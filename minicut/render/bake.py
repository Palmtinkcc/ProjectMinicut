"""Adaptive proxy: baked preview segments (Patch 39).

When you stop editing, the heavy parts of the timeline (many clips, effects, masks) are rendered once, in the background,
into small All-Intra H.264 files ("proxies", every frame is a key frame, so any frame can be read at once). While you play
or scrub, a frame inside a valid proxy is read from the file instead of being rendered again.

  * Used for the PREVIEW only. Export never reads a proxy.  Off by default (Settings).
  * A proxy is used only when the content hash of its time range is the same as now (clips, effects, keyframes, tracks, node
    graph, project size, source files, effect source code).  A changed clip makes only the ranges it touches stale; the rest are
    kept.  Because the hash decides, Undo finds the old proxy again at once (stale files stay on disk until the size limit).
  * Segment states:  LIVE (drawn directly: cheap, or not baked yet)  DIRTY (heavy, waiting for a bake)  BAKING  BAKED.
  * Levels S/M/L/XL are 2 s / 6 s / 18 s / 54 s.  Idle merge: S->M, M->L, L->XL only (3 steps, stream copy, nothing re-encoded).
    A merged file that turns stale is split back into its unchanged children (re-encoded from the proxy), so they are reused.
  * One bake at a time.  Baking waits until nothing happened for a while, pauses at once when you play or edit (the half-made
    file is dropped), and does not run while an export is running.  A half-made file is never used.
Everything here is wrapped so that any problem simply means the preview is drawn live, as before.
"""
import os, re, json, time, hashlib, threading, subprocess, weakref
import numpy as np
import cv2
from collections import OrderedDict

LIVE, DIRTY, BAKING, BAKED = "LIVE", "DIRTY", "BAKING", "BAKED"
NAMES = ("S", "M", "L", "XL")
BASE_SEC = 2.0; MULT = 3; N_LEVELS = 4
BAKE_Q = 0.5                  # proxies are made at half size; used when the preview asks for no more than this (x1.25)
IDLE_BAKE = 1.5               # seconds without any edit / seek / play before a bake starts
IDLE_MERGE = 8.0              # seconds before neighbouring proxies are merged
COST_MIN = 2.0                # a segment is baked when its cost score reaches this (or when it was measured too slow to draw live)
WINDOW_BEFORE, WINDOW_AFTER = 30.0, 120.0    # only segments near the playhead are looked at
MAX_BYTES = 2 * 1024 ** 3; MAX_AGE_DAYS = 30
_NAME = re.compile(r"^(\d)_(\d+)_([0-9a-f]{20})_(\d+)\.mkv$")
_EXPORT = [0]                 # > 0 while an export is running


def _ffmpeg():
    try: from ..shared.core import FFMPEG, NOWIN; return FFMPEG, NOWIN
    except Exception: return "ffmpeg", 0


def _cache_root():
    try: from ..shared.core import APP_DIR
    except Exception: APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")
    return os.path.join(APP_DIR, "bake")


def _enabled():
    try: from ..shared.core import CFG; return bool(CFG.get("bake"))
    except Exception: return False


def segment_cost(proj, clips, fx_specs=None):
    """How heavy it is to draw a time range live: clips x size, effects (heavy kinds count more), masks, blends, speed."""
    heavy = {"Particle", "3D object", "Distortion & warp", "Glitch", "VHS", "Wipes & shatter", "Repeat", "Background"}
    size = min(2.0, max(0.25, (proj.w * proj.h) / float(1920 * 1080))); tot = 0.0
    for c in clips:
        tot += {"video": 1.0, "gif": 0.6, "image": 0.3, "text": 0.4, "compound": 2.0}.get(c.get("kind"), 0.3) * size
        for e in (c.get("effects") or []):
            if e.get("on", True): tot += 1.6 if (fx_specs or {}).get(e.get("type"), {}).get("cat") in heavy else 0.8
        if c.get("mask") not in (None, "None", "") or c.get("mask_layers"): tot += 0.8
        if c.get("blend", "normal") != "normal": tot += 0.3
        if abs(float(c.get("speed", 1.0) or 1.0) - 1.0) > 1e-6: tot += 0.3
    return tot


class BakeManager:
    def __init__(self, renderer, snapshot, lower_priority=None, root=None, autostart=True):
        self._r = weakref.ref(renderer); self._snapshot = snapshot; self._lower = lower_priority
        self.root = root or _cache_root(); os.makedirs(self.root, exist_ok=True)
        self.index = {}                      # (level, idx) -> [entry, ...]  entry: {"path","hash","n","t"}
        self.state = {}                      # (level, idx) -> LIVE / DIRTY / BAKING / BAKED   (S level, near the playhead)
        self.live = None; self.playhead = 0.0; self.last_act = time.monotonic(); self.last_hit = 0.0
        self.enabled = _enabled; self._stop = threading.Event(); self._hm = {}; self._hm_ver = -1; self._fsig = {}
        self._caps = OrderedDict(); self._cl = threading.Lock(); self._snap = None; self._snap_ver = -1; self._merge_fail = set(); self._bad = {}; self.ms = {}
        self._scan(); self.prune()
        self.thread = None
        if autostart: self.thread = threading.Thread(target=self._run, name="MiniCutBake", daemon=True); self.thread.start()

    # ------------------------------------------------------------------ the activity clock
    def touch(self, proj, t):
        self.live = proj; self.playhead = float(t); self.last_act = time.monotonic()

    def stop(self): self._stop.set()

    def note(self, proj, t, ms):
        """How long drawing this frame live took. Segments that are measured too slow become DIRTY even if their static score is low."""
        if ms < 2.0: return                                   # a frame that came from a cache says nothing
        fps = max(1, proj.fps); idx = int(round(max(0.0, t) * fps)) // self.nf(0, fps); old = self.ms.get(idx)
        self.ms[idx] = ms if old is None else old * 0.7 + ms * 0.3

    def target_ms(self, fps):
        try: from ..shared.core import CFG; pf = float(CFG.get("preview_fps", 30))
        except Exception: pf = 30.0
        return 1000.0 / max(1.0, min(float(fps), pf)) * 0.7

    # ------------------------------------------------------------------ geometry and hashes
    @staticmethod
    def nf(level, fps): return int(round(BASE_SEC * max(1, fps))) * (MULT ** level)

    def _file_sig(self, path):
        if not path: return None
        v = self._fsig.get(path)
        if v is None:
            try: st = os.stat(path); v = (st.st_size, st.st_mtime_ns)
            except OSError: v = None
            self._fsig[path] = v
        return v

    def rhash(self, proj, level, idx):
        r = self._r(); ver = r.version if r is not None else 0
        if ver != self._hm_ver: self._hm.clear(); self._fsig.clear(); self._hm_ver = ver
        key = (level, idx, id(proj)); h = self._hm.get(key)
        if h is not None: return h
        fps = max(1, proj.fps); nf = self.nf(level, fps); a = idx * nf / float(fps); b = (idx + 1) * nf / float(fps)
        vt = [tr for tr in proj.tracks if tr.get("kind") == "video"]; ids = {tr.get("id") for tr in vt}
        cl = [c for c in proj.clips if c.get("track") in ids and c["start"] < b and c["start"] + c["dur"] > a]
        try:
            from . import fxcache; code = fxcache._code_hash()
        except Exception: code = ""
        data = json.dumps([proj.w, proj.h, fps, proj.bg, BAKE_Q, getattr(proj, "graph", None), vt, cl, [self._file_sig(c.get("path")) for c in cl], code, level],
                          sort_keys=True, default=str)
        h = hashlib.sha1(data.encode("utf-8", "replace")).hexdigest()[:20]; self._hm[key] = h; return h

    # ------------------------------------------------------------------ files
    def _path(self, level, idx, h, n): return os.path.join(self.root, "%d_%d_%s_%d.mkv" % (level, idx, h, n))

    def _scan(self):
        self.index.clear()
        try: names = os.listdir(self.root)
        except OSError: return
        for nme in names:
            f = os.path.join(self.root, nme)
            if nme.endswith(".part"):
                try: os.remove(f)
                except OSError: pass
                continue
            m = _NAME.match(nme)
            if m:
                try: t = os.path.getmtime(f)
                except OSError: continue
                self._add(int(m.group(1)), int(m.group(2)), {"path": f, "hash": m.group(3), "n": int(m.group(4)), "t": t})

    def _add(self, level, idx, e):
        lst = self.index.setdefault((level, idx), [])
        if not any(x["hash"] == e["hash"] for x in lst): lst.append(e)

    def _remove(self, level, idx, e):
        lst = self.index.get((level, idx), [])
        if e in lst: lst.remove(e)
        if not lst: self.index.pop((level, idx), None)
        with self._cl:
            c = self._caps.pop(e["path"], None)
        if c is not None:
            try: c[0].release()
            except Exception: pass
        for p in (e["path"], e["path"][:-4] + ".json"):
            try: os.remove(p)
            except OSError: pass

    def prune(self):
        """Delete files older than the age limit, then the least recently used ones while over the size limit."""
        try:
            items = []; now = time.time()
            for lv_idx, lst in list(self.index.items()):
                for e in list(lst):
                    try: items.append((os.path.getmtime(e["path"]), os.path.getsize(e["path"]), lv_idx, e))
                    except OSError: self._remove(lv_idx[0], lv_idx[1], e)
            items.sort(key=lambda x: x[0]); total = sum(i[1] for i in items)
            try: from ..shared.core import CFG; limit = max(0.5, float(CFG.get("bake_max_gb", 2))) * 1024 ** 3      # Patch 44: set in Settings
            except Exception: limit = MAX_BYTES
            for mt, sz, lv_idx, e in items:
                if total <= limit * 0.8 and now - mt <= MAX_AGE_DAYS * 86400: break
                self._remove(lv_idx[0], lv_idx[1], e); total -= sz
        except Exception as ex: print("[bake] prune:", ex)

    # ------------------------------------------------------------------ reading (playback)
    def _read(self, e, k):
        with self._cl:
            c = self._caps.get(e["path"])
            if c is None:
                cap = cv2.VideoCapture(e["path"])
                if not cap.isOpened(): return None
                c = [cap, -1]; self._caps[e["path"]] = c
                while len(self._caps) > 3: self._caps.popitem(last=False)[1][0].release()
            self._caps.move_to_end(e["path"]); cap, pos = c
            if pos + 1 != k: cap.set(cv2.CAP_PROP_POS_FRAMES, k)
            ok, img = cap.read(); c[1] = k if ok else -1
        if not ok or img is None: return None
        now = time.time()
        if now - e.get("t", 0) > 30:
            e["t"] = now
            try: os.utime(e["path"], None)
            except OSError: pass
        return img

    def lookup(self, proj, t, q):
        """The frame from a valid proxy (BGR, the size the preview asks for) or None."""
        if not self.enabled() or q > BAKE_Q * 1.25 + 1e-6: return None
        fps = max(1, proj.fps); f = int(round(max(0.0, t) * fps))
        for level in range(N_LEVELS - 1, -1, -1):
            nf = self.nf(level, fps); idx = f // nf; lst = self.index.get((level, idx))
            if not lst: continue
            h = self.rhash(proj, level, idx); e = next((x for x in lst if x["hash"] == h), None)
            if e is None: continue
            k = f - idx * nf
            if k >= e["n"]: continue
            img = self._read(e, k)
            if img is None: continue
            W, H = max(2, int(round(proj.w * q))), max(2, int(round(proj.h * q)))
            if img.shape[1] != W or img.shape[0] != H:
                img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA if W < img.shape[1] else cv2.INTER_LINEAR)
            self.last_hit = time.monotonic(); return img
        return None

    # ------------------------------------------------------------------ background work
    def _idle_for(self): return time.monotonic() - self.last_act

    def _wait_idle(self, need, ver):
        """Wait until nothing happened for `need` seconds. False if the project changed or we must stop."""
        while True:
            r = self._r()
            if r is None or self._stop.is_set() or not self.enabled(): return False
            if r.version != ver: return False
            if not _EXPORT[0] and self._idle_for() >= need: return True
            time.sleep(0.1)

    def _run(self):
        if self._lower:
            try: self._lower()
            except Exception: pass
        while not self._stop.wait(0.3):
            r = self._r()
            if r is None: return
            try:
                if not self.enabled() or self.live is None or _EXPORT[0] or self._idle_for() < IDLE_BAKE: continue
                self.work_once()
            except Exception as ex: print("[bake]", ex); time.sleep(2)

    def _snap_now(self, r):
        if self._snap is not None and self._snap_ver == r.version: return self._snap
        for _ in range(4):
            try:
                ver = r.version; s = self._snapshot(self.live)
                if r.version == ver: self._snap, self._snap_ver = s, ver; return s
            except RuntimeError: continue
        return None

    def candidates(self, snap):
        """Update the LIVE/DIRTY/BAKED states near the playhead; the DIRTY ones, most valuable first."""
        fps = max(1, snap.fps); nf = self.nf(0, fps); total = int(round(snap.duration() * fps))
        a = max(0, int((self.playhead - WINDOW_BEFORE) * fps) // nf); b = min((total + nf - 1) // nf, int((self.playhead + WINDOW_AFTER) * fps) // nf + 1)
        try:
            from .effects import FX; specs = FX
        except Exception: specs = {}
        out = []; ph = self.playhead
        for idx in range(a, b):
            if self.state.get((0, idx)) == BAKING: continue
            if self._covered(snap, idx, fps): self.state[(0, idx)] = BAKED; continue
            s, e = idx * nf / float(fps), (idx + 1) * nf / float(fps)
            vt = {tr.get("id") for tr in snap.tracks if tr.get("kind") == "video" and not tr.get("hidden")}
            cl = [c for c in snap.clips if c.get("track") in vt and c["start"] < e and c["start"] + c["dur"] > s]
            cost = segment_cost(snap, cl, specs); meas = self.ms.get(idx)
            if meas is not None and cl: cost = max(cost, COST_MIN * meas / self.target_ms(fps))     # measured: slower than the frame budget
            if cost >= COST_MIN and self._bad.get((idx, self.rhash(snap, 0, idx)), 0) < 2:      # a segment that failed twice waits for a change
                self.state[(0, idx)] = DIRTY; dist = abs((s + e) / 2.0 - ph); out.append((-(cost / (1.0 + dist / 20.0)), idx))
            else: self.state[(0, idx)] = LIVE
        out.sort(); return [i for _, i in out]

    def _covered(self, snap, idx0, fps):
        for level in range(N_LEVELS):
            idx = idx0 // (MULT ** level); lst = self.index.get((level, idx))
            if lst:
                h = self.rhash(snap, level, idx)
                if any(x["hash"] == h for x in lst): return True
        return False

    def work_once(self):
        r = self._r()
        if r is None or self.live is None: return False
        snap = self._snap_now(r)
        if snap is None: return False
        ver = r.version
        todo = self.candidates(snap)
        if todo: return self.bake(snap, todo[0], ver)
        if self._wait_idle(IDLE_MERGE, ver):
            if self.split_stale(snap, ver): return True
            if self.merge_one(snap, ver): return True
            self.prune()
        return False

    # ------------------------------------------------------------------ encoding
    def _encoder(self, W, H, fps, out):
        ff, nowin = _ffmpeg()
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-g", "1", "-pix_fmt", "yuv420p", "-f", "matroska", out]
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=nowin)

    @staticmethod
    def _end_encoder(proc, ok):
        try:
            if ok: proc.stdin.close(); return proc.wait(timeout=120) == 0
        except Exception: pass
        try: proc.kill()
        except Exception: pass
        try: proc.wait(timeout=5)
        except Exception: pass
        return False

    def bake(self, snap, idx, ver, render=None):
        """Render one S segment and store it. Returns True when a proxy was made."""
        r = self._r(); fps = max(1, snap.fps); nf = self.nf(0, fps); s = idx * nf; total = int(round(snap.duration() * fps)); e = min(s + nf, total); n = e - s
        if n <= 0: return False
        render = render or (lambda t: r.render(snap, t, BAKE_Q, False))
        h = self.rhash(snap, 0, idx); W = max(2, int(round(snap.w * BAKE_Q))) // 2 * 2; H = max(2, int(round(snap.h * BAKE_Q))) // 2 * 2
        final = self._path(0, idx, h, n); tmp = final + ".part"; self.state[(0, idx)] = BAKING; proc = None; ok = False
        try:
            proc = self._encoder(W, H, fps, tmp)
            for f in range(s, e):
                if not self._wait_idle(IDLE_BAKE, ver): raise InterruptedError()      # you did something: drop the half-made file
                with r._src_lock: img = render(f / float(fps))
                if img is None or img.ndim != 3: raise RuntimeError("no frame")
                img = np.ascontiguousarray(img[:H, :W, :3])
                if img.shape[0] != H or img.shape[1] != W: img = cv2.resize(img, (W, H))
                proc.stdin.write(img.tobytes()); time.sleep(0.001)
            ok = self._end_encoder(proc, True); proc = None
            if not ok or not os.path.isfile(tmp): raise RuntimeError("encoder failed")
            if r.version != ver: raise InterruptedError()
            os.replace(tmp, final); self._add(0, idx, {"path": final, "hash": h, "n": n, "t": time.time()}); self.state[(0, idx)] = BAKED
            return True
        except InterruptedError:
            pass
        except Exception as ex:
            print("[bake] segment", idx, "failed:", ex); k = (idx, h); self._bad[k] = self._bad.get(k, 0) + 1
        finally:
            if proc is not None: self._end_encoder(proc, False)
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except OSError: pass
            if self.state.get((0, idx)) == BAKING: self.state[(0, idx)] = DIRTY
        return False

    # ------------------------------------------------------------------ merge / split
    def merge_one(self, snap, ver):
        """S->M, M->L, L->XL by stream copy. Only whole groups of valid neighbours; nothing is re-encoded."""
        fps = max(1, snap.fps); ff, nowin = _ffmpeg()
        for level in range(N_LEVELS - 1):
            groups = {}
            for (lv, idx), lst in list(self.index.items()):
                if lv == level: groups.setdefault(idx // MULT, []).append(idx)
            for pidx, kids in sorted(groups.items()):
                if (level + 1, pidx) in self.index and any(x["hash"] == self.rhash(snap, level + 1, pidx) for x in self.index[(level + 1, pidx)]): continue
                if sorted(kids) != list(range(pidx * MULT, pidx * MULT + MULT)) or (level, pidx) in self._merge_fail: continue
                es = []
                for ci in sorted(kids):
                    h = self.rhash(snap, level, ci); e = next((x for x in self.index[(level, ci)] if x["hash"] == h), None)
                    if e is None or e["n"] != self.nf(level, fps): es = []; break
                    es.append(e)
                if not es or not self._wait_idle(IDLE_MERGE, ver): continue
                n = sum(x["n"] for x in es); h = self.rhash(snap, level + 1, pidx); final = self._path(level + 1, pidx, h, n); tmp = final + ".part"
                lst = tmp + ".txt"
                try:
                    with open(lst, "w", encoding="utf-8") as fh:
                        for x in es: fh.write("file '%s'\n" % x["path"].replace("\\", "/").replace("'", "'\\''"))
                    p = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-f", "matroska", tmp],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=nowin, timeout=300)
                    cap = cv2.VideoCapture(tmp); cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
                    if p.returncode != 0 or cnt != n: raise RuntimeError("merge check failed (%d of %d frames)" % (cnt, n))
                    os.replace(tmp, final)
                    with open(final[:-4] + ".json", "w", encoding="utf-8") as fh: json.dump({"children": [{"hash": x["hash"], "n": x["n"]} for x in es]}, fh)
                    self._add(level + 1, pidx, {"path": final, "hash": h, "n": n, "t": time.time()})
                    for ci, x in zip(sorted(kids), es): self._remove(level, ci, x)
                    return True
                except Exception as ex:
                    print("[bake] merge skipped:", ex); self._merge_fail.add((level, pidx))
                finally:
                    for p_ in (tmp, lst):
                        try: os.remove(p_)
                        except OSError: pass
        return False

    def split_stale(self, snap, ver):
        """A merged proxy that is no longer valid: give back its children that are still valid (re-encoded from the proxy)."""
        fps = max(1, snap.fps)
        for (level, idx), lst in list(self.index.items()):
            if level == 0 or any(x["hash"] == self.rhash(snap, level, idx) for x in lst): continue
            for e in list(lst):
                side = e["path"][:-4] + ".json"
                try:
                    with open(side, encoding="utf-8") as fh: kids = json.load(fh)["children"]
                except Exception: continue
                if e.get("split_done"): continue
                cap = None; made = False
                for j, kd in enumerate(kids):
                    cidx = idx * MULT + j; cnf = self.nf(level - 1, fps)
                    if self.rhash(snap, level - 1, cidx) != kd["hash"]: continue
                    if any(x["hash"] == kd["hash"] for x in self.index.get((level - 1, cidx), [])): continue
                    if cap is None: cap = cv2.VideoCapture(e["path"])
                    final = self._path(level - 1, cidx, kd["hash"], kd["n"]); tmp = final + ".part"; proc = None; ok = False
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, j * cnf); proc = None
                        for f in range(kd["n"]):
                            if not self._wait_idle(IDLE_MERGE, ver): raise InterruptedError()
                            okr, img = cap.read()
                            if not okr: raise RuntimeError("read failed")
                            if proc is None: proc = self._encoder(img.shape[1], img.shape[0], fps, tmp)
                            proc.stdin.write(np.ascontiguousarray(img).tobytes())
                        ok = self._end_encoder(proc, True); proc = None
                        if ok and os.path.isfile(tmp): os.replace(tmp, final); self._add(level - 1, cidx, {"path": final, "hash": kd["hash"], "n": kd["n"], "t": time.time()}); made = True
                    except InterruptedError: return False
                    except Exception as ex: print("[bake] split skipped:", ex)
                    finally:
                        if proc is not None: self._end_encoder(proc, False)
                        try:
                            if os.path.exists(tmp): os.remove(tmp)
                        except OSError: pass
                if cap is not None: cap.release()
                e["split_done"] = True
                if made: return True
        return False

    def segments(self, fps):
        """(start s, end s, state) of every 2 s segment that is not plainly LIVE: for the coloured strip under the ruler."""
        nf = self.nf(0, fps)
        return [(i * nf / float(fps), (i + 1) * nf / float(fps), st) for (lv, i), st in list(self.state.items()) if lv == 0 and st != LIVE]

    def status(self):
        c = {LIVE: 0, DIRTY: 0, BAKING: 0, BAKED: 0}
        for v in self.state.values(): c[v] = c.get(v, 0) + 1
        return c


def clear_cache(bm=None):
    """Delete every baked proxy file (and forget them in the running manager). Returns (files, megabytes)."""
    root = bm.root if bm is not None else _cache_root(); n = 0; size = 0
    if bm is not None:
        with bm._cl:
            for c in list(bm._caps.values()):
                try: c[0].release()
                except Exception: pass
            bm._caps.clear()
    if os.path.isdir(root):
        for nme in os.listdir(root):
            f = os.path.join(root, nme)
            try: sz = os.path.getsize(f); os.remove(f); n += 1; size += sz
            except OSError: pass
    if bm is not None:
        bm.index.clear(); bm.state.clear(); bm.ms.clear(); bm._merge_fail.clear(); bm._bad.clear()
    return n, size / 1e6


# ---------------------------------------------------------------------------------------------------------- hooks
def install(Renderer, RenderWorker, snapshot, tls, lower_priority=None):
    """Put the proxy lookup in front of Renderer.render_cached and the activity clock in RenderWorker.submit."""
    orig_rc = Renderer.render_cached; orig_submit = RenderWorker.submit

    def render_cached(self, proj, t, q, fast=False, ver=None, fp=None):
        bm = getattr(self, "bake", None)
        if bm is not None and not fast and getattr(tls, "preview", False) and _enabled():
            try: img = bm.lookup(proj, t, q)
            except Exception as ex: print("[bake] lookup:", ex); img = None
            if img is not None: return img
        if bm is None or fast or not getattr(tls, "preview", False): return orig_rc(self, proj, t, q, fast, ver, fp)
        t0 = time.perf_counter(); out = orig_rc(self, proj, t, q, fast, ver, fp)
        try: bm.note(proj, t, (time.perf_counter() - t0) * 1000.0)
        except Exception: pass
        return out

    def submit(self, proj, t, q, fast):
        try:
            bm = getattr(self.r, "bake", None)
            if bm is None and _enabled(): bm = self.r.bake = BakeManager(self.r, snapshot, lower_priority)
            if bm is not None: bm.touch(proj, t)
        except Exception as ex: print("[bake] attach:", ex)
        return orig_submit(self, proj, t, q, fast)

    Renderer.render_cached = render_cached; RenderWorker.submit = submit


def guard_export(ExportWorker):
    """No baking while an export runs."""
    orig = ExportWorker.run

    def run(self):
        _EXPORT[0] += 1
        try: return orig(self)
        finally: _EXPORT[0] = max(0, _EXPORT[0] - 1)
    ExportWorker.run = run

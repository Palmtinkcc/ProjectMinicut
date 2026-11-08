"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""
from ..shared.deps import *
from ..shared.core import *


_HW_DECODE_VALIDATION_CACHE = {}


def _hw_frame_matches_cpu(hw_frame, cpu_frame):
    """Conservatively reject visibly different hardware-decoded frames (including pink/magenta bands)."""
    if hw_frame is None or cpu_frame is None or hw_frame.shape != cpu_frame.shape:
        return False
    # Compare reduced copies: full-resolution per-pixel comparisons were expensive during clip loading.
    def sample(frame):
        h, w = frame.shape[:2]
        scale = min(1.0, 320.0 / max(1, w), 180.0 / max(1, h))
        if scale < 1.0:
            frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        return frame.astype(np.int16)
    hw = sample(hw_frame)
    cpu = sample(cpu_frame)
    if hw.shape != cpu.shape:
        return False
    diff = np.abs(hw - cpu)
    mean_diff = float(diff.mean())
    severe = float((diff.max(axis=2) > 48).mean())
    top_h = max(1, diff.shape[0] // 8)
    top = diff[:top_h]
    body = diff[top_h:] if top_h < diff.shape[0] else diff
    top_mean = float(top.mean())
    body_mean = float(body.mean())
    top_severe = float((top.max(axis=2) > 48).mean())
    pink_band = top_mean > max(24.0, body_mean * 3.0) and top_severe > 0.10
    return mean_diff <= 14.0 and severe <= 0.08 and not pink_band


def _hw_validation_key(path):
    """Cache validation only for the exact file version that was checked."""
    try:
        st = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def open_capture(path):
    """Open optional FFmpeg hardware decoding with real-frame validation and CPU fallback.

    Successful/failed validation is cached per file version so opening the same clip repeatedly does not decode
    and compare reference frames every time. The first open still validates actual frames against CPU decoding.
    """
    if not CFG.get("hw_decode"):
        return cv2.VideoCapture(path)

    key = _hw_validation_key(path)
    cached = _HW_DECODE_VALIDATION_CACHE.get(key) if key is not None else None
    if cached is False:
        return cv2.VideoCapture(path)

    cap = None
    cpu = None
    try:
        backend = getattr(cv2, "CAP_FFMPEG", None)
        hw_prop = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)
        hw_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)
        if backend is None or hw_prop is None or hw_any is None:
            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
            return cv2.VideoCapture(path)

        cap = cv2.VideoCapture(path, backend, [hw_prop, hw_any])
        if not cap.isOpened() or cap.get(hw_prop) <= 0:
            if cap is not None: cap.release()
            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
            return cv2.VideoCapture(path)

        # A prior successful real-frame test is valid for this unchanged file and backend setting.
        if cached is True:
            return cap

        cpu = cv2.VideoCapture(path)
        if not cpu.isOpened():
            cap.release(); cap = None
            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
            return cv2.VideoCapture(path)

        # Two frames give a modest safety check while reducing first-open CPU work vs. three full-size compares.
        for _ in range(2):
            hw_ok, hw_frame = cap.read()
            cpu_ok, cpu_frame = cpu.read()
            if not hw_ok or not cpu_ok or not _hw_frame_matches_cpu(hw_frame, cpu_frame):
                cap.release(); cap = None
                if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
                return cv2.VideoCapture(path)

        if not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
            cap.release(); cap = None
            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
            return cv2.VideoCapture(path)
        if key is not None:
            _HW_DECODE_VALIDATION_CACHE[key] = True
            # Bound memory when projects contain many distinct media files.
            while len(_HW_DECODE_VALIDATION_CACHE) > 256:
                _HW_DECODE_VALIDATION_CACHE.pop(next(iter(_HW_DECODE_VALIDATION_CACHE)))
        return cap
    except Exception:
        if cap is not None:
            try: cap.release()
            except Exception: pass
        if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False
        return cv2.VideoCapture(path)
    finally:
        if cpu is not None:
            try: cpu.release()
            except Exception: pass


import threading, collections
PLAYING = [False]      # set by playback: background work (thumbnails, waveforms) waits while the preview plays
PROXY_HEIGHT = 540
PROXY_CHUNK = 2.0                 # seconds per proxy piece (pieces are finished one by one, in order)
PROXY_RETRY_AFTER = 20.0          # seconds before a failed video is tried again


def proxy_dir(path, create=True):
    """Folder with the proxy pieces of this video. The name depends on the file and on the proxy settings,
    so changing the size / quality never reuses old pieces. create=False only looks (no folder is made)."""
    import hashlib
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d|%d|%s|%s" % (os.path.abspath(path), st.st_size, int(st.st_mtime),
                                            CFG.get("proxy_height", PROXY_HEIGHT), CFG.get("proxy_quality", 23))).encode("utf-8")).hexdigest()[:24]
    d = os.path.join(APP_DIR, "proxies", key)
    if create: os.makedirs(d, exist_ok=True)
    return d


def proxy_index(d):
    """Pieces written so far: [(file name, start second, end second)] from index.csv (ffmpeg writes a line per finished piece)."""
    out = []
    try:
        with open(os.path.join(d, "index.csv"), encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3: continue
                try: out.append((parts[0], float(parts[1]), float(parts[2])))
                except ValueError: continue
    except OSError: pass
    return out


_PIECES_CACHE = {}


def proxy_pieces(path):
    """{piece number: (start, end)} of the finished proxy pieces. Cached by the index file's time, so calling it
    often (the timeline does, twice a second) costs almost nothing unless the proxy changed."""
    try: d = proxy_dir(path, create=False)
    except Exception: return {}
    try: mt = os.path.getmtime(os.path.join(d, "index.csv"))
    except OSError:
        _PIECES_CACHE.pop(d, None); return {}
    hit = _PIECES_CACHE.get(d)
    if hit is not None and hit[0] == mt: return hit[1]
    out = {}
    for name, s, e in proxy_index(d):
        m = re.match(r"p(\d+)\.mp4$", name)
        if m: out[int(m.group(1))] = (s, e)
    _PIECES_CACHE[d] = (mt, out)
    return out


def merged_runs(pieces):
    """[(start, end)] of the finished pieces, joined where they touch: far fewer rectangles to draw."""
    runs = []
    for k in sorted(pieces):
        s, e = pieces[k]
        if runs and abs(runs[-1][1] - s) < 1e-3: runs[-1] = (runs[-1][0], e)
        else: runs.append((s, e))
    return runs


_RUNS_CACHE = {}


def proxy_runs(path):
    """Merged runs of the finished pieces, cached with them (what the timeline draws)."""
    try: d = proxy_dir(path, create=False)
    except Exception: return []
    pieces = proxy_pieces(path)
    hit = _RUNS_CACHE.get(d)
    if hit is not None and hit[0] is pieces: return hit[1]
    runs = merged_runs(pieces)
    _RUNS_CACHE[d] = (pieces, runs)
    return runs


def video_duration(path):
    cap = cv2.VideoCapture(safe_path(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 30; n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0; cap.release()
    return n / fps if n > 0 else 0.0


from ..shared.tasks import TASKS
import bisect, heapq, math, re, shutil, threading, time, subprocess


def _proxy_cmd(path, d, enc):
    h = int(CFG.get("proxy_height", PROXY_HEIGHT)); crf = int(CFG.get("proxy_quality", 23))
    cmd = [FFMPEG, "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", path, "-an", "-vf", "scale=-2:min(%d\\,ih)" % h]
    if enc is None:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-threads", str(int(CFG.get("bg_threads", max(1, (os.cpu_count() or 4) // 2))))]
    else:
        # Settings widely supported across driver versions (no "usage=ultralowlatency": some AMF drivers reject it
        # together with "-quality speed" and fail with "Invalid argument"). No B-frames, since every frame is a keyframe.
        vendor, name = enc; cmd += ["-c:v", name, "-bf", "0"]
        if vendor == "nvenc": cmd += ["-preset", "p1", "-rc", "constqp", "-qp", str(crf)]
        elif vendor == "qsv": cmd += ["-global_quality", str(crf), "-look_ahead", "0"]
        else: cmd += ["-usage", "transcoding", "-quality", "speed", "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    cmd += ["-g", "1", "-pix_fmt", "yuv420p", "-f", "segment", "-segment_time", "%.3f" % PROXY_CHUNK,
            "-reset_timestamps", "1", "-segment_format", "mp4", "-segment_list", os.path.join(d, "index.csv"),
            "-segment_list_type", "csv", os.path.join(d, "p%05d.mp4")]
    return cmd


def _clean_dir(d):
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if os.path.isfile(p):
            try: os.remove(p)
            except OSError: pass


def _first_piece_ok(d):
    """The first finished piece opens and gives a picture (a GPU encoder that 'worked' but wrote nothing usable fails here)."""
    idx = proxy_index(d)
    if not idx: return False
    cap = cv2.VideoCapture(os.path.join(d, idx[0][0]))
    try:
        ok, fr = cap.read(); return bool(ok) and fr is not None and fr.size > 0
    finally: cap.release()


def _run_proxy(path, d, alive, task, enc, dur):
    try:
        proc = subprocess.Popen(_proxy_cmd(path, d, enc), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                creationflags=NOWIN | (0x00004000 if os.name == "nt" else 0))
    except Exception as ex:
        print("proxy error:", ex); return "failed"
    for line in proc.stdout:
        if not alive():
            proc.kill(); proc.wait(); return "cancelled"
        if task is not None and line.startswith("out_time_us="):
            try:
                secs = int(line.split("=", 1)[1]) / 1e6
                task.done = int(secs / PROXY_CHUNK); task.detail = "%d s of %d s%s" % (int(secs), int(dur or 0), "  (GPU)" if enc else "")
            except ValueError: pass
    rc = proc.wait()
    if not alive(): return "cancelled"
    if rc == 0 and proxy_index(d) and _first_piece_ok(d): return "done"
    err = (proc.stderr.read() or "")[-300:]
    if err: print("proxy ffmpeg (%s):" % (enc[1] if enc else "libx264"), err)
    return "failed"


_BAD_HW = set()     # encoder names that failed a real proxy encode this session: skipped from then on (no repeated errors)


def reset_bad_hw():
    """Forget which hardware encoders failed, so they are tried again (called by Settings -> Check GPU encoders)."""
    _BAD_HW.clear()


def make_proxy(path, d, alive, task=None):
    """One ffmpeg run turns the whole video into proxy pieces (about 2 s each) and writes the exact timing of every piece
    to index.csv. The GPU encoder is tried first when Settings allow it, it passed the quick self-test, and it has not
    already failed a real encode this session; if it fails here, the CPU encoder is used and the GPU encoder is skipped
    for the rest of the session (so later videos do not repeat the same failure). Returns 'done', 'failed' or 'cancelled'."""
    if os.path.exists(os.path.join(d, "done")): return "done"
    dur = video_duration(path)
    if task is not None: task.total = int(math.ceil(dur / PROXY_CHUNK)) if dur else None
    encs = []
    if CFG.get("proxy_hw", "auto") != "cpu":
        try:
            from ..shared.hwaccel import pick_hw_encoder
            e = pick_hw_encoder(False, "auto")
            if e and e[1] not in _BAD_HW: encs.append(e)
        except Exception as ex: print("proxy gpu check:", ex)
    encs.append(None)
    for enc in encs:
        _clean_dir(d)                                    # an earlier or failed run: start clean
        st = _run_proxy(path, d, alive, task, enc, dur)
        if st == "done": open(os.path.join(d, "done"), "w").close(); return "done"
        if st == "cancelled": return "cancelled"
        if enc is not None: _BAD_HW.add(enc[1])
    return "failed"


def proxy_cleanup(budget, keep):
    """Keep the proxy folder under the budget: the least recently used videos are removed first. Never removes 'keep'."""
    root = os.path.join(APP_DIR, "proxies")
    if not os.path.isdir(root): return
    dirs = []; total = 0
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if not os.path.isdir(p): continue
        size = 0
        for f in os.listdir(p):
            try: size += os.path.getsize(os.path.join(p, f))
            except OSError: pass
        dirs.append((os.path.getmtime(p), size, p)); total += size
    dirs.sort()
    for _, size, p in dirs:
        if total <= budget: break
        if p in keep: continue
        shutil.rmtree(p, ignore_errors=True); total -= size


class ProxyManager:
    """Builds the proxies in one background thread. The video nearest the playhead is built first (priority).
    reset() cancels everything (settings changed, cache cleared). The folder is kept under the disk budget."""
    def __init__(self):
        self.gen = 0; self.state = {}; self.lock = threading.Lock(); self.cv = threading.Condition(self.lock)
        self.heap = []; self.seq = 0; self.thread = None; self.pool = None
    def want(self, path, prio=0.0):
        d = proxy_dir(path)
        with self.lock:
            st = self.state.get(d)
            if st is not None:
                status, when = st
                if status in ("queued", "running"): return
                if status == "done" and proxy_pieces(path): return
                if time.monotonic() - when < PROXY_RETRY_AFTER: return
            self.state[d] = ("queued", time.monotonic()); self.seq += 1
            heapq.heappush(self.heap, (prio, self.seq, path, d, self.gen)); self.cv.notify()
            if self.thread is None:
                self.thread = threading.Thread(target=self._loop, daemon=True, name="proxy-builder"); self.thread.start()
    def _keep(self, d):
        keep = {d}
        try:
            if self.pool is not None:
                keep |= {s.dir for s in list(self.pool.src.values()) if getattr(s, "dir", None)}
        except RuntimeError: pass
        return keep
    def _loop(self):
        while True:
            with self.lock:
                while not self.heap: self.cv.wait()
                prio, _, path, d, g = heapq.heappop(self.heap)
                if g != self.gen: continue
                self.state[d] = ("running", time.monotonic())
            status = "failed"; task = TASKS.start("proxy", "Proxy  " + os.path.basename(path))
            try: status = make_proxy(path, d, lambda: g == self.gen, task)
            except Exception as ex: print("proxy error:", ex)
            finally: task.finish()
            try: proxy_cleanup(float(CFG.get("proxy_budget_gb", 40)) * 1e9, self._keep(d))
            except Exception as ex: print("proxy cleanup:", ex)
            with self.lock:
                if g == self.gen: self.state[d] = (status, time.monotonic())
    def reset(self):
        with self.lock: self.gen += 1; self.state.clear(); self.heap = []


PROXY = ProxyManager()
PROXY = ProxyManager()


class _Reader:
    """One opened video file. Reads forward when the next frame is close, seeks otherwise."""
    def __init__(self, cap):
        self.cap = cap; self.pos = -10; self.raw = None; self.n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    def read(self, idx):
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        if idx != self.pos or self.raw is None:
            gap = idx - self.pos
            if 0 < gap <= 8:
                for _ in range(gap - 1): self.cap.grab()
            else: self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, f = self.cap.read()
            if ok: self.raw = f; self.pos = idx
            else:
                self.pos = -10
                if self.raw is None: return None
        return self.raw
    def release(self):
        try: self.cap.release()
        except Exception: pass


# ---------------------------------------------------------------------------------------------------------------
# Patch 45 / 48: GPU decoding through an FFmpeg pipe, used only for sustained playback.
#   * Jumps (clicking, scrubbing) and the first frames of every start are read by OpenCV: it seeks at once. An FFmpeg process needs
#     time to start (a GPU decoder even more), so it is never started for a jump.
#   * After _RUN_MIN frames in a row (it is playing) a process is started in the BACKGROUND a little ahead of the playhead; when it
#     has its first frame it takes over. Nothing waits for it.
#   * That first frame is compared with the OpenCV frame (a pink band or wrong colours fail): the backend is then marked bad for this
#     kind of video (codec and size) and the next one is tried. The answer is kept in hwdec.json, so it is asked once, not at every start.
#   * Any problem: this video goes back to OpenCV. A process that is not used for 4 s is stopped. At most 6 run at once.
#   * MINICUT_CV2_DECODE=1 uses only OpenCV.
# ---------------------------------------------------------------------------------------------------------------
import json as _json
_FF_LIVE = OrderedDict(); _FF_LOCK = threading.Lock()      # readers that own a running ffmpeg (kept to a few)
_FF_MAX_LIVE = 6; _FF_PENDING = [0]; _RUN_MIN = 10; _BAD_MAX_AGE = 14 * 86400
_BAD_HW = {}; _HW_LISTED = []; _HW_DB = {"v": 1, "cls": {}}; _HW_STATE = {"loaded": False}; _HW_LOCK = threading.Lock(); _FF_REAPER = [None]


def _hw_candidates():
    """Hardware decoders this FFmpeg build lists, best first. Listed does not mean working: each is checked when it is used."""
    if not _HW_LISTED:
        try:
            out = subprocess.run([FFMPEG, "-hide_banner", "-hwaccels"], capture_output=True, text=True, errors="ignore",
                                 creationflags=NOWIN, timeout=15).stdout.split()
        except Exception:
            out = []
        order = ["d3d11va", "dxva2", "cuda", "qsv"] if os.name == "nt" else ["cuda", "vaapi", "videotoolbox", "qsv"]
        _HW_LISTED.append([b for b in order if b in out])
    return _HW_LISTED[0]


def _hw_path():
    try: from ..shared.core import APP_DIR
    except Exception: APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")
    return os.path.join(APP_DIR, "hwdec.json")


def _hw_db():
    with _HW_LOCK:
        if not _HW_STATE["loaded"]:
            _HW_STATE["loaded"] = True
            try:
                with open(_hw_path(), encoding="utf-8") as fh: d = _json.load(fh)
                if isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("cls"), dict): _HW_DB["cls"] = d["cls"]
            except Exception: pass
        return _HW_DB["cls"]


def _hw_save():
    try:
        p = _hw_path(); os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp"
        with _HW_LOCK:
            with open(tmp, "w", encoding="utf-8") as fh: _json.dump(_HW_DB, fh)
        os.replace(tmp, p)
    except Exception: pass


def _ff_reap():
    while True:
        time.sleep(2.0); now = time.monotonic()
        with _FF_LOCK: idle = [r for r in _FF_LIVE.values() if now - r.last_use > 4.0]
        for r in idle: r._stop()


class _FFReader:
    """Same interface as _Reader (read(idx) / release()). OpenCV serves jumps and the start; an FFmpeg pipe serves long runs."""
    def __init__(self, path, fps, n, w, h, fallback, cls=""):
        self.path = safe_path(path); self.fps = float(fps); self.n = n; self.w = w; self.h = h; self.fallback = fallback; self.cls = cls or "%dx%d" % (w, h)
        self.proc = None; self.ppos = -10; self.pos = -10; self.raw = None; self.backend = None; self.dead = False; self.bad = 0; self.run = 0
        self.pend = None; self.last_use = time.monotonic()
    # ---- processes
    def _spawn(self, idx, backend):
        t = max(0.0, (idx - 0.5) / self.fps)          # half a frame early: the first frame given is exactly idx
        c = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if backend and backend != "cpu": c += ["-hwaccel", backend]
        if t > 0: c += ["-ss", "%.6f" % t]
        c += ["-i", self.path, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", "scale=%d:%d" % (self.w, self.h), "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        return subprocess.Popen(c, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=NOWIN, bufsize=0)
    @staticmethod
    def _kill(proc):
        if proc is None: return
        try: proc.kill()
        except Exception: pass
        try: proc.stdout.close()
        except Exception: pass
        try: proc.wait(timeout=2)
        except Exception: pass
    def _get(self, proc):
        buf = np.empty((self.h, self.w, 3), np.uint8); mv = memoryview(buf).cast("B"); got = 0; size = buf.size
        try:
            while got < size:
                k = proc.stdout.readinto(mv[got:])
                if not k: return None
                got += k
        except Exception:
            return None
        return buf
    def _register(self, proc):
        with _FF_LOCK:
            self.proc = proc; self.last_use = time.monotonic(); _FF_LIVE[id(self)] = self
            while len(_FF_LIVE) > _FF_MAX_LIVE:                       # too many ffmpeg running: stop the least used
                _, o = _FF_LIVE.popitem(last=False)
                if o is not self: p, o.proc = o.proc, None; self._kill(p)
        if _FF_REAPER[0] is None:
            _FF_REAPER[0] = threading.Thread(target=_ff_reap, name="MiniCutFFReap", daemon=True); _FF_REAPER[0].start()
    def _stop(self):
        with _FF_LOCK:
            p, self.proc = self.proc, None; _FF_LIVE.pop(id(self), None)
        self._kill(p)
    # ---- what is known about this kind of video
    def _entry(self):
        ent = _hw_db().setdefault(self.cls, {"ok": "", "bad": [], "t": time.time()})
        if time.time() - ent.get("t", 0) > _BAD_MAX_AGE: ent.update({"ok": "", "bad": [], "t": time.time()})       # drivers and FFmpeg change: ask again
        return ent
    def _pick_backend(self):
        ent = self._entry(); cands = ([ent["ok"]] if ent.get("ok") else []) + [b for b in _hw_candidates() if b != ent.get("ok")]
        for b in cands:
            if b and b not in ent["bad"] and _BAD_HW.get(b, 0) < 3: return b
        return None
    def _mark_bad(self, b):
        ent = self._entry(); _BAD_HW[b] = _BAD_HW.get(b, 0) + 1
        if b not in ent["bad"]: ent["bad"].append(b)
        if ent.get("ok") == b: ent["ok"] = ""
        ent["t"] = time.time(); _hw_save()
    def _mark_ok(self, b):
        ent = self._entry()
        if ent.get("ok") != b: ent["ok"] = b; ent["t"] = time.time(); _hw_save()
    # ---- starting the pipe in the background
    def _want_pipe(self, idx):
        if self.pend is not None or self.proc is not None or self.dead: return
        with _FF_LOCK:
            if _FF_PENDING[0] >= 2: return
            _FF_PENDING[0] += 1
        target = idx + max(8, int(self.fps * 0.5))
        if self.n > 0: target = min(target, self.n - 1)
        pend = {"idx": target, "b": None, "done": False, "proc": None, "first": None, "none": False}; self.pend = pend
        def work():
            proc = first = None
            try:
                b = self._pick_backend(); pend["b"] = b
                if b is None: pend["none"] = True
                else: proc = self._spawn(target, b); first = self._get(proc)
            except Exception: first = None
            if pend.get("cancel"): self._kill(proc); proc = None
            pend["proc"] = proc; pend["first"] = first; pend["done"] = True
            with _FF_LOCK: _FF_PENDING[0] = max(0, _FF_PENDING[0] - 1)
        threading.Thread(target=work, name="MiniCutFFStart", daemon=True).start()
    def _drop_pend(self):
        p, self.pend = self.pend, None
        if p is None: return
        p["cancel"] = True
        if p["done"]: self._kill(p["proc"])
    def _takeover(self, idx):
        """The picture at idx from the pipe that was started in the background, or None while it is not ready."""
        p = self.pend
        if p is None or not p["done"] or idx < p["idx"]: return None
        self.pend = None; proc, first = p["proc"], p["first"]
        if p["none"]: self.dead = True; return None                            # no GPU decoder is left to try: OpenCV from now on
        if first is None: self._kill(proc); self._mark_bad(p["b"]); return None
        if idx - p["idx"] > 30: self._kill(proc); return None                  # it came too late: try again from here
        img = first
        for _ in range(idx - p["idx"]):
            img = self._get(proc)
            if img is None: break
        ref = self.fallback.read(idx)
        if img is None or ref is None or float(cv2.absdiff(img, ref).mean()) >= 6.0:
            self._kill(proc); self._mark_bad(p["b"]); return None            # wrong picture (or no picture): not this backend for this kind of video
        self._register(proc); self.backend = p["b"]; self.ppos = idx; self._mark_ok(p["b"]); return img
    def _from_pipe(self, idx):
        proc = self.proc; gap = idx - self.ppos
        if proc is None or proc.poll() is not None or gap < 1 or gap > 8: self._stop(); return None
        for _ in range(gap - 1):
            if self._get(proc) is None: self._stop(); self.bad += 1; return None
        img = self._get(proc)
        if img is None:
            self._stop(); self.bad += 1
            if self.bad >= 2: self.dead = True
            return None
        self.ppos = idx; self.last_use = time.monotonic()
        with _FF_LOCK:
            if id(self) in _FF_LIVE: _FF_LIVE.move_to_end(id(self))
        return img
    def read(self, idx):
        if self.dead: return self.fallback.read(idx)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        if idx == self.pos and self.raw is not None: return self.raw
        seq = self.pos >= 0 and 1 <= idx - self.pos <= 4
        if seq: self.run += 1
        else: self.run = 0; self._stop(); self._drop_pend()                    # a jump: no pipe, OpenCV seeks at once
        img = None
        try:
            if seq:
                if self.proc is not None: img = self._from_pipe(idx)
                elif self.pend is not None: img = self._takeover(idx)
            if img is None:
                img = self.fallback.read(idx)
                if seq and self.run >= _RUN_MIN and self.proc is None and self.pend is None and not self.dead: self._want_pipe(idx)
        except Exception:
            self.bad += 1; self._stop(); self._drop_pend(); img = self.fallback.read(idx)
            if self.bad >= 3: self.dead = True
        if img is not None: self.raw = img; self.pos = idx
        return img if img is not None else self.raw
    def release(self):
        self._stop(); self._drop_pend()
        try: self.fallback.release()
        except Exception: pass


def _ff_on():
    """The FFmpeg pipe is used only when GPU decoding is switched on: with the CPU alone the OpenCV reader is faster."""
    return bool(CFG.get("hw_decode")) and not os.environ.get("MINICUT_CV2_DECODE") and bool(CFG.get("ff_decode", True))


def _make_reader(path, probe, fps, n, w, h):
    if not _ff_on() or w <= 0 or h <= 0 or not fps or fps != fps:
        return _Reader(probe)
    try:
        fc = int(probe.get(cv2.CAP_PROP_FOURCC)); cc = "".join(chr((fc >> (8 * i)) & 255) for i in range(4)) if fc else "?"
    except Exception: cc = "?"
    return _FFReader(path, fps, n, w, h, _Reader(probe), "%s|%dx%d" % (cc, w, h))


class _Ahead:
    """Decode-ahead wrapper (Patch 38). While the playhead moves forward frame by frame, a helper thread decodes (and, when a
    target size is known, shrinks) the next frames, so the render thread never waits for the decoder. A jump (click, scrub)
    stops the helper and the inner reader seeks at once, as before. Same interface as _Reader: read(idx) / release()."""
    DEPTH = 3
    def __init__(self, inner, n):
        self.inner = inner; self.n = n; self.pos = -10; self.raw = None
        self.cv = threading.Condition(); self.q = collections.deque(); self.th = None; self.stop = False; self.next = 0
        self.hint = None; self.small = {}; self.err = 0
    def _run(self, start, gen):
        i = start
        while True:
            with self.cv:
                while not self.stop and gen == self.gen and len(self.q) >= self.DEPTH: self.cv.wait(0.2)
                if self.stop or gen != self.gen: return
                hint = self.hint
            if self.n > 0 and i >= self.n: return
            try:
                f = self.inner.read(i)
                sm = None
                if f is not None and hint and (f.shape[1], f.shape[0]) != hint:
                    sm = cv2.resize(f, hint, interpolation=cv2.INTER_AREA if hint[0] < f.shape[1] else cv2.INTER_LINEAR)
            except Exception:
                f = None; sm = None
            with self.cv:
                if self.stop or gen != self.gen: return
                if f is None: self.err += 1; self.q.append((i, None, None)); self.cv.notify_all(); return
                self.q.append((i, f, sm)); self.cv.notify_all()
            i += 1
    def _halt(self):
        with self.cv:
            self.stop = True; self.gen += 1; self.cv.notify_all(); th = self.th
        if th is not None and th is not threading.current_thread(): th.join(3.0)
        self.th = None; self.q.clear(); self.small.clear(); self.stop = False
    gen = 0
    def _go(self, start):
        self.q.clear(); self.gen += 1; g = self.gen
        self.th = threading.Thread(target=self._run, args=(start, g), name="MiniCutDecodeAhead", daemon=True); self.th.start()
    def want(self, tw, th):
        self.hint = (tw, th)
    def read(self, idx):
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        if idx == self.pos and self.raw is not None: return self.raw
        gap = idx - self.pos
        if self.err >= 3 or not (self.pos >= 0 and 1 <= gap <= 4):
            self._halt()
            f = self.inner.read(idx)
            if f is not None: self.raw = f; self.pos = idx
            self.small.clear()
            return f if f is not None else self.raw
        if self.th is None or not self.th.is_alive():
            if self.th is not None and not self.q: self._halt()
            if self.th is None: self._go(self.pos + 1)
        t_end = time.monotonic() + 3.0
        with self.cv:
            while True:
                while self.q and self.q[0][0] < idx: self.q.popleft(); self.cv.notify_all()
                if self.q and self.q[0][0] == idx:
                    _, f, sm = self.q.popleft(); self.cv.notify_all(); break
                if self.q and self.q[0][0] > idx: f = None; sm = None; break
                if (self.th is None or not self.th.is_alive()) or time.monotonic() > t_end: f = None; sm = None; break
                self.cv.wait(0.05)
        if f is None:
            self._halt(); f = self.inner.read(idx)
            if f is None: return self.raw
            sm = None
        self.raw = f; self.pos = idx; self.small = {idx: sm} if sm is not None else {}
        return f
    def small_for(self, idx, tw, th):
        sm = self.small.get(idx)
        return sm if sm is not None and sm.shape[1] == tw and sm.shape[0] == th else None
    def release(self):
        self._halt()
        try: self.inner.release()
        except Exception: pass


class VideoSource:
    """Frames of a video. A finished proxy piece covering the time is used when there is one; otherwise the original
    file. Size, fps and length always come from the original file."""
    KEEP_PIECES = 3
    def __init__(self, path, use_proxy=False):
        probe = cv2.VideoCapture(safe_path(path)) if _ff_on() else open_capture(safe_path(path))      # Patch 45: FFmpeg checks GPU decoding itself
        if not probe.isOpened(): raise IOError("cannot open " + path)
        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.orig = _make_reader(path, probe, self.fps, self.n, self.w, self.h)
        if not os.environ.get("MINICUT_NO_AHEAD"): self.orig = _Ahead(self.orig, self.n)
        self.dir = proxy_dir(path) if use_proxy else None
        if self.dir:
            try: os.utime(self.dir)                      # used now: keep it longest in the disk budget
            except OSError: pass
        self.index = []; self._starts = []; self._index_mt = None
        self.pieces = OrderedDict(); self.cache = OrderedDict(); self.rawc = OrderedDict()
        self.path = path; self._warm = None; self._spare = None; self._warm_busy = False; self._wlock = threading.Lock()      # Patch 54: see prewarm()
    def _refresh_index(self):
        if self.dir is None: return
        try: mt = os.path.getmtime(os.path.join(self.dir, "index.csv"))
        except OSError: return
        if mt != self._index_mt:
            self._index_mt = mt; self.index = proxy_index(self.dir); self._starts = [s for _, s, _ in self.index]
    def _piece_for(self, t):
        """(piece file name, time inside the piece) of the finished piece that covers t, or None."""
        self._refresh_index()
        if not self._starts: return None
        i = bisect.bisect_right(self._starts, t) - 1
        if i < 0: return None
        name, s, e = self.index[i]
        if t >= e: return None
        return name, t - s
    def _piece(self, name):
        if name in self.pieces:
            if os.path.exists(os.path.join(self.dir, name)): self.pieces.move_to_end(name); return self.pieces[name]
            self.pieces.pop(name).release(); self.cache.clear(); self.rawc.clear(); return None      # deleted: never show it again
        f = os.path.join(self.dir, name)
        if not os.path.exists(f): return None
        cap = cv2.VideoCapture(safe_path(f))
        if not cap.isOpened(): return None
        self.pieces[name] = _Reader(cap)
        while len(self.pieces) > self.KEEP_PIECES: self.pieces.popitem(last=False)[1].release()
        return self.pieces[name]
    def prewarm(self, idx):
        """Patch 54: the playhead is about to enter a clip of this file at frame idx, which is NOT the frame after the one shown now (a cut that
        was moved). A jump inside the file costs a seek to the keyframe plus decoding up to a whole GOP: that was the short freeze at every
        join. So a second reader is moved there beforehand in a helper thread; raw_frame() swaps it in when the frame is asked for."""
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        pos = getattr(self.orig, "pos", -10)
        if pos >= 0 and 0 <= idx - pos <= 8: return                       # the reader in use gets there by reading on: nothing to prepare
        with self._wlock:
            w = self._warm
            if self._warm_busy or (w is not None and abs(w["idx"] - idx) <= 1): return
            rd = None
            if w is not None and w.get("r") is not None: rd = w["r"]       # an earlier guess that was not used: move that reader instead
            if rd is None: rd, self._spare = self._spare, None
            self._warm = w = {"idx": idx, "r": None, "ok": False}; self._warm_busy = True
        def work():
            r = rd; ok = False
            try:
                if r is None:
                    probe = cv2.VideoCapture(safe_path(self.path)) if _ff_on() else open_capture(safe_path(self.path))
                    if not probe.isOpened(): raise IOError("cannot open")
                    r = _make_reader(self.path, probe, self.fps, self.n, self.w, self.h)
                    if not os.environ.get("MINICUT_NO_AHEAD"): r = _Ahead(r, self.n)
                ok = r.read(idx) is not None                                # the slow part: seek + decode the first frame
            except Exception: ok = False
            with self._wlock: w["r"] = r; w["ok"] = ok; self._warm_busy = False
        threading.Thread(target=work, name="MiniCutPreRoll", daemon=True).start()
    def _swap_warm(self, idx):
        w = self._warm
        if w is None or not w["ok"] or w["r"] is None: return
        pos = getattr(self.orig, "pos", -10)
        if idx == pos or (pos >= 0 and 1 <= idx - pos <= 4): return       # the reader in use serves it without a jump
        r = w["r"]; rp = getattr(r, "pos", -10)
        if not (rp >= 0 and 0 <= idx - rp <= 4): return                    # the playhead did not go where it was expected
        with self._wlock:
            old, self.orig = self.orig, r; self._warm = None
            if self._spare is None: self._spare = old; old = None
        if old is not None:
            try: old.release()
            except Exception: pass
    def raw_frame(self, t):
        """The decoded picture exactly as it is (BGR, no resize, no copy). The last few are kept, so asking again is free."""
        t = max(0.0, t); idx = int(t * self.fps + 1e-6)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        pm = self._piece_for(t) if self.dir is not None else None
        key = (idx, pm[0] if pm else None)
        hit = self.rawc.get(key)
        if hit is not None: self.rawc.move_to_end(key); return hit
        raw = None
        if pm:
            rd = self._piece(pm[0])
            if rd is not None: raw = rd.read(int(pm[1] * self.fps + 1e-6))
        if raw is None:
            if self._warm is not None: self._swap_warm(idx)                      # Patch 54
            raw = self.orig.read(idx)
        if raw is None: raw = np.zeros((max(1, self.h), max(1, self.w), 3), np.uint8)
        self.rawc[key] = raw
        while len(self.rawc) > 4: self.rawc.popitem(last=False)  # keep more decoded frames to reduce re-decodes on scrub
        return raw
    def frame(self, t, ds=1.0):
        t = max(0.0, t); idx = int(t * self.fps + 1e-6)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        pm = self._piece_for(t) if self.dir is not None else None
        key = (idx, ds, pm[0] if pm else None)
        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
        raw = self.raw_frame(t)
        tw, th = max(1, int(self.w * ds)), max(1, int(self.h * ds))
        if raw.shape[1] != tw or raw.shape[0] != th:
            raw = cv2.resize(raw, (tw, th), interpolation=cv2.INTER_AREA if tw < raw.shape[1] else cv2.INTER_LINEAR)
        img = cv2.cvtColor(raw, cv2.COLOR_BGR2BGRA)
        self.cache[key] = img
        while len(self.cache) > CFG["frame_cache"]: self.cache.popitem(last=False)
        return img
    def frame_bgr(self, t, ds=1.0):
        """Like frame() but 3-channel BGR (no alpha plane): what the effects use for video (Patch 34)."""
        t = max(0.0, t); idx = int(t * self.fps + 1e-6)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        pm = self._piece_for(t) if self.dir is not None else None
        key = ("bgr", idx, ds, pm[0] if pm else None)
        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
        tw, th = max(1, int(self.w * ds)), max(1, int(self.h * ds))
        if hasattr(self.orig, "want"): self.orig.want(tw, th)
        raw = self.raw_frame(t)
        sm = self.orig.small_for(idx, tw, th) if (pm is None and hasattr(self.orig, "small_for")) else None
        if sm is not None: raw = sm
        elif raw.shape[1] != tw or raw.shape[0] != th:
            raw = cv2.resize(raw, (tw, th), interpolation=cv2.INTER_AREA if tw < raw.shape[1] else cv2.INTER_LINEAR)
        self.cache[key] = raw
        while len(self.cache) > CFG["frame_cache"]: self.cache.popitem(last=False)
        return raw
    def close(self):
        for r in self.pieces.values(): r.release()
        with self._wlock:
            extra = [x for x in ((self._warm or {}).get("r"), self._spare) if x is not None]; self._warm = None; self._spare = None
        for r in extra:
            try: r.release()
            except Exception: pass
        self.pieces.clear(); self.orig.release(); self.cache.clear(); self.rawc.clear()


class ImageSource:
    def __init__(self, path):
        self.img = to_bgra(imread_any(path))
        if self.img is None: raise IOError("cannot open " + path)
        self.h, self.w = self.img.shape[:2]; self.cache = {}; self.bgr_cache = {}
        self.opaque = bool(cv2.extractChannel(self.img, 3).min() == 255)      # no transparency: can be drawn without alpha
    def frame_bgr(self, ds=1.0):
        if ds not in self.bgr_cache:
            self.bgr_cache[ds] = cv2.cvtColor(self.frame(0, ds), cv2.COLOR_BGRA2BGR)
            while len(self.bgr_cache) > 8: self.bgr_cache.pop(next(iter(self.bgr_cache)))
        return self.bgr_cache[ds]
    def frame(self, t, ds=1.0):
        if ds >= 0.999: return self.img
        if ds not in self.cache:
            self.cache[ds] = cv2.resize(self.img, (max(1, int(self.w * ds)), max(1, int(self.h * ds))), interpolation=cv2.INTER_AREA)
        return self.cache[ds]


class GifSource:
    def __init__(self, path):
        im = Image.open(path); self.frames = []; durs = []
        for f in ImageSequence.Iterator(im):
            self.frames.append(cv2.cvtColor(np.array(f.convert("RGBA")), cv2.COLOR_RGBA2BGRA))
            durs.append(max(20, f.info.get("duration", 100) or 100) / 1000)
        self.ends = np.cumsum(durs); self.dur = float(self.ends[-1])
        self.h, self.w = self.frames[0].shape[:2]; self.cache = OrderedDict()
    def frame(self, t, ds=1.0):
        i = min(int(np.searchsorted(self.ends, t % self.dur, side="right")), len(self.frames) - 1)
        if ds >= 0.999: return self.frames[i]
        key = (i, ds)
        if key not in self.cache:
            self.cache[key] = cv2.resize(self.frames[i], (max(1, int(self.w * ds)), max(1, int(self.h * ds))), interpolation=cv2.INTER_AREA)
            while len(self.cache) > 120: self.cache.popitem(last=False)
        return self.cache[key]


def proxy_sources(clips, off=0.0, out=None):
    """(clip, timeline offset) for every clip, including the clips inside compound clips (at any depth).
    The offset turns a clip's own start into a time on the project timeline: global start = c['start'] + offset."""
    if out is None: out = []
    for c in clips:
        if c.get("kind") == "compound":
            proxy_sources(c.get("children", []), off + c["start"] - c.get("inp", 0.0), out)
        else:
            out.append((c, off))
    return out


class MediaPool:
    def __init__(self, use_proxy=False): self.src = {}; self.make_compound = None; self.use_proxy = use_proxy; self._proxy_jobs = set()
    MAX_OPEN = 16          # open video files at most (the oldest one is closed first): keeps a long project light
    def _evict(self):
        while len(self.src) >= self.MAX_OPEN:
            s = self.src.pop(next(iter(self.src)))
            try:
                if hasattr(s, "close"): s.close()
            except Exception: pass
    def _video(self, p):
        self._evict()
        if not self.use_proxy: return VideoSource(p)
        PROXY.pool = self; PROXY.want(p)
        return VideoSource(p, use_proxy=True)
    def prepare(self, clips, t=0.0):
        """Queue the proxies of every video in the project (also inside compound clips); the ones nearest the playhead first."""
        if not self.use_proxy: return
        best = {}
        for c, off in proxy_sources(clips):
            if c.get("kind") == "video" and c.get("path"):
                s = c["start"] + off; e = s + c["dur"]
                d = 0.0 if s <= t <= e else min(abs(s - t), abs(e - t))
                best[c["path"]] = min(best.get(c["path"], 1e18), d)
        for p, d in best.items(): PROXY.want(p, d)
    def reset(self):
        """Cancel the proxy jobs, close every open file and forget the sources (call with the render lock held)."""
        PROXY.reset()
        for s in self.src.values():
            try: s.close()
            except Exception: pass
        self.src.clear()
    def get(self, c):
        if c.get("kind") == "compound": return self.make_compound(c) if self.make_compound else None
        p = c["path"]
        if c.get("effects"):
            from .smartkey import sk_path
            p = sk_path(c) or p                                                    # Better Chroma Key: the rendered media is used while it is valid, else the original
        if p not in self.src:
            with self.__dict__.setdefault("_open_lock", threading.RLock()):         # Patch 54: a file may be opened by the pre-roll thread too
                if p not in self.src:
                    try:
                        k = c["kind"]
                        if k == "video" and p != c["path"]:
                            from .smartkey import PackedAlphaSource
                            self.src[p] = PackedAlphaSource(p)
                        else: self.src[p] = self._video(p) if k == "video" else GifSource(p) if k == "gif" else ImageSource(p) if k == "image" else None
                    except Exception as ex:
                        print("media error:", ex); self.src[p] = None
        return self.src[p]


class AudioStore:
    """Decoded audio of every file. The decoded sound is kept in a file on disk and read through a memory map, so an hour
    of audio does not take RAM, and the next start does not decode it again."""
    def __init__(self): self.data = {}; self.peaks = {}; self.files = {}; self.lock = threading.Lock(); self._locks = {}
    @staticmethod
    def _cache_file(path):
        import hashlib
        st = os.stat(path)
        key = hashlib.sha1(("%s|%d|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime), SR)).encode("utf-8")).hexdigest()[:24]
        d = os.path.join(APP_DIR, "audiocache"); os.makedirs(d, exist_ok=True)
        return os.path.join(d, key + ".pcm")
    def _cleanup(self, keep):
        """Keep the audio cache under its budget (Settings): the least recently used files go first, files in use stay."""
        d = os.path.join(APP_DIR, "audiocache"); budget = float(CFG.get("audio_cache_gb", 8)) * 1e9
        try: items = [(os.path.getmtime(os.path.join(d, f)), os.path.getsize(os.path.join(d, f)), os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".pcm")]
        except OSError: return
        total = sum(s for _, s, _ in items); inuse = set(list(self.files.values())) | {keep}
        for _, size, p in sorted(items):
            if total <= budget: break
            if p in inuse: continue
            try: os.remove(p); total -= size
            except OSError: pass
    def _plock(self, path):
        with self.lock: return self._locks.setdefault(path, threading.Lock())
    def load(self, path):
        if path in self.data: return self.data[path]      # already decoded: never wait for other files that are being decoded
        with self._plock(path):                            # one lock per file (it used to be one lock for all files)
            if path in self.data: return self.data[path]
            arr = None
            try:
                f = self._cache_file(path)
                if not (os.path.exists(f) and os.path.getsize(f) >= 4):
                    tmp = f + ".part"
                    with open(tmp, "wb") as out:
                        r = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"],
                                           stdout=out, stderr=subprocess.DEVNULL, creationflags=NOWIN | (0x4000 if os.name == "nt" else 0))      # below normal priority: the window stays smooth
                    if r.returncode == 0 and os.path.getsize(tmp) >= 4: os.replace(tmp, f)
                    else:
                        try: os.remove(tmp)
                        except OSError: pass
                if os.path.exists(f) and os.path.getsize(f) >= 4:
                    arr = np.memmap(f, dtype=np.int16, mode="r", shape=(os.path.getsize(f) // 4, 2))
                    try: os.utime(f)
                    except OSError: pass
                    self.files[path] = f; self._cleanup(f)
            except Exception as ex: print("audio load:", ex)
            self.data[path] = arr
            if arr is not None:
                hop = SR // 100; n = len(arr) // hop; pk = np.empty(n, np.float32)
                for s in range(0, n, 6000):                 # one minute at a time: no big temporary arrays
                    # Patch 53: the old line took the max over the 2 channels (an axis of length 2: millions of tiny reductions) after copying everything
                    # to int32. Now: one max and one min over long contiguous rows, on the int16 data as it is (same numbers, many times faster).
                    e = min(n, s + 6000); blk = np.asarray(arr[s * hop:e * hop]).reshape(e - s, hop * 2)
                    pk[s:e] = np.maximum(blk.max(axis=1).astype(np.int32), -blk.min(axis=1).astype(np.int32)) / 32768.0; _wait_idle(); time.sleep(0.002)      # lets the window draw in between
                self.peaks[path] = pk
            else: self.peaks[path] = np.zeros(0, np.float32)
            return arr


AUDIO = AudioStore()


_THUMB_CAPS = OrderedDict(); _THUMB_LOCK = threading.Lock()


def make_thumb(path, kind, t, h):
    img = None
    if kind == "video":
        with _THUMB_LOCK:                        # Patch 38: the file stays open between thumbnails (opening a long file costs more than the seek)
            cap = _THUMB_CAPS.pop(path, None)
            if cap is None: cap = cv2.VideoCapture(safe_path(path))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, img = cap.read()
            if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, img = cap.read()
            _THUMB_CAPS[path] = cap
            while len(_THUMB_CAPS) > 2:
                try: _THUMB_CAPS.popitem(last=False)[1].release()
                except Exception: pass
        if not ok: return None
    elif kind == "image":
        img = to_bgra(imread_any(path))
        if img is None:                                  # Patch 48: OpenCV could not read it (an unusual PNG ...): try Pillow
            try: im = Image.open(path); im.load(); img = cv2.cvtColor(np.array(im.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
            except Exception: img = None
    elif kind == "gif":
        im = Image.open(path); im.seek(0); img = cv2.cvtColor(np.array(im.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
    if img is None: return None
    ih, iw = img.shape[:2]
    img = cv2.resize(img, (max(1, int(iw * h / ih)), h), interpolation=cv2.INTER_AREA)
    return np_to_qimage(img)


def _wait_idle(limit=60.0):
    """Background decoration (thumbnails, waveforms) does not compete with playback for the CPU / the interpreter lock."""
    t0 = time.monotonic()
    while PLAYING[0] and time.monotonic() - t0 < limit: time.sleep(0.1)


class _Job(QRunnable):
    def __init__(self, fn, cb): super().__init__(); self.fn = fn; self.cb = cb
    def run(self):
        _wait_idle()
        try: r = self.fn()
        except Exception: r = None
        try: self.cb(r)
        except RuntimeError: pass          # Qt objects already deleted at shutdown


class ThumbStore(QObject):
    updated = Signal()
    def __init__(self):
        super().__init__(); self.cache = OrderedDict(); self.pending = set(); self._fail = {}
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)
        # Timeline thumbnails are background decoration: keep their CPU contention low so
        # preview decoding/compositing and the GUI have room to run during auto-scroll.
        try: self.pool.setThreadPriority(QThread.LowPriority)
        except Exception: pass
        self.apool = QThreadPool(); self.apool.setMaxThreadCount(1)      # sound of the cards: one at a time, thumbnails are not held up
        try: self.apool.setThreadPriority(QThread.LowPriority)           # Patch 53: reading the waveforms must not take the CPU from the preview
        except Exception: pass
        self.ppool = QThreadPool(); self.ppool.setMaxThreadCount(1)      # sound of the file that is being previewed
    def _run(self, key, fn, pool=None, prio=0):
        self.pending.add(key)
        def cb(r, key=key):
            self.pending.discard(key)
            if r is None and isinstance(key, tuple) and key and key[0] == "t":
                # Patch 48: a thumbnail that failed is tried again (after 4 s, three times) instead of being given up for good
                n = self._fail.get(key, (0, 0.0))[0] + 1; self._fail[key] = (n, time.monotonic())
                if n >= 3: self.cache[key] = None
            else: self.cache[key] = r
            while len(self.cache) > 1500: self.cache.popitem(last=False)
            try: self.updated.emit()
            except RuntimeError: pass          # the window was closed while the job was running
        (pool or self.pool).start(_Job(fn, cb), prio)
    def thumb(self, path, kind, t, h, urgent=False):
        key = ("t", path, round(t, 1), h)
        f = self._fail.get(key)
        if f is not None and key not in self.cache and time.monotonic() - f[1] < 4.0: return None
        if key in self.cache:
            try: self.cache.move_to_end(key)
            except Exception: pass
            return self.cache[key]
        if key not in self.pending:
            # Scrolling can expose hundreds of new thumbnail timestamps quickly. Bound the queued
            # work so stale thumbnails cannot build an unbounded backlog ahead of playback.
            queued = sum(1 for k in self.pending if isinstance(k, tuple) and k and k[0] == "t")
            if queued >= 8 and not urgent:       # the cards of the media pool are never held back (and go first)
                try:
                    from .debug_trace import trace_event
                    now = time.monotonic()
                    last = getattr(self, "_thumb_skip_log", 0.0)
                    if now - last >= 1.0:
                        self._thumb_skip_log = now
                        trace_event("thumbnail_queue_throttled", pending=queued, limit=8)
                except Exception: pass
                return None
            self._run(key, lambda: make_thumb(path, kind, t, h), None, 10 if urgent else 0)
        return None
    def wave(self, path):
        if path in AUDIO.peaks: return AUDIO.peaks[path]
        key = ("w", path)
        if key not in self.pending and key not in self.cache: self._run(key, lambda: (AUDIO.load(path), None)[1], self.apool)
        return None
    def wave_now(self, path):
        """Decode the sound of the previewed file now (its own thread, not behind the cards' waveforms)."""
        key = ("wn", path)
        if path not in AUDIO.data and key not in self.pending: self._run(key, lambda: (AUDIO.load(path), None)[1], self.ppool)


# MINI CUT PATCH 36 RENDER DIAGNOSTICS
try:
    from .debug_trace import trace_timing
    _mc36_orig_raw_frame = VideoSource.raw_frame
    def _mc36_raw_frame(self, t):
        _mc36_t0 = time.perf_counter()
        _mc36_idx = int(max(0.0, float(t)) * max(1.0, float(getattr(self, "fps", 30))))
        _mc36_hit = False
        try:
            _mc36_cache = getattr(self, "rawc", {})
            _mc36_hit = any(isinstance(_mc36_k, tuple) and _mc36_k and _mc36_k[0] == _mc36_idx for _mc36_k in _mc36_cache)
        except Exception: pass
        try:
            return _mc36_orig_raw_frame(self, t)
        finally:
            trace_timing("video_raw_frame", (time.perf_counter() - _mc36_t0) * 1000.0,
                         cache_hit=_mc36_hit, frame=_mc36_idx, fps=round(float(getattr(self, "fps", 0) or 0), 3),
                         size="%sx%s" % (getattr(self, "w", 0), getattr(self, "h", 0)))
    VideoSource.raw_frame = _mc36_raw_frame
except Exception as _mc36_media_hook_error:
    try: trace_timing("media_instrumentation_error", 0, error=repr(_mc36_media_hook_error))
    except Exception: pass
# END MINI CUT PATCH 36 RENDER DIAGNOSTICS


# PATCH 37: identify slow timeline thumbnail decoding without logging every fast call.
try:
    from .debug_trace import trace_timing
    _mc37_make_thumb_original = make_thumb
    def make_thumb(path, kind, t, h):
        _t0 = time.perf_counter()
        try:
            return _mc37_make_thumb_original(path, kind, t, h)
        finally:
            trace_timing("timeline_thumbnail", (time.perf_counter() - _t0) * 1000.0,
                         kind=kind, t=round(float(t), 3), height=int(h),
                         path=os.path.basename(str(path)))
except Exception:
    pass


# PATCH 37: log the decoder request and what OpenCV reports for each opened source.
try:
    from .debug_trace import trace_event
    _mc37_open_capture_original = open_capture
    def open_capture(path):
        requested_hw = bool(CFG.get("hw_decode"))
        cap = _mc37_open_capture_original(path)
        try:
            hw_prop = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)
            backend_prop = getattr(cv2, "CAP_PROP_BACKEND", None)
            reported_hw = cap.get(hw_prop) if hw_prop is not None and cap.isOpened() else None
            backend_id = cap.get(backend_prop) if backend_prop is not None and cap.isOpened() else None
            backend_name = None
            try:
                if backend_id is not None and hasattr(cv2, "VideoCaptureAPIs"):
                    backend_name = cv2.videoio_registry.getBackendName(int(backend_id))
            except Exception: pass
            trace_event("video_decoder_open", path=os.path.basename(str(path)),
                        requested_hw_decode=requested_hw, opened=bool(cap.isOpened()),
                        reported_hw_acceleration=reported_hw, backend_id=backend_id,
                        backend_name=backend_name,
                        note="OpenCV-reported properties; not a GPU-utilization measurement")
        except Exception: pass
        return cap
except Exception:
    pass

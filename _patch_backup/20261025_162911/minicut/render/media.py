"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""
from ..shared.deps import *
from ..shared.core import *


def open_capture(path):
    """Open a video file. With "hw_decode" on (Settings) FFmpeg is asked to decode on the GPU; if that is not
    supported on this PC, fall back to the normal CPU decoder."""
    # GPU decoding is switched off for every read. With some drivers the GPU decoder returns frames with a pink /
    # magenta band at the top, which showed up in the viewport. The CPU decoder is used whatever the setting says.
    return cv2.VideoCapture(path)


import threading
PROXY_HEIGHT = 540
PROXY_CHUNK = 2.0                 # seconds per proxy piece (pieces are finished one by one, in order)
PROXY_JOB_TIMEOUT = 180           # seconds one ffmpeg call may take before the job is given up
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


def _piece_path(d, k): return os.path.join(d, "p%05d.mp4" % k)


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


class VideoSource:
    """Frames of a video. A finished proxy piece covering the time is used when there is one; otherwise the original
    file. Size, fps and length always come from the original file."""
    KEEP_PIECES = 3
    def __init__(self, path, use_proxy=False):
        probe = open_capture(safe_path(path))
        if not probe.isOpened(): raise IOError("cannot open " + path)
        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.orig = _Reader(probe)
        self.dir = proxy_dir(path) if use_proxy else None
        if self.dir:
            try: os.utime(self.dir)                      # used now: keep it longest in the disk budget
            except OSError: pass
        self.index = []; self._starts = []; self._index_mt = None
        self.pieces = OrderedDict(); self.cache = OrderedDict(); self.rawc = OrderedDict()
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
        if raw is None: raw = self.orig.read(idx)
        if raw is None: raw = np.zeros((max(1, self.h), max(1, self.w), 3), np.uint8)
        self.rawc[key] = raw
        while len(self.rawc) > 4: self.rawc.popitem(last=False)
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
    def close(self):
        for r in self.pieces.values(): r.release()
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
        if p not in self.src:
            try:
                k = c["kind"]
                self.src[p] = self._video(p) if k == "video" else GifSource(p) if k == "gif" else ImageSource(p) if k == "image" else None
            except Exception as ex:
                print("media error:", ex); self.src[p] = None
        return self.src[p]


class AudioStore:
    """Decoded audio of every file. The decoded sound is kept in a file on disk and read through a memory map, so an hour
    of audio does not take RAM, and the next start does not decode it again."""
    def __init__(self): self.data = {}; self.peaks = {}; self.files = {}; self.lock = threading.Lock()
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
        total = sum(s for _, s, _ in items); inuse = set(self.files.values()) | {keep}
        for _, size, p in sorted(items):
            if total <= budget: break
            if p in inuse: continue
            try: os.remove(p); total -= size
            except OSError: pass
    def load(self, path):
        with self.lock:
            if path in self.data: return self.data[path]
            arr = None
            try:
                f = self._cache_file(path)
                if not (os.path.exists(f) and os.path.getsize(f) >= 4):
                    tmp = f + ".part"
                    with open(tmp, "wb") as out:
                        r = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"],
                                           stdout=out, stderr=subprocess.DEVNULL, creationflags=NOWIN)
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
                    e = min(n, s + 6000); blk = np.asarray(arr[s * hop:e * hop]).astype(np.int32)
                    pk[s:e] = np.abs(blk).max(axis=1).reshape(e - s, hop).max(axis=1) / 32768.0
                self.peaks[path] = pk
            else: self.peaks[path] = np.zeros(0, np.float32)
            return arr


AUDIO = AudioStore()


def make_thumb(path, kind, t, h):
    img = None
    if kind == "video":
        cap = cv2.VideoCapture(safe_path(path)); cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, img = cap.read()
        if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, img = cap.read()
        cap.release()
        if not ok: return None
    elif kind == "image": img = to_bgra(imread_any(path))
    elif kind == "gif":
        im = Image.open(path); im.seek(0); img = cv2.cvtColor(np.array(im.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
    if img is None: return None
    ih, iw = img.shape[:2]
    img = cv2.resize(img, (max(1, int(iw * h / ih)), h), interpolation=cv2.INTER_AREA)
    return np_to_qimage(img)


class _Job(QRunnable):
    def __init__(self, fn, cb): super().__init__(); self.fn = fn; self.cb = cb
    def run(self):
        try: r = self.fn()
        except Exception: r = None
        self.cb(r)


class ThumbStore(QObject):
    updated = Signal()
    def __init__(self):
        super().__init__(); self.cache = OrderedDict(); self.pending = set()
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(2)
    def _run(self, key, fn):
        self.pending.add(key)
        def cb(r, key=key):
            self.cache[key] = r; self.pending.discard(key)
            while len(self.cache) > 1500: self.cache.popitem(last=False)
            self.updated.emit()
        self.pool.start(_Job(fn, cb))
    def thumb(self, path, kind, t, h):
        key = ("t", path, round(t, 1), h)
        if key in self.cache: return self.cache[key]
        if key not in self.pending: self._run(key, lambda: make_thumb(path, kind, t, h))
        return None
    def wave(self, path):
        if path in AUDIO.peaks: return AUDIO.peaks[path]
        key = ("w", path)
        if key not in self.pending and key not in self.cache: self._run(key, lambda: (AUDIO.load(path), None)[1])
        return None

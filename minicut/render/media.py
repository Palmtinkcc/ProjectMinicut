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


# ---------------------------------------------------------------------------------------------------------------
# Patch 45: video frames through an FFmpeg pipe (hardware decode that is verified, CPU decode otherwise).
#   * Hardware decoding is only used when "GPU video decode" is on in Settings AND the first frame it gives is
#     checked against the CPU decoder (a pink band / wrong colours fail the check) -> then that backend is not used.
#   * Any problem (FFmpeg does not start, no frames, ...) switches this video to the old cv2.VideoCapture reader.
#   * Set the environment variable MINICUT_CV2_DECODE=1 to use only the old reader.
# ---------------------------------------------------------------------------------------------------------------
_FF_LIVE = OrderedDict(); _FF_LOCK = threading.Lock()      # readers that own a running ffmpeg (kept to a few)
_FF_MAX_LIVE = 6
_FILE_HW = {}; _BAD_HW = {}; _HW_LISTED = []


def _hw_candidates():
    """Hardware decoders this FFmpeg build lists, best first. Listed does not mean working: each is verified."""
    if not _HW_LISTED:
        try:
            out = subprocess.run([FFMPEG, "-hide_banner", "-hwaccels"], capture_output=True, text=True, errors="ignore",
                                 creationflags=NOWIN, timeout=15).stdout.split()
        except Exception:
            out = []
        order = ["d3d11va", "dxva2", "cuda", "qsv"] if os.name == "nt" else ["cuda", "vaapi", "videotoolbox", "qsv"]
        _HW_LISTED.append([b for b in order if b in out])
    return _HW_LISTED[0]


class _FFReader:
    """Same interface as _Reader (read(idx) / release()) but frames come from an FFmpeg subprocess pipe."""
    def __init__(self, path, fps, n, w, h, fallback):
        self.path = safe_path(path); self.fps = float(fps); self.n = n; self.w = w; self.h = h
        self.fallback = fallback; self.proc = None; self.pos = -10; self.raw = None
        self.backend = None; self.decided = False; self.dead = False; self.bad = 0
        try: st = os.stat(path); self.key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
        except OSError: self.key = (path, 0, 0)
    def _spawn(self, idx, backend):
        t = max(0.0, (idx - 0.5) / self.fps)          # half a frame early: the first frame given is exactly idx
        c = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if backend: c += ["-hwaccel", backend]
        if t > 0: c += ["-ss", "%.6f" % t]
        c += ["-i", self.path, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", "scale=%d:%d" % (self.w, self.h),
              "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        return subprocess.Popen(c, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                creationflags=NOWIN, bufsize=0)
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
    def _decide(self, idx):
        """Pick the hardware backend once per file: it must give the same picture as the CPU decoder."""
        self.decided = True; self.backend = None
        if not CFG.get("hw_decode"): return
        if self.key in _FILE_HW: self.backend = _FILE_HW[self.key]; return
        ref = None
        for b in _hw_candidates():
            if _BAD_HW.get(b, 0) >= 2: continue
            hw = cp = None
            try:
                hw = self._spawn(idx, b); fh = self._get(hw)
                if fh is None: _BAD_HW[b] = _BAD_HW.get(b, 0) + 1; continue
                if ref is None:
                    cp = self._spawn(idx, None); ref = self._get(cp)
                if ref is None: break                                  # cannot verify -> stay on the CPU
                if float(cv2.absdiff(fh, ref).mean()) < 6.0: self.backend = b; break
            except Exception:
                _BAD_HW[b] = _BAD_HW.get(b, 0) + 1
            finally:
                self._kill(hw); self._kill(cp)
        _FILE_HW[self.key] = self.backend
    def _start(self, idx):
        self._stop()
        proc = self._spawn(idx, self.backend)
        with _FF_LOCK:
            self.proc = proc; _FF_LIVE[id(self)] = self
            while len(_FF_LIVE) > _FF_MAX_LIVE:                       # too many ffmpeg running: stop the least used
                _, o = _FF_LIVE.popitem(last=False)
                if o is not self: p, o.proc = o.proc, None; self._kill(p)
        return proc
    def _stop(self):
        with _FF_LOCK:
            p, self.proc = self.proc, None; _FF_LIVE.pop(id(self), None)
        self._kill(p)
    def read(self, idx):
        if self.dead: return self.fallback.read(idx)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        if idx == self.pos and self.raw is not None: return self.raw
        try:
            if not self.decided:
                self._decide(idx)
                if self.backend is None: self.dead = True; return self.fallback.read(idx)      # no GPU decoder passed the check: OpenCV (CPU)
            for _ in range(3):
                proc = self.proc; gap = idx - self.pos; fresh = False
                if proc is None or proc.poll() is not None or gap <= 0 or gap > 8:
                    proc = self._start(idx); fresh = True; skip = 0
                else: skip = gap - 1
                f = None; ok = True
                for _s in range(skip):
                    if self._get(proc) is None: ok = False; break
                if ok: f = self._get(proc)
                if f is not None:
                    self.raw = f; self.pos = idx; self.bad = 0
                    with _FF_LOCK:
                        if id(self) in _FF_LIVE: _FF_LIVE.move_to_end(id(self))
                    return f
                self.pos = -10; self._stop()
                if fresh:
                    if self.backend: self.backend = None; _FILE_HW[self.key] = None; continue    # hardware failed -> CPU
                    self.bad += 1; break
        except Exception:
            self.bad += 1
        if self.raw is None or self.bad >= 2:                          # nothing ever read / keeps failing: old reader
            self.dead = True; self._stop(); return self.fallback.read(idx)
        return self.raw                                                # e.g. end of file: keep the last picture
    def release(self):
        self._stop()
        try: self.fallback.release()
        except Exception: pass


def _ff_on():
    """The FFmpeg pipe is used only when GPU decoding is switched on: with the CPU alone the OpenCV reader is faster."""
    return bool(CFG.get("hw_decode")) and not os.environ.get("MINICUT_CV2_DECODE") and bool(CFG.get("ff_decode", True))


def _make_reader(path, probe, fps, n, w, h):
    if not _ff_on() or w <= 0 or h <= 0 or not fps or fps != fps:
        return _Reader(probe)
    return _FFReader(path, fps, n, w, h, _Reader(probe))


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
                    e = min(n, s + 6000); blk = np.asarray(arr[s * hop:e * hop]).astype(np.int32)
                    pk[s:e] = np.abs(blk).max(axis=1).reshape(e - s, hop).max(axis=1) / 32768.0; time.sleep(0.001)      # lets the window draw in between
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
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)
        # Timeline thumbnails are background decoration: keep their CPU contention low so
        # preview decoding/compositing and the GUI have room to run during auto-scroll.
        try: self.pool.setThreadPriority(QThread.LowPriority)
        except Exception: pass
        self.apool = QThreadPool(); self.apool.setMaxThreadCount(1)      # sound of the cards: one at a time, thumbnails are not held up
        self.ppool = QThreadPool(); self.ppool.setMaxThreadCount(1)      # sound of the file that is being previewed
    def _run(self, key, fn, pool=None):
        self.pending.add(key)
        def cb(r, key=key):
            self.cache[key] = r; self.pending.discard(key)
            while len(self.cache) > 1500: self.cache.popitem(last=False)
            self.updated.emit()
        (pool or self.pool).start(_Job(fn, cb))
    def thumb(self, path, kind, t, h):
        key = ("t", path, round(t, 1), h)
        if key in self.cache:
            try: self.cache.move_to_end(key)
            except Exception: pass
            return self.cache[key]
        if key not in self.pending:
            # Scrolling can expose hundreds of new thumbnail timestamps quickly. Bound the queued
            # work so stale thumbnails cannot build an unbounded backlog ahead of playback.
            queued = sum(1 for k in self.pending if isinstance(k, tuple) and k and k[0] == "t")
            if queued >= 8:
                try:
                    from .debug_trace import trace_event
                    now = time.monotonic()
                    last = getattr(self, "_thumb_skip_log", 0.0)
                    if now - last >= 1.0:
                        self._thumb_skip_log = now
                        trace_event("thumbnail_queue_throttled", pending=queued, limit=8)
                except Exception: pass
                return None
            self._run(key, lambda: make_thumb(path, kind, t, h))
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

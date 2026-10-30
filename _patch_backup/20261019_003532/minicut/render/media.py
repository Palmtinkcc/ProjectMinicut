"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""
from ..shared.deps import *
from ..shared.core import *


def open_capture(path):
    """Open a video file. With "hw_decode" on (Settings) FFmpeg is asked to decode on the GPU; if that is not
    supported on this PC, fall back to the normal CPU decoder."""
    if CFG.get("hw_decode"):
        try:
            cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG, [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY])
            if cap.isOpened() and cap.read()[0]: return cap
            cap.release()
        except Exception: pass
    return cv2.VideoCapture(path)


PROXY_HEIGHT = 540
PROXY_CHUNK = 2.0                                              # seconds per proxy piece: pieces appear one by one
PROXY_POOL = QThreadPool(); PROXY_POOL.setMaxThreadCount(1)   # one proxy job at a time, in the background


def proxy_dir(path):
    """Folder with the proxy pieces of this video. Each piece is a small file in which every frame is a keyframe."""
    import hashlib
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d|%d|%s|%s" % (os.path.abspath(path), st.st_size, int(st.st_mtime),
                                            CFG.get("proxy_height", PROXY_HEIGHT), CFG.get("proxy_quality", 23))).encode("utf-8")).hexdigest()[:24]
    d = os.path.join(APP_DIR, "proxies", key); os.makedirs(d, exist_ok=True)
    return d


def _piece_path(d, k): return os.path.join(d, "p%05d.mp4" % k)


def proxy_pieces(path):
    """Numbers of the proxy pieces that are finished for this video (a piece is only renamed into place when complete)."""
    try:
        d = proxy_dir(path)
        return {int(f[1:6]) for f in os.listdir(d) if f.startswith("p") and f.endswith(".mp4") and ".tmp" not in f and f[1:6].isdigit()}
    except Exception: return set()


def video_duration(path):
    cap = cv2.VideoCapture(safe_path(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 30; n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0; cap.release()
    return n / fps if n > 0 else 0.0


def make_proxy(path):
    """Build the pieces in order (piece 0 first, so the start of a clip is ready soon). Finished pieces are kept."""
    d = proxy_dir(path); dur = video_duration(path); k = 0
    while True:
        if dur and k * PROXY_CHUNK >= dur - 1e-3: break
        dst = _piece_path(d, k)
        if not os.path.exists(dst):
            tmp = os.path.join(d, "p%05d.tmp.mp4" % k)
            cmd = [FFMPEG, "-y", "-v", "error", "-ss", "%.3f" % (k * PROXY_CHUNK), "-i", path, "-t", "%.3f" % PROXY_CHUNK, "-an",
                   "-vf", "scale=-2:min(%d\\,ih)" % int(CFG.get("proxy_height", PROXY_HEIGHT)),
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(CFG.get("proxy_quality", 23))), "-g", "1", "-pix_fmt", "yuv420p", tmp]
            try:
                r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN | (0x00004000 if os.name == "nt" else 0))
                ok = r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 200
            except Exception as ex:
                print("proxy error:", ex); ok = False
            if not ok:
                try: os.remove(tmp)
                except Exception: pass
                break
            os.replace(tmp, dst)
        k += 1
    return True


class _ProxyJob(QRunnable):
    def __init__(self, path, cb): super().__init__(); self.path = path; self.cb = cb
    def run(self):
        try: ok = make_proxy(self.path)
        except Exception as ex: print("proxy error:", ex); ok = False
        self.cb(ok)


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
    def release(self): self.cap.release()


class VideoSource:
    """Frames of a video. When a proxy piece covering the requested time is finished, the frame comes from it
    (fast seeking); otherwise it comes from the original file. Size, fps and length always come from the original."""
    KEEP_PIECES = 3
    def __init__(self, path, use_proxy=False):
        probe = open_capture(safe_path(path))
        if not probe.isOpened(): raise IOError("cannot open " + path)
        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.orig = _Reader(probe)
        self.dir = proxy_dir(path) if use_proxy else None
        self.pieces = OrderedDict(); self.cache = OrderedDict()
    def _piece(self, k):
        if k in self.pieces: self.pieces.move_to_end(k); return self.pieces[k]
        f = _piece_path(self.dir, k)
        if not os.path.exists(f): return None
        cap = cv2.VideoCapture(safe_path(f))
        if not cap.isOpened(): return None
        self.pieces[k] = _Reader(cap)
        while len(self.pieces) > self.KEEP_PIECES: self.pieces.popitem(last=False)[1].release()
        return self.pieces[k]
    def frame(self, t, ds=1.0):
        t = max(0.0, t)
        idx = int(t * self.fps + 1e-6)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        key = (idx, ds)
        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
        raw = None
        if self.dir is not None:
            k = int(t // PROXY_CHUNK); rd = self._piece(k)
            if rd is not None: raw = rd.read(int((t - k * PROXY_CHUNK) * self.fps + 1e-6))
        if raw is None: raw = self.orig.read(idx)
        if raw is None: raw = np.zeros((max(1, self.h), max(1, self.w), 3), np.uint8)
        tw, th = max(1, int(self.w * ds)), max(1, int(self.h * ds))
        if raw.shape[1] != tw or raw.shape[0] != th:
            raw = cv2.resize(raw, (tw, th), interpolation=cv2.INTER_AREA if tw < raw.shape[1] else cv2.INTER_LINEAR)
        img = cv2.cvtColor(raw, cv2.COLOR_BGR2BGRA)
        self.cache[key] = img
        while len(self.cache) > CFG["frame_cache"]: self.cache.popitem(last=False)
        return img



class ImageSource:
    def __init__(self, path):
        self.img = to_bgra(imread_any(path))
        if self.img is None: raise IOError("cannot open " + path)
        self.h, self.w = self.img.shape[:2]; self.cache = {}
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


class MediaPool:
    def __init__(self, use_proxy=False): self.src = {}; self.make_compound = None; self.use_proxy = use_proxy; self._proxy_jobs = set()
    def _video(self, p):
        if not self.use_proxy: return VideoSource(p)
        # Pieces are built in the background; the source picks each one up as soon as it is finished.
        if p not in self._proxy_jobs:
            self._proxy_jobs.add(p)
            PROXY_POOL.start(_ProxyJob(p, lambda ok: None))
        return VideoSource(p, use_proxy=True)
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
    def __init__(self): self.data = {}; self.peaks = {}; self.lock = threading.Lock()
    def load(self, path):
        with self.lock:
            if path in self.data: return self.data[path]
            arr = None
            try:
                p = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"],
                                   capture_output=True, creationflags=NOWIN)
                a = np.frombuffer(p.stdout, np.int16)
                if a.size >= 2: arr = a[: a.size // 2 * 2].reshape(-1, 2)
            except Exception: pass
            self.data[path] = arr
            if arr is not None:
                hop = SR // 100; n = len(arr) // hop
                self.peaks[path] = (np.abs(arr[: n * hop]).max(axis=1).reshape(n, hop).max(axis=1) / 32768.0).astype(np.float32)
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

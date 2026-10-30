"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""
from ..shared.deps import *
from ..shared.core import *


class VideoSource:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(safe_path(path))
        if not self.cap.isOpened(): raise IOError("cannot open " + path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.pos = -10; self.raw = None; self.cache = OrderedDict()
    def frame(self, t, ds=1.0):
        idx = int(t * self.fps + 1e-6)
        if self.n > 0: idx = max(0, min(self.n - 1, idx))
        key = (idx, ds)
        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
        if idx != self.pos or self.raw is None:
            gap = idx - self.pos
            if 0 < gap <= 8:
                for _ in range(gap - 1): self.cap.grab()
            else: self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, f = self.cap.read()
            if ok: self.raw = f; self.pos = idx
            else:
                self.pos = -10
                if self.raw is None: self.raw = np.zeros((max(1, self.h), max(1, self.w), 3), np.uint8)
        img = self.raw
        if ds < 0.999: img = cv2.resize(img, (max(1, int(self.w * ds)), max(1, int(self.h * ds))), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
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
    def __init__(self): self.src = {}; self.make_compound = None
    def get(self, c):
        if c.get("kind") == "compound": return self.make_compound(c) if self.make_compound else None
        p = c["path"]
        if p not in self.src:
            try:
                k = c["kind"]
                self.src[p] = VideoSource(p) if k == "video" else GifSource(p) if k == "gif" else ImageSource(p) if k == "image" else None
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

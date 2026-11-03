"""Media speed for sound: the part of a clip's sound that plays at a given time when the clip is faster or slower.

Two ways, chosen per clip (the "Pitch follows speed" switch):
  * pitch follows speed: the sound is simply played faster / slower (like a tape): faster = higher, slower = deeper.
    This is done on the fly, for any piece of the clip, with no waiting.
  * pitch stays the same: the sound is stretched with WSOLA (overlap-add of pieces that are lined up with each other).
    This is made for the whole clip in the background and kept in memory; until it is ready the preview uses the
    first way, and the export waits for it, so the export always has the right sound.
The speed itself (constant or keyframed) comes from the clip: see src_time() in shared/core.py."""
from ..shared.deps import *
from ..shared.core import *
import threading
from ..shared.tasks import TASKS

STRETCH_BUDGET = 1.0e9                 # bytes of stretched sound kept in memory
STRETCH_CACHE = OrderedDict()          # key -> int16 stereo array (clip time 0 ... clip length)
_PENDING = set(); _LOCK = threading.Lock()
STRETCH_POOL = QThreadPool(); STRETCH_POOL.setMaxThreadCount(1)


def _snapshot(c):
    """The few things of a clip that the mapping needs (copied, so editing the clip while it is computed is harmless)."""
    sp = (c.get("props") or {}).get("speed") or {"v": 100.0, "k": []}
    return {"kind": c["kind"], "inp": float(c["inp"]), "dur": float(c["dur"]), "props": {"speed": copy.deepcopy(sp)}}


def _key(c, data):
    sp = c["props"]["speed"]
    return (c.get("path"), id(data), round(float(c["inp"]), 4), round(float(c["dur"]), 4), json.dumps([sp["v"], sp["k"]], sort_keys=True))


def resample_piece(c, data, lt0, length, sr=SR):
    """Pitch follows speed: the sound of local time lt0 ... lt0 + length, played faster / slower. float32, int16 scale."""
    n = max(0, int(length * sr)); out = np.zeros((n, 2), np.float32)
    if n == 0 or data is None or not len(data): return out
    pos = src_time_arr(c, lt0 + np.arange(n) / sr) * sr
    i0 = np.floor(pos).astype(np.int64); fr = (pos - i0).astype(np.float32)[:, None]
    last = len(data) - 1; ok = (i0 >= 0) & (i0 <= last)
    if not ok.any(): return out
    lo = int(i0[ok].min()); hi = min(last, int(i0[ok].max()) + 1)
    chunk = np.asarray(data[lo:hi + 1]).astype(np.float32)
    a = np.clip(i0 - lo, 0, len(chunk) - 1); b = np.clip(i0 + 1 - lo, 0, len(chunk) - 1)
    seg = chunk[a] * (1.0 - fr) + chunk[b] * fr
    seg[~ok] = 0.0
    return seg


def wsola(data, snap, sr=SR, alive=None):
    """The whole clip's sound with its speed applied and the pitch kept. Returns int16 stereo, length = clip length."""
    n_out = max(1, int(snap["dur"] * sr)); N = 2048; Hs = N // 2; tol = 512; D = 4
    win = np.hanning(N).astype(np.float32)[:, None]
    mono = (np.asarray(data[:, 0], np.float32) + np.asarray(data[:, 1], np.float32)) * 0.5
    dec = mono[::D].copy(); L = len(data)
    outs = np.arange(0, n_out, Hs); want = (src_time_arr(snap, outs / float(sr)) * sr).astype(np.int64)
    out = np.zeros((n_out + N, 2), np.float32); wsum = np.zeros((n_out + N, 1), np.float32)
    prev = None
    for k, o in enumerate(outs):
        if alive is not None and not alive(): return None
        a = int(want[k]); pos = a
        if prev is not None and 0 <= a < L:
            nat = prev + Hs; lo = max(0, a - tol)
            ref = dec[nat // D: nat // D + N // D]
            cand = dec[lo // D: (a + tol + N) // D]
            if len(ref) == N // D and len(cand) > len(ref):
                c = np.correlate(cand, ref, "valid"); pos = lo + D * int(np.argmax(c))
        prev = pos
        if pos < 0 or pos >= L: continue
        fr = np.asarray(data[pos:pos + N]).astype(np.float32); m = len(fr)
        out[o:o + m] += fr * win[:m]; wsum[o:o + m] += win[:m]
    y = out[:n_out] / np.maximum(wsum[:n_out], 1e-3)
    return np.clip(y, -32768, 32767).astype(np.int16)


def _make(snap, data, key):
    y = wsola(data, snap)
    with _LOCK:
        if y is not None:
            STRETCH_CACHE[key] = y
            while len(STRETCH_CACHE) > 1 and sum(v.nbytes for v in STRETCH_CACHE.values()) > STRETCH_BUDGET: STRETCH_CACHE.popitem(last=False)
        _PENDING.discard(key)
    return y


class _Job(QRunnable):
    def __init__(self, snap, data, key, name):
        super().__init__(); self.a = (snap, data, key); self.name = name; self.setAutoDelete(True)
    def run(self):
        task = TASKS.start("audio", "Speed  " + self.name)
        try: _make(*self.a)
        except Exception as ex:
            print("speed:", ex)
            with _LOCK: _PENDING.discard(self.a[2])
        finally: task.finish()


def stretched(c, data, wait=False):
    """Pitch-kept sound of the whole clip (clip time 0 ...), or None while it is being made."""
    key = _key(c, data)
    with _LOCK:
        if key in STRETCH_CACHE: STRETCH_CACHE.move_to_end(key); return STRETCH_CACHE[key]
    if wait: return _make(_snapshot(c), data, key)
    with _LOCK:
        if key not in _PENDING:
            _PENDING.add(key); STRETCH_POOL.start(_Job(_snapshot(c), data, key, os.path.basename(c.get("path") or "")))
    return None


def speed_piece(c, data, lt0, length, sr=SR, wait=False):
    """Sound of local time lt0 ... lt0 + length of a clip that has a speed. float32 stereo, int16 scale."""
    if not c.get("pitch_follow", False):
        w = stretched(c, data, wait)
        if w is not None:
            n = max(0, int(length * sr)); s = max(0, int(lt0 * sr)); seg = w[s:s + n].astype(np.float32)
            if len(seg) < n: seg = np.vstack([seg, np.zeros((n - len(seg), 2), np.float32)])
            return seg
    return resample_piece(c, data, lt0, length, sr)

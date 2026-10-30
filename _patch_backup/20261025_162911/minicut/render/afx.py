"""Audio effects for clips: echo, reverb, low-pass, high-pass, 3-band EQ and pan.

The effects are applied to the whole audio file of a clip and the result is kept in memory (like the proxies).
While it is being made, playback uses the clean audio; when it is ready the preview switches to it. The export
waits for it, so the export always contains the effects."""
from ..shared.deps import *
from ..shared.core import *
from .media import AUDIO
import threading
from ..shared.tasks import TASKS


AFX_FX = OrderedDict([
    ("echo", {"title": "Echo", "params": [("delay", "Delay (ms)", 1, 2000, 350, 1), ("feedback", "Feedback %", 0, 95, 40, 1), ("mix", "Mix %", 0, 100, 35, 1)]}),
    ("reverb", {"title": "Reverb", "params": [("decay", "Decay (s)", 0.2, 6, 1.8, 0.1), ("predelay", "Pre-delay (ms)", 0, 150, 20, 1), ("mix", "Mix %", 0, 100, 25, 1)]}),
    ("lowpass", {"title": "Low-pass", "params": [("cutoff", "Cutoff (Hz)", 80, 20000, 8000, 10)]}),
    ("highpass", {"title": "High-pass", "params": [("cutoff", "Cutoff (Hz)", 20, 5000, 120, 5)]}),
    ("eq", {"title": "EQ (3-band)", "params": [("low", "Low (dB)", -12, 12, 0, .5), ("mid", "Mid (dB)", -12, 12, 0, .5), ("high", "High (dB)", -12, 12, 0, .5)]}),
    ("denoise", {"title": "Denoise", "params": [("amount", "Amount %", 0, 100, 60, 1), ("floor", "Floor %", 0, 50, 5, 1)]}),
    ("pan", {"title": "Pan", "params": [("pan", "Pan  (L ← 0 → R)", -100, 100, 0, 1)]}),
])


def afx_defaults(type_):
    return {k: d for k, _, _, _, d, _ in AFX_FX[type_]["params"]}


def _params(e):
    p = afx_defaults(e["type"]); p.update(e.get("p") or {}); return p


def _conv(x, H, B, M):
    """Overlap-add FFT convolution. x: (N, 2) float32. H: (B//2+1, 1 or 2) spectrum of the kernel(s). Output length N."""
    N = len(x); L = B - M + 1; out = np.zeros((N, 2), np.float32)
    for s in range(0, N, L):
        Y = np.fft.irfft(np.fft.rfft(x[s:s + L], B, axis=0) * H, B, axis=0)
        e = min(N, s + B); out[s:e] += Y[:e - s].astype(np.float32)
    return out


def _zero_phase_kernel(G, M=2049):
    """Linear-phase FIR (length M) from a magnitude curve G sampled on the rfft grid of 4096 points."""
    h = np.fft.irfft(G, 4096); h = np.concatenate([h[-(M // 2):], h[:M // 2 + 1]])
    return (h * np.hanning(M)).astype(np.float32)


def _transition(f, x0, width=1.0):
    """0 below x0 and 1 above it, smooth over one octave (raised cosine)."""
    d = (np.log2(np.maximum(f, 1.0)) - np.log2(x0) + width) / (2 * width)
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(d, 0.0, 1.0))


def _fir(x, h):
    M = len(h); B = 1 << int(np.ceil(np.log2(max(4 * M, 1 << 14))))
    H = np.fft.rfft(h, B)[:, None]
    return _conv(x, H, B, M)


def fx_lowpass(x, p, sr=SR):
    f = np.fft.rfftfreq(4096, 1 / sr); return _fir(x, _zero_phase_kernel(1.0 - _transition(f, float(p["cutoff"]), 0.5)))


def fx_highpass(x, p, sr=SR):
    f = np.fft.rfftfreq(4096, 1 / sr); return _fir(x, _zero_phase_kernel(_transition(f, float(p["cutoff"]), 0.5)))


def fx_eq(x, p, sr=SR):
    f = np.fft.rfftfreq(4096, 1 / sr)
    lo, mid, hi = (10 ** (float(p[k]) / 20) for k in ("low", "mid", "high"))
    s1 = _transition(f, 250.0); s2 = _transition(f, 4000.0)
    G = lo * (1 - s1) + mid * s1 * (1 - s2) + hi * s2
    return _fir(x, _zero_phase_kernel(G))


def fx_echo(x, p, sr=SR):
    d = int(round(float(p["delay"]) / 1000 * sr)); fb = float(p["feedback"]) / 100; mix = float(p["mix"]) / 100
    if d <= 0 or fb <= 0 or mix <= 0: return x
    taps = min(40, int(np.ceil(np.log(0.001) / np.log(fb))))       # each repeat is fb times the one before
    wet = np.zeros_like(x)
    for k in range(1, taps + 1):
        s = k * d
        if s >= len(x): break
        wet[s:] += (fb ** k) * x[:-s]
    return x + mix * wet


def fx_reverb(x, p, sr=SR):
    mix = float(p["mix"]) / 100; decay = max(0.2, float(p["decay"])); pre = int(float(p["predelay"]) / 1000 * sr)
    if mix <= 0: return x
    n = int(decay * sr); t = np.arange(n) / sr
    rng = np.random.default_rng(7)                                    # the same room every time
    ir = rng.standard_normal((n, 2)).astype(np.float32) * np.exp(-6.91 * t / decay)[:, None].astype(np.float32)
    ir = np.concatenate([np.zeros((pre, 2), np.float32), ir]); ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-9
    M = len(ir); B = 1 << int(np.ceil(np.log2(max(4 * M, 1 << 14))))
    wet = _conv(x, np.fft.rfft(ir, B, axis=0), B, M)
    scale = (np.sqrt(np.mean(x ** 2)) + 1e-9) / (np.sqrt(np.mean(wet ** 2)) + 1e-9)
    return (1 - mix) * x + mix * wet * min(scale, 4.0)


def fx_pan(x, p, sr=SR):
    v = float(p["pan"]) / 100
    out = x.copy(); out[:, 0] *= 1 - max(0.0, v); out[:, 1] *= 1 - max(0.0, -v); return out


def fx_denoise(x, p, sr=SR):
    """Spectral noise reduction: the noise is the quietest 10 % of the frames of each frequency. That part is
    taken away from every frame (a floor keeps it from sounding hollow)."""
    amount = float(p["amount"]) / 100; floor = float(p["floor"]) / 100
    if amount <= 0 or len(x) < 4096: return x
    n = 2048; hop = 512; win = np.hanning(n).astype(np.float32)
    N = len(x); pad = np.zeros((N + 2 * n, 2), np.float32); pad[n:n + N] = x
    nf = 1 + (len(pad) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(nf)[:, None]
    sub = idx[::4]
    noise = np.percentile(np.abs(np.fft.rfft(pad[sub] * win[None, :, None], axis=1)), 10, axis=0)   # (bins, 2)
    out = np.zeros_like(pad); wsum = np.zeros((len(pad), 1), np.float32); wsq = (win ** 2)[:, None]
    for s in range(0, nf, 2000):
        ii = idx[s:s + 2000]
        X = np.fft.rfft(pad[ii] * win[None, :, None], axis=1); m = np.abs(X)
        g = np.maximum(m - amount * 1.5 * noise[None], floor * m) / np.maximum(m, 1e-9)
        Y = (np.fft.irfft(X * g, n, axis=1) * win[None, :, None]).astype(np.float32)
        for r in range(n // hop):          # frames r, r+4, ... never overlap each other: one fancy add per group
            sel = np.arange(r, len(ii), n // hop)
            if not len(sel): continue
            rows = ii[sel]
            out[rows] += Y[sel]; wsum[rows] += wsq[None, :, :]
    res = out / np.maximum(wsum, 1e-6)
    return np.clip(res[n:n + N], -1.0, 1.0).astype(np.float32)


AFX_FN = {"denoise": fx_denoise, "echo": fx_echo, "reverb": fx_reverb, "lowpass": fx_lowpass, "highpass": fx_highpass, "eq": fx_eq, "pan": fx_pan}


def active_chain(c):
    return [e for e in (c.get("afx") or []) if e.get("on", True) and e.get("type") in AFX_FN]


def apply_chain(x, chain):
    for e in chain:
        x = AFX_FN[e["type"]](x, _params(e))
    return x


# ---------- cache and background work ----------
AFX_BUDGET = 1.5e9   # bytes kept for processed audio (about 35 minutes of stereo)
AFX_CACHE = OrderedDict()          # (file, chain) -> processed audio, int16 stereo like the original files
_PENDING = set(); _LOCK = threading.Lock()
AFX_POOL = QThreadPool(); AFX_POOL.setMaxThreadCount(1)


def _key(path, chain):
    return (path, json.dumps([[e["type"], _params(e)] for e in chain], sort_keys=True))


def _make(path, chain, key):
    data = AUDIO.load(path)
    if data is None: return None
    x = np.asarray(data, np.float32) / 32768.0
    if x.ndim == 1: x = np.stack([x, x], 1)
    y = (np.clip(apply_chain(x, chain), -1, 1) * 32767).astype(np.int16)
    with _LOCK:
        AFX_CACHE[key] = y
        while len(AFX_CACHE) > 1 and sum(v.nbytes for v in AFX_CACHE.values()) > AFX_BUDGET: AFX_CACHE.popitem(last=False)
        _PENDING.discard(key)
    return y


class _AfxJob(QRunnable):
    def __init__(self, path, chain, key):
        super().__init__(); self.a = (path, chain, key); self.setAutoDelete(True)
    def run(self):
        task = TASKS.start("audio", "Audio effects  " + os.path.basename(self.a[0]))
        try: _make(*self.a)
        except Exception as ex:
            print("audio effects:", ex)
            with _LOCK: _PENDING.discard(self.a[2])
        finally: task.finish()


def processed(path, chain, wait=False):
    """The file with the chain applied, or None while it is being made (the caller then uses the clean audio)."""
    key = _key(path, chain)
    with _LOCK:
        if key in AFX_CACHE: AFX_CACHE.move_to_end(key); return AFX_CACHE[key]
    if wait: return _make(path, chain, key)
    with _LOCK:
        if key not in _PENDING:
            _PENDING.add(key); AFX_POOL.start(_AfxJob(path, chain, key))
    return None


def audio_data_for(c, wait=False):
    """What the mixer should read for this clip: the processed audio when there is a chain and it is ready."""
    chain = active_chain(c)
    if chain:
        d = processed(c["path"], chain, wait)
        if d is not None: return d
    return AUDIO.load(c["path"])

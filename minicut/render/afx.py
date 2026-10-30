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
    ("echo", {"title": "Echo", "params": [("delay", "Delay (ms)", 1, 2000, 350, 1), ("feedback", "Feedback %", 0, 95, 40, 1), ("mix", "Mix %", 0, 100, 35, 1)],
              "help": "Repeats the sound again and again, each repeat quieter. Delay = time between the repeats. Feedback = how many repeats you hear (higher = longer). Mix = how loud the echo is next to the original. The echo goes on after the clip ends: use \"Fit length to filter\" so it is not cut off."}),
    ("reverb", {"title": "Reverb", "params": [("decay", "Decay (s)", 0.2, 6, 1.8, 0.1), ("predelay", "Pre-delay (ms)", 0, 150, 20, 1), ("mix", "Mix %", 0, 100, 25, 1)],
                "help": "Makes the sound seem to be in a room or a hall. Decay = how long the room keeps ringing. Pre-delay = the pause before the room answers. Mix = how much room you hear. The ring-out lasts after the clip ends: use \"Fit length to filter\"."}),
    ("lowpass", {"title": "Low-pass", "params": [("cutoff", "Cutoff (Hz)", 80, 20000, 8000, 10)],
                 "help": "Removes high sounds (treble). Cutoff = the frequency above which the sound is turned down. The lower it is, the more muffled it gets, like sound heard through a wall."}),
    ("highpass", {"title": "High-pass", "params": [("cutoff", "Cutoff (Hz)", 20, 5000, 120, 5)],
                  "help": "Removes low sounds (rumble, wind, bumps on the microphone). Cutoff = the frequency below which the sound is turned down. 80 to 150 Hz is good for a voice."}),
    ("eq", {"title": "EQ (3-band)", "params": [("low", "Low (dB)", -12, 12, 0, .5), ("mid", "Mid (dB)", -12, 12, 0, .5), ("high", "High (dB)", -12, 12, 0, .5)],
            "help": "Turns the bass (Low), the middle (Mid) and the treble (High) up or down. 0 = no change. A voice that is too boomy: lower Low. A voice that is dull: raise High."}),
    ("denoise", {"title": "Denoise", "params": [("amount", "Amount %", 0, 100, 60, 1), ("floor", "Floor %", 0, 50, 5, 1), ("noise_db", "Noise level (dB)", -90, -10, -90, 1)],
                 "help": "Reduces steady background noise (fan, room tone, tape noise). Amount = how much noise is taken away (too much sounds watery). Floor = how much is kept so it still sounds natural. Noise level = how loud the noise is; -90 means MiniCut finds it by itself. Press Auto adjust to show the noise level on a graph."}),
    ("hum", {"title": "Hum remover", "params": [("freq", "Hum (Hz)", 40, 70, 50, 1), ("harmonics", "Harmonics", 1, 8, 4, 1), ("width", "Width (Hz)", 1, 10, 3, 0.5)],
             "help": "Removes the electric hum (a steady low \"mmmm\") that comes from mains power. Hum (Hz) = 50 in most countries (Thailand, Europe) and 60 in the USA and Japan. Harmonics = how many higher whines are removed too. Width = how wide each cut is: keep it small so the voice is not hurt."}),
    ("gate", {"title": "Noise gate", "params": [("threshold", "Open above (dB)", -80, -10, -45, 1), ("reduction", "Reduce by (dB)", 6, 80, 40, 1), ("attack", "Attack (ms)", 1, 200, 8, 1), ("release", "Release (ms)", 20, 1500, 200, 5)],
              "help": "Turns the sound down when it is quieter than a level, so the noise between words disappears. Open above = how loud the sound must be to pass. Reduce by = how much it is turned down when closed. Attack / Release = how fast it opens / closes (too fast chops the words). Press Auto adjust to set it on a graph."}),
    ("hiss", {"title": "Hiss remover", "params": [("cutoff", "From (Hz)", 1000, 16000, 5000, 100), ("amount", "Amount %", 0, 100, 60, 1)],
              "help": "Reduces the \"sss\" hiss of microphones and tapes, which lives in the high frequencies. From = the hiss is reduced above this frequency. Amount = how strong. Press Auto adjust to let MiniCut find the frequency."}),
    ("pan", {"title": "Pan", "params": [("pan", "Pan  (L \u2190 0 \u2192 R)", -100, 100, 0, 1)],
             "help": "Moves the sound to the left or to the right. -100 = only the left speaker, 0 = the middle, 100 = only the right speaker."}),
])
AFX_AUTO = ("denoise", "gate", "hiss")        # the filters that have an Auto adjust window


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
    amount = float(p["amount"]) / 100; floor = float(p["floor"]) / 100; fmin = float(p.get("fmin", 0) or 0)
    if amount <= 0 or len(x) < 4096: return x
    n = 2048; hop = 512; win = np.hanning(n).astype(np.float32); fr = np.fft.rfftfreq(n, 1.0 / sr)
    N = len(x); pad = np.zeros((N + 2 * n, 2), np.float32); pad[n:n + N] = x
    nf = 1 + (len(pad) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(nf)[:, None]
    sub = idx[::4]; S = np.abs(np.fft.rfft(pad[sub] * win[None, :, None], axis=1)); ndb = float(p.get("noise_db", -90))
    noise = np.percentile(S, 10, axis=0)   # (bins, 2)
    if ndb > -89:          # a noise level was chosen: the noise is what the frames under that level contain
        db = 10 * np.log10(np.maximum(np.mean(2 * np.sum(S ** 2, axis=1) / (n * n) / 0.375, axis=1), 1e-12))
        quiet = db < ndb
        if quiet.sum() >= 3: noise = S[quiet].mean(axis=0) * 0.65
    out = np.zeros_like(pad); wsum = np.zeros((len(pad), 1), np.float32); wsq = (win ** 2)[:, None]
    for s in range(0, nf, 2000):
        ii = idx[s:s + 2000]
        X = np.fft.rfft(pad[ii] * win[None, :, None], axis=1); m = np.abs(X)
        g = np.maximum(m - amount * 1.5 * noise[None], floor * m) / np.maximum(m, 1e-9)
        if fmin > 0: g = np.where(fr[None, :, None] >= fmin, g, 1.0)            # only above this frequency
        Y = (np.fft.irfft(X * g, n, axis=1) * win[None, :, None]).astype(np.float32)
        for r in range(n // hop):          # frames r, r+4, ... never overlap each other: one fancy add per group
            sel = np.arange(r, len(ii), n // hop)
            if not len(sel): continue
            rows = ii[sel]
            out[rows] += Y[sel]; wsum[rows] += wsq[None, :, :]
    res = out / np.maximum(wsum, 1e-6)
    return np.clip(res[n:n + N], -1.0, 1.0).astype(np.float32)


def fx_gate(x, p, sr=SR):
    """Noise gate: when the sound is quieter than the threshold it is turned down (the noise between words goes away)."""
    thr = 10 ** (float(p["threshold"]) / 20); red = 10 ** (-float(p["reduction"]) / 20)
    att = max(1.0, float(p["attack"])) / 1000; rel = max(1.0, float(p["release"])) / 1000
    B = 128; N = len(x); nb = N // B
    if nb < 4: return x
    lev = np.abs(x[:nb * B]).max(axis=1).reshape(nb, B).max(axis=1)
    lev = np.maximum(lev, np.maximum(np.r_[lev[1:], lev[-1:]], np.r_[lev[:1], lev[:-1]]))      # a short hold: words are not chopped
    target = np.where(lev > thr, 1.0, red).astype(np.float32)
    ca = 1 - np.exp(-B / (sr * att)); cr = 1 - np.exp(-B / (sr * rel)); g = np.empty(nb, np.float32); cur = float(target[0])
    for i in range(nb):
        t = float(target[i]); cur += (ca if t > cur else cr) * (t - cur); g[i] = cur
    gain = np.interp(np.arange(N), (np.arange(nb) + 0.5) * B, g).astype(np.float32)
    return (x * gain[:, None]).astype(np.float32)


def fx_hum(x, p, sr=SR):
    """Takes out the mains hum (50 / 60 Hz) and its harmonics with very narrow notches."""
    f0 = float(p["freq"]); nh = int(p["harmonics"]); w = max(0.5, float(p["width"]) / 2.355)
    n = 32768; hop = n // 2; N = len(x); fr = np.fft.rfftfreq(n, 1 / sr); g = np.ones_like(fr); w = max(w, 1.5 * sr / n)
    for h in range(1, nh + 1):
        if f0 * h >= sr / 2: break
        g *= 1 - 0.98 * np.exp(-0.5 * ((fr - f0 * h) / w) ** 2)
    win = np.sin(np.pi * (np.arange(n) + 0.5) / n).astype(np.float32)[:, None]
    pad = np.zeros((N + 2 * n, 2), np.float32); pad[n:n + N] = x; out = np.zeros_like(pad)
    for s in range(0, len(pad) - n + 1, hop):
        X = np.fft.rfft(pad[s:s + n] * win, axis=0) * g[:, None]
        out[s:s + n] += (np.fft.irfft(X, n, axis=0) * win).astype(np.float32)
    return np.clip(out[n:n + N], -1.0, 1.0).astype(np.float32)


def fx_hiss(x, p, sr=SR):
    """Spectral noise reduction that works only above a frequency (hiss lives in the high frequencies)."""
    return fx_denoise(x, {"amount": min(250.0, float(p["amount"]) * 2.2), "floor": 3, "fmin": p["cutoff"]}, sr)      # stronger than Denoise: hiss is steady


AFX_FN = {"gate": fx_gate, "hum": fx_hum, "hiss": fx_hiss, "denoise": fx_denoise, "echo": fx_echo, "reverb": fx_reverb, "lowpass": fx_lowpass, "highpass": fx_highpass, "eq": fx_eq, "pan": fx_pan}


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


def chain_tail(chain):
    """Seconds that the filters make the sound last after the end of the file (echo repeats, the ring of the reverb)."""
    s = 0.0
    for e in chain:
        p = _params(e)
        if e["type"] == "echo" and p["feedback"] > 0 and p["mix"] > 0: s += p["delay"] / 1000.0 * min(40, np.ceil(np.log(0.001) / np.log(max(0.01, p["feedback"] / 100.0))))
        elif e["type"] == "reverb" and p["mix"] > 0: s += p["decay"] + p["predelay"] / 1000.0
    return min(20.0, s)


def _make(path, chain, key):
    data = AUDIO.load(path)
    if data is None: return None
    x = np.asarray(data, np.float32) / 32768.0
    if x.ndim == 1: x = np.stack([x, x], 1)
    n0 = len(x); tail = int(chain_tail(chain) * SR)
    if tail: x = np.concatenate([x, np.zeros((tail, 2), np.float32)])
    y = np.clip(apply_chain(x, chain), -1, 1)
    if tail:        # keep only the part of the tail that can be heard (louder than -60 dB)
        loud = np.nonzero(np.abs(y[n0:]).max(axis=1) > 1e-3)[0]; y = y[: n0 + (int(loud[-1]) + 1 if len(loud) else 0)]
    y = (y * 32767).astype(np.int16)
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


def tail_info(c):
    """Seconds by which the filtered sound of the clip is longer than its file (0 = not longer); None while it is being made."""
    chain = active_chain(c)
    if not chain: return 0.0
    y = processed(c["path"], chain, False)
    if y is None: return None
    d = AUDIO.data.get(c["path"]); n0 = len(d) if d is not None else len(y)
    return max(0.0, (len(y) - n0) / float(SR))


def audio_data_for(c, wait=False):
    """What the mixer should read for this clip: the processed audio when there is a chain and it is ready."""
    chain = active_chain(c)
    if chain:
        d = processed(c["path"], chain, wait)
        if d is not None: return d
    return AUDIO.load(c["path"])

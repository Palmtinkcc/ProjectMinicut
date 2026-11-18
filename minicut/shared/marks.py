"""Marks (CapCut style) shared by the main timeline and the Bone2D animation sheet.

A "mark set" is any object with these attributes (Project has them, DictMarks wraps an animation dict):
    markers        sorted list of seconds
    marker_names   {"%.3f" % t: "name"}
    marker_colors  {"%.3f" % t: "#rrggbb"}
    beat_grid      {"on": bool, "show": bool, "bpm": float, "offset": float, "div": float}
Everything here is plain numpy / python, so both editors (and the Auto mark dialog) recycle the same code.
"""
import colorsys
import numpy as np

MARK_DEFAULT = "#f59e0b"
PALETTE = [("Amber", "#f59e0b"), ("Red", "#ef4444"), ("Pink", "#ec4899"), ("Violet", "#8b5cf6"),
           ("Blue", "#3b82f6"), ("Cyan", "#22d3ee"), ("Green", "#22c55e"), ("White", "#e5e7eb")]
DEFAULT_GRID = {"on": False, "show": True, "bpm": 120.0, "offset": 0.0, "div": 1.0}
DIVS = [("Every beat", 1.0), ("Every 2 beats", 2.0), ("Every bar (4 beats)", 4.0), ("Half beat", 0.5), ("Quarter beat", 0.25)]
MODES = [("Beats (steady tempo)", "beats"), ("All sound hits", "all"), ("Bass / kick hits", "bass"), ("Mid / voice hits", "mid"), ("High / hi-hat hits", "high")]


def key(t): return "%.3f" % t


def clean_grid(g):
    out = dict(DEFAULT_GRID)
    if isinstance(g, dict):
        for k, v in g.items():
            if k in out: out[k] = v
    out["bpm"] = max(20.0, min(400.0, float(out["bpm"]))); out["offset"] = float(out["offset"]); out["div"] = max(0.125, float(out["div"]))
    out["on"] = bool(out["on"]); out["show"] = bool(out["show"]); return out


class DictMarks:
    """The same four attributes as Project, stored inside a dict (a Bone2D animation) so every mark function works on both."""
    def __init__(self, d, fps=30): self._d = d; self.fps = fps
    markers = property(lambda s: s._d.setdefault("markers", []), lambda s, v: s._d.__setitem__("markers", v))
    marker_names = property(lambda s: s._d.setdefault("marker_names", {}), lambda s, v: s._d.__setitem__("marker_names", v))
    marker_colors = property(lambda s: s._d.setdefault("marker_colors", {}), lambda s, v: s._d.__setitem__("marker_colors", v))
    @property
    def beat_grid(self):
        g = clean_grid(self._d.get("beat_grid")); self._d["beat_grid"] = g; return g
    @beat_grid.setter
    def beat_grid(self, v): self._d["beat_grid"] = clean_grid(v)


# ───────────────────────── beat grid ─────────────────────────
def grid_times(g, t0, t1):
    """Grid lines (seconds) inside [t0, t1]."""
    g = clean_grid(g); step = 60.0 / g["bpm"] * g["div"]
    if step <= 1e-4 or t1 < t0: return []
    k0 = int(np.ceil((t0 - g["offset"]) / step - 1e-9)); k1 = int(np.floor((t1 - g["offset"]) / step + 1e-9))
    if k1 - k0 > 20000: return []
    return [g["offset"] + k * step for k in range(k0, k1 + 1) if g["offset"] + k * step >= -1e-9]


def nearest_beat(g, t):
    g = clean_grid(g); step = 60.0 / g["bpm"] * g["div"]; k = round((t - g["offset"]) / step)
    return max(0.0, g["offset"] + k * step)


def snap_time(m, t, fps=None):
    """Where a mark added / dragged at t lands: on the nearest beat when 'Lock to beat' is on, else on the nearest frame."""
    g = m.beat_grid
    if g["on"]: return round(nearest_beat(g, t), 3)
    fps = fps or getattr(m, "fps", 30) or 30
    return round(round(t * fps) / fps, 3)


def beat_snap_points(m, t, window):
    """Beat lines near t (for the timeline's magnet), only when 'Lock to beat' is on."""
    g = m.beat_grid
    return grid_times(g, t - window, t + window) if g["on"] else []


# ───────────────────────── mark editing (works on any mark set) ─────────────────────────
def add_mark(m, t, color=None, name=None, fps=None, snap=True):
    t = snap_time(m, t, fps) if snap else round(float(t), 3)
    if any(abs(x - t) < 1e-3 for x in m.markers): return t
    m.markers = sorted(m.markers + [t])
    if color: m.marker_colors[key(t)] = color
    if name: m.marker_names[key(t)] = name
    return t


def remove_mark(m, t):
    m.markers = [x for x in m.markers if abs(x - t) > 1e-3]; m.marker_names.pop(key(t), None); m.marker_colors.pop(key(t), None)


def toggle_mark(m, t, fps=None):
    """Add a mark at t (snapped); when one is already within half a frame, remove it. Returns True when added."""
    fps = fps or getattr(m, "fps", 30) or 30
    near = [x for x in m.markers if abs(x - t) < 0.5 / fps]
    if near:
        for x in near: remove_mark(m, x)
        return False
    add_mark(m, t, fps=fps); return True


def move_mark(m, old, new, fps=None):
    """Move one mark (its name and colour go with it). Returns the final time."""
    new = max(0.0, snap_time(m, new, fps)); k0 = key(old); nm = m.marker_names.pop(k0, None); col = m.marker_colors.pop(k0, None)
    m.markers = sorted([x for x in m.markers if abs(x - old) > 1e-3 and abs(x - new) > 1e-3] + [new])
    if nm: m.marker_names[key(new)] = nm
    if col: m.marker_colors[key(new)] = col
    return new


def set_color(m, t, color):
    if color: m.marker_colors[key(t)] = color
    else: m.marker_colors.pop(key(t), None)


def color_of(m, t): return m.marker_colors.get(key(t)) or MARK_DEFAULT


def clear_marks(m): m.markers = []; m.marker_names = {}; m.marker_colors = {}


def neighbour(m, t, direction, eps=0.01):
    ms = sorted(m.markers)
    return next((x for x in reversed(ms) if x < t - eps), None) if direction < 0 else next((x for x in ms if x > t + eps), None)


# ───────────────────────── audio analysis ─────────────────────────
class Analysis:
    """Per-frame features of a piece of sound. hop = seconds between frames."""
    def __init__(self, hop, flux, rms, centroid, t0=0.0):
        self.hop = hop; self.flux = flux; self.rms = rms; self.centroid = centroid; self.t0 = t0; self.n = len(rms); self.tempo = None
    def time(self, i): return self.t0 + i * self.hop
    def frame(self, t): return int(max(0, min(self.n - 1, round((t - self.t0) / self.hop))))


def to_mono(a):
    a = np.asarray(a)
    if a.ndim == 2: a = a.mean(axis=1)
    if a.dtype.kind == "i": a = a.astype(np.float32) / 32768.0
    return np.ascontiguousarray(a, dtype=np.float32)


def analyze(sound, sr, t0=0.0, win=1024, hop=512, progress=None):
    """Spectral flux of the whole band and of three bands (bass < 200 Hz, mid 200 Hz - 2 kHz, high > 2 kHz), loudness and brightness."""
    x = to_mono(sound)
    if len(x) < win * 2: x = np.pad(x, (0, win * 2 - len(x)))
    n = 1 + (len(x) - win) // hop; w = np.hanning(win).astype(np.float32); fr = np.fft.rfftfreq(win, 1.0 / sr)
    bands = {"all": (fr >= 30) & (fr <= 12000), "bass": (fr >= 30) & (fr < 200), "mid": (fr >= 200) & (fr < 2000), "high": (fr >= 2000) & (fr <= 12000)}
    flux = {k: np.zeros(n, np.float32) for k in bands}; rms = np.zeros(n, np.float32); cen = np.zeros(n, np.float32); prev = None; CH = 1500
    for s in range(0, n, CH):
        e = min(n, s + CH); idx = (np.arange(s, e)[:, None] * hop + np.arange(win)[None, :])
        seg = x[idx]; rms[s:e] = np.sqrt((seg ** 2).mean(axis=1)); mag = np.abs(np.fft.rfft(seg * w, axis=1)); lm = np.log1p(mag * 30.0)
        cen[s:e] = (mag * fr[None, :]).sum(axis=1) / (mag.sum(axis=1) + 1e-9)
        lm_p = np.vstack([lm[:1] if prev is None else prev[None, :], lm[:-1]]); d = np.maximum(0.0, lm - lm_p)
        for k, sel in bands.items(): flux[k][s:e] = d[:, sel].sum(axis=1)
        prev = lm[-1]
        if progress: progress(e / n)
    a = Analysis(hop / float(sr), {k: _norm(v) for k, v in flux.items()}, rms, cen, t0); a.tempo = detect_tempo(a); return a


def _norm(v):
    v = np.asarray(v, np.float32); hi = float(np.percentile(v, 99.5)) if len(v) else 1.0
    return np.clip(v / (hi + 1e-9), 0, 1.5).astype(np.float32)


def _smooth(v, n):
    if n <= 1: return v
    k = np.hanning(n * 2 + 1); k /= k.sum(); return np.convolve(v, k, mode="same")


def detect_tempo(a, lo=70.0, hi=180.0):
    """(bpm, offset seconds, confidence 0..1) from the flux: autocorrelation for the rough tempo, then a fine search of tempo + phase."""
    f = _smooth(a.flux["all"].astype(np.float64), 2); f = f - _smooth(f, int(0.5 / a.hop))
    if len(f) < int(2.0 / a.hop): return (120.0, 0.0, 0.0)
    nfft = 1 << int(np.ceil(np.log2(len(f) * 2))); F = np.fft.rfft(f, nfft); ac = np.fft.irfft(F * np.conj(F))[:len(f)]; ac /= (ac[0] + 1e-9)
    lags = np.arange(len(ac)) * a.hop; bpms = np.where(lags > 0, 60.0 / np.maximum(lags, 1e-9), 0)
    sel = (bpms >= lo) & (bpms <= hi)
    if not sel.any(): return (120.0, 0.0, 0.0)
    pri = np.exp(-0.5 * (np.log2(np.maximum(bpms, 1e-6) / 120.0) / 0.9) ** 2); sc = np.where(sel, ac * pri, -1e9); i = int(np.argmax(sc))
    if 0 < i < len(ac) - 1:
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]; den = y0 - 2 * y1 + y2; i = i + (0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0)
    bpm0 = 60.0 / (i * a.hop); fs = _smooth(a.flux["all"].astype(np.float64), 1); dur = len(fs) * a.hop; tt = np.arange(len(fs)) * a.hop
    best = (-1.0, bpm0, 0.0); tot = float(fs.sum()) + 1e-9
    for bpm in np.arange(bpm0 * 0.97, bpm0 * 1.03 + 1e-9, max(0.02, bpm0 * 0.0006)):
        per = 60.0 / bpm; offs = np.arange(0, per, a.hop)[:, None]; beats = offs + per * np.arange(0, int(dur / per) + 1)[None, :]
        beats = np.where(beats < dur, beats, dur - 1e-3); sc2 = np.interp(beats, tt, fs).sum(axis=1); j = int(np.argmax(sc2))
        if sc2[j] > best[0]: best = (float(sc2[j]), float(bpm), float(offs[j, 0]))
    bpm, off = best[1], best[2]; per = 60.0 / bpm; n_beats = max(1, int(dur / per)); conf = float(np.clip((best[0] / n_beats) / (tot / len(fs)) / 4.0, 0, 1))
    return (round(bpm, 2), round(a.t0 + off, 3), conf)


def _peaks(env, hop, sens, min_gap):
    """Local maxima of env above a moving threshold (mean + k*std over ~0.6 s). sens 0..100: higher = more marks."""
    k = 2.2 - 2.0 * (sens / 100.0); w = max(3, int(0.6 / hop)); sm = _smooth(env.astype(np.float64), 1)
    mean = _smooth(sm, w); var = _smooth((sm - mean) ** 2, w); thr = mean + k * np.sqrt(var) + 0.04 + (1.0 - sens / 100.0) * 0.08
    cand = np.where((sm[1:-1] > sm[:-2]) & (sm[1:-1] >= sm[2:]) & (sm[1:-1] > thr[1:-1]))[0] + 1; out = []; gap = max(1, int(min_gap / hop))
    for i in cand[np.argsort(-sm[cand])] if len(cand) else []:
        if all(abs(i - j) >= gap for j in out): out.append(int(i))
    return sorted(out)


def color_for(a, i, strength=1.0):
    """Colour of a sound hit from which band it hits: bass = red / orange, mid = yellow / green, high = cyan / blue / violet.
    Loud hits are vivid, quiet ones pale."""
    sl = slice(max(0, i - 2), i + 3); wb, wm, wh = [float(a.flux[k][sl].max()) + 1e-3 for k in ("bass", "mid", "high")]; tot = wb + wm + wh
    hue = (wb * 0.00 + wm * 0.30 + wh * 0.62) / tot; s = 0.35 + 0.6 * float(np.clip(strength, 0, 1)); v = 0.85 + 0.15 * float(np.clip(strength, 0, 1))
    r, g, b = colorsys.hsv_to_rgb(hue, s, v); return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def find_marks(a, mode="all", sens=50, min_gap=0.12, lock=False, grid=None, div=1.0, by_sound=True, fixed_color=MARK_DEFAULT, t_from=None, t_to=None):
    """[(time, colour)] for the sound. mode 'beats' = the steady beat grid; 'all' / 'bass' / 'mid' / 'high' = hits of that band.
    lock=True moves every hit to the nearest beat line (and drops duplicates), so the marks sit exactly on the rhythm."""
    lo = a.t0 if t_from is None else t_from; hi = a.t0 + a.n * a.hop if t_to is None else t_to; g = clean_grid(grid) if grid else None
    if mode == "beats":
        bpm, off, _ = a.tempo or (120.0, 0.0, 0.0); gg = g if g else clean_grid({"bpm": bpm, "offset": off, "div": div}); ts = grid_times(dict(gg, div=div), lo, hi); out = []
        for t in ts:
            i = a.frame(t); st = float(a.flux["all"][max(0, i - 2): i + 3].max()) if a.n else 1.0; out.append((round(t, 3), color_for(a, i, min(1.0, st)) if by_sound else fixed_color))
        return out
    env = a.flux.get(mode, a.flux["all"]); idx = _peaks(env, a.hop, sens, min_gap); out = []; seen = set()
    for i in idx:
        t = a.time(i)
        if t < lo or t > hi: continue
        if lock and g: t = nearest_beat(dict(g, div=div), t)
        t = round(t, 3)
        if t in seen: continue
        seen.add(t); st = float(env[max(0, i - 1): i + 2].max()); out.append((t, color_for(a, i, min(1.0, st)) if by_sound else fixed_color))
    return out


def apply_found(m, found, replace=False, names=None, fps=None):
    if replace: clear_marks(m)
    n = 0
    for t, col in found:
        if not any(abs(x - t) < 1e-3 for x in m.markers): m.markers.append(t); n += 1
        m.marker_colors[key(t)] = col
        if names: m.marker_names[key(t)] = names
    m.markers = sorted(m.markers); return n


def recolor_by_sound(m, a):
    """Give every mark the colour of the sound under it."""
    for t in m.markers: i = a.frame(t); m.marker_colors[key(t)] = color_for(a, i, min(1.0, float(a.flux["all"][max(0, i - 1): i + 3].max())))

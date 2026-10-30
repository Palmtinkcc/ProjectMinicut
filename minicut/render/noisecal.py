"""Auto adjust for the noise filters: from the loudness graph of a clip and the level the user draws as "this is noise",
work out sensible settings for Denoise, Noise gate and Hiss remover."""
from ..shared.deps import *
from ..shared.core import *
from .media import AUDIO

HOP = SR // 100                  # one level value every 10 ms
DB_FLOOR = -90.0


def clip_mono(c):
    """The sound of the part of the file that the clip plays (before any filter), mono, -1..1. None when it has no sound."""
    data = AUDIO.load(c["path"])
    if data is None or not len(data): return None
    i0 = max(0, int(c["inp"] * SR)); i1 = min(len(data), int(max(src_time(c, c["dur"]), c["inp"] + 0.05) * SR))
    seg = np.asarray(data[i0:i1], np.float32)
    if seg.ndim == 2: seg = seg.mean(axis=1)
    return seg / 32768.0 if len(seg) >= HOP * 4 else None


def levels_db(mono):
    """Loudness (RMS, dB) of every 10 ms."""
    n = len(mono) // HOP
    rms = np.sqrt(np.mean(mono[: n * HOP].reshape(n, HOP) ** 2, axis=1))
    return np.maximum(20 * np.log10(rms + 1e-6), DB_FLOOR)


def guess_noise_db(db):
    """First guess of the noise level: a little above the quietest tenth of the clip."""
    return float(np.clip(round(np.percentile(db, 10) + 3), -85, -12))


def _spectrum(mono, starts, n=2048):
    win = np.hanning(n).astype(np.float32); acc = np.zeros(n // 2 + 1, np.float64); k = 0
    for s in starts:
        seg = mono[s * HOP: s * HOP + n]
        if len(seg) == n: acc += np.abs(np.fft.rfft(seg * win)); k += 1
    return acc / max(1, k)


def analyze(mono, db, thr):
    """Numbers about the clip for a noise level thr (dB): how far the speech is above it, and where the noise lives in frequency."""
    noise = np.nonzero(db < thr)[0]; sig = np.nonzero(db >= thr + 6)[0]
    speech = float(np.percentile(db[db >= thr], 90)) if np.any(db >= thr) else thr + 20.0
    snr = max(0.0, speech - thr); cutoff = 5000.0
    if len(noise) >= 3 and len(sig) >= 3:
        pick = lambda ix: ix[np.linspace(0, len(ix) - 1, min(80, len(ix))).astype(int)]
        ns = _spectrum(mono, pick(noise)); ss = _spectrum(mono, pick(sig))
        ratio = np.convolve(ns / np.maximum(ss, 1e-9), np.ones(9) / 9, mode="same"); fr = np.fft.rfftfreq(2048, 1.0 / SR)
        for f in np.arange(1000, 12001, 250):
            m = (fr >= f) & (fr <= 16000)
            if np.median(ratio[m]) > 0.15: cutoff = float(f); break
    return {"speech_db": speech, "snr": snr, "cutoff": cutoff, "noise_share": float(len(noise)) / max(1, len(db))}


def auto_params(etype, thr, an):
    """The settings that go with the chosen noise level."""
    snr = an["snr"]; amount = float(np.clip(100 - 1.5 * snr, 35, 90))
    if etype == "denoise": return {"noise_db": float(thr), "amount": round(amount), "floor": 5 if snr >= 20 else 8}
    if etype == "gate": return {"threshold": float(np.clip(thr + 3, -80, -10)), "reduction": round(float(np.clip(snr * 0.8, 12, 60))), "attack": 8, "release": 200}
    if etype == "hiss": return {"cutoff": round(float(np.clip(an["cutoff"], 1000, 16000)), -2), "amount": round(amount)}
    return {}

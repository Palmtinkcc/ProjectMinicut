"""Audio mixing, streaming playback and the level meter state."""
from ..shared.deps import *
from ..shared.core import *
from .media import *
from .nodegraph import *
from .afx import *
from .speed import *


METER = {"l": 0.0, "r": 0.0, "t": 0.0}      # latest audio peak (0..1), filled by the audio stream


def mix_audio(proj, t0, t1, sr=SR, wait=False):
    proj = flatten_compounds(proj)
    n = max(0, int((t1 - t0) * sr)); out = np.zeros((n, 2), np.float32)
    for c in proj.clips:
        if c["kind"] not in ("video", "audio"): continue
        tr = proj.track(c["track"])
        if tr is None or tr["muted"]: continue
        a = max(t0, c["start"]); b = min(t1, c["start"] + c["dur"])
        if b <= a: continue
        data = audio_data_for(c, wait)     # clean audio, or the audio with the clip's audio effects when it is ready
        if data is None: continue
        if clip_has_speed(c): seg = speed_piece(c, data, a - c["start"], b - a, sr, wait)         # faster / slower media
        else:
            s0 = int((c["inp"] + a - c["start"]) * sr); seg = data[max(0, s0): max(0, s0) + int((b - a) * sr)]
        if not len(seg): continue
        o = int((a - t0) * sr); la = a - c["start"]
        drv = node_drives(proj, c, "volume")
        if c["props"]["volume"]["k"] or drv:
            times = np.linspace(la, la + len(seg) / sr, max(2, len(seg) // 441 + 2))
            vols = np.array([prop_at(node_apply(proj, c, c["start"] + tt) if drv else c, "volume", tt) for tt in times]) / 100
            env = np.interp(la + np.arange(len(seg)) / sr, times, vols).astype(np.float32)[:, None]
        else: env = c["props"]["volume"]["v"] / 100
        m = min(len(seg), n - o)
        if m > 0: out[o:o + m] += (seg[:m].astype(np.float32) / 32768.0) * (env[:m] if isinstance(env, np.ndarray) else env)
    return np.clip(out, -1, 1)


class AudioStream(QIODevice):
    def __init__(self):
        super().__init__(); self.proj = None; self.pos = 0.0
    def set(self, proj, t): self.proj = proj; self.pos = float(t)
    def readData(self, maxlen):
        n = min(int(maxlen) // 4, int(SR * 0.1))
        if n <= 0: return b""
        proj, t0 = self.proj, self.pos; self.pos = t0 + n / SR
        if proj is None: return bytes(n * 4)
        try:
            d = mix_audio(proj, t0, t0 + n / SR)
            if d.shape[0] < n: d = np.vstack([d, np.zeros((n - d.shape[0], 2), np.float32)])
            d = np.clip(d[:n], -1, 1)
            METER["l"] = float(np.abs(d[:, 0]).max()); METER["r"] = float(np.abs(d[:, 1]).max()); METER["t"] = time.monotonic()   # level meter
            return (d * 32767).astype("<i2").tobytes()
        except Exception as ex:
            print("audio:", ex); return bytes(n * 4)
    def writeData(self, data): return 0
    def bytesAvailable(self): return 1 << 24
    def isSequential(self): return True


class AudioPlayer:
    LATENCY = 0.03            # ถ้ารู้สึกว่าภาพนำเสียง ให้เพิ่มค่านี้ (วินาที)
    def __init__(self):
        self.sink = None; self.stream = None; self.running = False; self.start_t = 0.0; self._wall = time.monotonic()
        if HAS_AUDIO:
            try:
                fmt = QAudioFormat(); fmt.setSampleRate(SR); fmt.setChannelCount(2)
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16); self.fmt = fmt
                self.stream = AudioStream(); self.stream.open(QIODevice.ReadOnly)
                self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt)
                self.sink.setBufferSize(int(SR * 4 * 0.15))
            except Exception as ex:
                print("audio init:", ex); self.sink = None
    @property
    def active(self): return self.running
    def start(self, proj, t, length=None):
        self.start_t = float(t); self.running = True
        if self.sink is not None:
            self.sink.stop()
            if not self.stream.isOpen(): self.stream.open(QIODevice.ReadOnly)
            self.stream.set(proj, t); self.sink.start(self.stream)
        self._wall = time.monotonic()
    def stop(self):
        self.running = False
        if self.sink is not None: self.sink.stop()
    def clock(self):
        return self.start_t + max(0.0, time.monotonic() - self._wall - self.LATENCY)

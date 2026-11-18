"""Sound of a Bone2D animation (Patch 44): a reference sound taken from the main timeline so a puppet can be animated in sync with it.

The sound is a stereo wav next to the rig file (<rig>_audio/<id>.wav, made from the mix of a part of the main timeline) and
anim["audio"] = {"file": path relative to the rig file, "name", "src_t0": where on the main timeline it came from, "dur", "offset", "gain", "mute"}.
It is only a guide while animating (sheet waveform, playback in the Bone2D page, Auto mark); it is not part of the clip's own sound."""
from ..shared.deps import *
from ..shared.core import SR

_CACHE = OrderedDict()      # wav path -> (mtime, float32 stereo (n, 2), peaks)
PEAK_RATE = 200             # peaks per second kept for the sheet waveform


def audio_of(anim):
    a = anim.get("audio") if isinstance(anim, dict) else None
    return a if isinstance(a, dict) and a.get("file") else None


def wav_path(rig_path, a): return os.path.join(os.path.dirname(os.path.abspath(rig_path)), a["file"])


def audio_folder(rig_path): return os.path.splitext(os.path.abspath(rig_path))[0] + "_audio"


def write_wav(path, data, sr=SR):
    """data: float32 (n, 2) in -1..1."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes(); raw = w.readframes(n)
    if sw != 2: raise ValueError("16-bit wav expected")
    d = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0; d = d.reshape(-1, ch)
    if ch == 1: d = np.repeat(d, 2, axis=1)
    return d[:, :2].copy(), sr


def _peaks(d, sr):
    mono = np.abs(d).max(axis=1) if len(d) else np.zeros(1, np.float32); step = max(1, int(sr / PEAK_RATE)); n = len(mono) // step
    return mono[:n * step].reshape(n, step).max(axis=1) if n else np.zeros(1, np.float32)


def load(rig_path, a):
    """(float32 stereo (n, 2), peaks at PEAK_RATE per second) of the sound of an animation, or None when the file is gone."""
    p = wav_path(rig_path, a)
    try: mt = os.path.getmtime(p)
    except OSError: return None
    c = _CACHE.get(p)
    if c is None or c[0] != mt:
        try: d, sr = read_wav(p)
        except Exception as ex: print("rig audio:", ex); return None
        _CACHE[p] = c = (mt, d, _peaks(d, sr)); _CACHE.move_to_end(p)
        while len(_CACHE) > 4: _CACHE.popitem(last=False)
    return c[1], c[2]


def pull_from_project(proj, t0, length, clips=None, wait=True):
    """The sound of the main timeline from t0 for `length` seconds as float32 (n, 2). clips = only these clips (None = everything)."""
    from .audio import mix_audio
    p2 = copy.copy(proj)
    if clips is not None: p2.clips = list(clips)
    return mix_audio(p2, float(t0), float(t0) + float(length), SR, wait)


def forget(path): _CACHE.pop(path, None)


# ───────────────────────── playback ─────────────────────────
class _ArrayStream(QIODevice):
    def __init__(self): super().__init__(); self.data = None; self.pos = 0; self.gain = 1.0
    def set(self, data, start_sample, gain): self.data = data; self.pos = int(start_sample); self.gain = float(gain)
    def readData(self, maxlen):
        n = min(int(maxlen) // 4, int(SR * 0.1))
        if n <= 0: return b""
        out = np.zeros((n, 2), np.float32); d = self.data; p0 = self.pos; self.pos = p0 + n
        if d is not None:
            a = max(0, p0); b = min(len(d), p0 + n)
            if b > a: out[a - p0: b - p0] = d[a:b]
        return (np.clip(out * self.gain, -1, 1) * 32767).astype("<i2").tobytes()
    def writeData(self, data): return 0
    def bytesAvailable(self): return 1 << 24
    def isSequential(self): return True


class RigAudioPlayer:
    """Plays the sound of an animation from a given animation time. Does nothing when the machine has no audio output."""
    def __init__(self):
        self.sink = None; self.stream = None
        if HAS_AUDIO:
            try:
                fmt = QAudioFormat(); fmt.setSampleRate(SR); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                self.stream = _ArrayStream(); self.stream.open(QIODevice.ReadOnly)
                self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt); self.sink.setBufferSize(int(SR * 4 * 0.1))
            except Exception as ex:
                print("rig audio init:", ex); self.sink = None
    def start(self, data, t, offset=0.0, gain=1.0):
        """t = animation time to start at; the sound begins at `offset` seconds of the animation."""
        if self.sink is None or data is None: return
        self.sink.stop()
        if not self.stream.isOpen(): self.stream.open(QIODevice.ReadOnly)
        self.stream.set(data, (t - offset) * SR, gain); self.sink.start(self.stream)
    def stop(self):
        if self.sink is not None: self.sink.stop()

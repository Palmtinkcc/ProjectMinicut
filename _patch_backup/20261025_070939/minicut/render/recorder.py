"""Voice recording into the project: the microphone is recorded to a WAV file in the asset folder (Recordings/)."""
from ..shared.deps import *
from ..shared.core import *

try:
    from PySide6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices
except Exception:
    QAudioSource = None


class VoiceRecorder(QObject):
    def __init__(self):
        super().__init__(); self.src = None; self.io = None; self.chunks = []; self.t0 = 0.0; self.rate = SR; self.ch = 2
        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self._pull)
    def active(self): return self.src is not None
    def seconds(self): return (time.monotonic() - self.t0) if self.src is not None else 0.0
    def start(self, folder):
        self.folder = folder
        if QAudioSource is None: raise RuntimeError("Recording needs QtMultimedia, which is not available here.")
        dev = QMediaDevices.defaultAudioInput()
        if dev.isNull(): raise RuntimeError("No microphone was found.")
        fmt = QAudioFormat(); fmt.setSampleRate(SR); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not dev.isFormatSupported(fmt): fmt = dev.preferredFormat(); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.rate = fmt.sampleRate(); self.ch = fmt.channelCount()
        self.src = QAudioSource(dev, fmt); self.chunks = []; self.io = self.src.start(); self.t0 = time.monotonic(); self.timer.start()
    def _pull(self):
        if self.io is None: return
        data = bytes(self.io.readAll())
        if data: self.chunks.append(data)
    def stop(self):
        """Finish the take. Returns the WAV path (stereo, 16 bit) or None if the take is too short."""
        if self.src is None: return None
        self.timer.stop(); self._pull(); self.src.stop(); self.src = None; self.io = None
        raw = b"".join(self.chunks); self.chunks = []
        frame = 2 * self.ch
        if len(raw) < frame * self.rate // 4: return None
        arr = np.frombuffer(raw[: len(raw) // frame * frame], "<i2").reshape(-1, self.ch)
        if self.ch == 1: arr = np.repeat(arr, 2, axis=1)
        folder = os.path.join(self.folder, "Recordings"); os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "voice_%s.wav" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(self.rate); w.writeframes(np.ascontiguousarray(arr[:, :2], "<i2").tobytes())
        return path

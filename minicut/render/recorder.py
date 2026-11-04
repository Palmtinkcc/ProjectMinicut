"""Voice recording into the project: the microphone is recorded to a WAV file in the asset folder (Recordings/).
While recording, the level of every 10 ms is kept (peaks), so the timeline can draw the sound as it is recorded."""
from ..shared.deps import *
from ..shared.core import *
from .audio import METER

try:
    from PySide6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices
except Exception:
    QAudioSource = None


def list_audio_inputs():
    """[(name, id)] of the microphones this PC has. The id is what Settings stores."""
    out = []
    if QAudioSource is None: return out
    try:
        for d in QMediaDevices.audioInputs(): out.append((d.description(), bytes(d.id()).decode("utf-8", "ignore")))
    except Exception: pass
    return out


def _find_input(device_id):
    """(device, found): the microphone with this id, else the system default."""
    if device_id:
        for d in QMediaDevices.audioInputs():
            if bytes(d.id()).decode("utf-8", "ignore") == device_id: return d, True
    return QMediaDevices.defaultAudioInput(), not device_id


class VoiceRecorder(QObject):
    PEAKS_PER_SEC = 100

    def __init__(self):
        super().__init__(); self.src = None; self.io = None; self.chunks = []; self.rate = SR; self.ch = 2; self.frames = 0
        self.fallback = False; self.device_name = ""; self._dt = np.dtype("<i2"); self._rest = b""; self._carry = np.zeros(0, np.float32)
        self.peaks = np.zeros(2048, np.float32); self.npk = 0
        self.timer = QTimer(self); self.timer.setInterval(25); self.timer.timeout.connect(self._pull)

    def active(self): return self.src is not None
    def seconds(self): return self.frames / float(self.rate or SR)
    def peaks_view(self): return self.peaks[: self.npk]

    def start(self, folder, device_id=""):
        self.folder = folder
        if QAudioSource is None: raise RuntimeError("Recording needs QtMultimedia, which is not available here.")
        dev, found = _find_input(device_id); self.fallback = bool(device_id) and not found
        if dev.isNull(): raise RuntimeError("No microphone was found.")
        want = QAudioFormat(); want.setSampleRate(SR); want.setChannelCount(2); want.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        fmt = next((f for f in (want, dev.preferredFormat()) if dev.isFormatSupported(f)), dev.preferredFormat())
        sf = fmt.sampleFormat(); SF = QAudioFormat.SampleFormat
        self._dt = np.dtype({SF.UInt8: "u1", SF.Int16: "<i2", SF.Int32: "<i4", SF.Float: "<f4"}.get(sf, "<i2"))
        if sf not in (SF.UInt8, SF.Int16, SF.Int32, SF.Float): fmt.setSampleFormat(SF.Int16)
        self.rate = fmt.sampleRate(); self.ch = max(1, fmt.channelCount()); self.device_name = dev.description()
        self.chunks = []; self.frames = 0; self._rest = b""; self._carry = np.zeros(0, np.float32); self.npk = 0
        self.src = QAudioSource(dev, fmt); self.io = self.src.start()
        if self.io is None:
            self.src = None; raise RuntimeError("The microphone could not be opened (is another program using it?).")
        self.timer.start()

    def _to_int16(self, arr):
        k = self._dt.kind; sz = self._dt.itemsize
        if k == "f": x = np.clip(arr, -1.0, 1.0) * 32767.0
        elif k == "u": x = (arr.astype(np.float32) - 128.0) * 256.0
        elif sz == 4: x = arr.astype(np.float32) / 65536.0
        else: return arr.astype(np.int16)
        return x.astype(np.int16)

    def _pull(self):
        if self.io is None: return
        data = self._rest + bytes(self.io.readAll())
        if not data: return
        frame = self._dt.itemsize * self.ch; n = len(data) // frame * frame
        self._rest = data[n:]
        if n == 0: return
        a = self._to_int16(np.frombuffer(data[:n], self._dt).reshape(-1, self.ch))
        if self.ch == 1: a = np.repeat(a, 2, axis=1)
        a = np.ascontiguousarray(a[:, :2]); self.chunks.append(a); self.frames += len(a)
        ab = np.abs(a.astype(np.int32))
        METER["l"] = float(ab[:, 0].max()) / 32768.0; METER["r"] = float(ab[:, 1].max()) / 32768.0; METER["t"] = time.monotonic()    # level meter
        hop = max(1, self.rate // self.PEAKS_PER_SEC)
        self._carry = np.concatenate([self._carry, ab.max(axis=1).astype(np.float32)]); k = len(self._carry) // hop
        if k:
            blk = self._carry[: k * hop].reshape(k, hop).max(axis=1) / 32768.0; self._carry = self._carry[k * hop:]
            if self.npk + k > len(self.peaks): self.peaks = np.concatenate([self.peaks, np.zeros(max(len(self.peaks), k), np.float32)])
            self.peaks[self.npk: self.npk + k] = blk; self.npk += k

    def _close(self):
        self.timer.stop(); self._pull()
        if self.src is not None: self.src.stop()
        self.src = None; self.io = None

    def discard(self):
        """Stop and throw the take away."""
        if self.src is None: return
        self._close(); self.chunks = []

    def stop(self):
        """Finish the take. Returns the WAV path (stereo, 16 bit) or None if the take is too short."""
        if self.src is None: return None
        self._close()
        arr = np.concatenate(self.chunks) if self.chunks else np.zeros((0, 2), np.int16); self.chunks = []
        if len(arr) < self.rate // 4: return None
        folder = os.path.join(self.folder, "Recordings"); os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "voice_%s.wav" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(self.rate); w.writeframes(np.ascontiguousarray(arr, "<i2").tobytes())
        return path

"""Previews, so nothing has to be tried blind: the effect gallery shows every effect applied to the picture on screen, and the
sound card shows the waveform of the clip and plays just that clip (with its effects) when you press Listen."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.ui import *
from ..render.effects import FX, FX_CATS, new_effect, apply_effects


def sample_frame(app, w=200):
    """A small BGRA picture to try effects on: what the viewport shows now, or a test card when it shows nothing."""
    img = getattr(getattr(app, "viewport", None), "img", None); arr = None
    if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[0] > 4: arr = img
    elif isinstance(img, QImage) and not img.isNull():
        q = img.convertToFormat(QImage.Format_RGBA8888); a = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine() // 4, 4)[:, :q.width()]
        arr = cv2.cvtColor(a.copy(), cv2.COLOR_RGBA2BGRA)
    if arr is None:
        h = int(w * 9 / 16); arr = np.zeros((h, w, 4), np.uint8); xs = np.linspace(0, 255, w, dtype=np.uint8)
        arr[..., 0] = xs[None, :]; arr[..., 1] = np.linspace(255, 40, h, dtype=np.uint8)[:, None]; arr[..., 2] = 255 - xs[None, :]; arr[..., 3] = 255
        cv2.circle(arr, (w // 2, h // 2), h // 3, (255, 255, 255, 255), -1); cv2.rectangle(arr, (8, 8), (w // 4, h // 3), (30, 30, 30, 255), -1)
    h0, w0 = arr.shape[:2]; s = w / float(w0); arr = cv2.resize(arr, (w, max(2, int(h0 * s))), interpolation=cv2.INTER_AREA)
    if arr.shape[2] == 3: arr = np.dstack([arr, np.full(arr.shape[:2], 255, np.uint8)])
    return np.ascontiguousarray(arr)


def bgra_pixmap(arr):
    rgba = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA); h, w = rgba.shape[:2]
    return QPixmap.fromImage(QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy())


def fx_preview(app, effects, base=None, w=200):
    """The sample picture with a list of effect layers applied."""
    base = sample_frame(app, w) if base is None else base; pw = app.proj.w if app.proj else 1920
    c = {"effects": effects, "kind": "video"}
    try: out = apply_effects(c, base.copy(), k=base.shape[1] / float(pw), lt=0.0, fast=True)
    except Exception as ex: print("[preview]", ex); out = base
    return bgra_pixmap(out)


# ========================================================= effect gallery ===============================================
class _Tile(QWidget):
    clicked = Signal(str)
    def __init__(self, typ, title, pm):
        super().__init__(); self.typ, self.title, self.pm = typ, title, pm; self.setFixedSize(148, 112); self.setCursor(Qt.PointingHandCursor); self._h = False; self.setMouseTracking(True)
    def enterEvent(self, e): self._h = True; self.update()
    def leaveEvent(self, e): self._h = False; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(c["accent"] if self._h else c["line"]), 1.5 if self._h else 1)); p.setBrush(QColor(c["field_h"] if self._h else c["field"])); p.drawRoundedRect(r, 9, 9)
        clip = QPainterPath(); clip.addRoundedRect(QRectF(5, 5, 138, 78), 6, 6); p.save(); p.setClipPath(clip)
        pm = self.pm.scaled(138, 78, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation); p.drawPixmap(5, 5, pm, (pm.width() - 138) // 2, (pm.height() - 78) // 2, 138, 78); p.restore()
        p.setPen(QColor(c["text"])); p.setFont(_f(12, True)); p.drawText(QRectF(8, 86, 132, 22), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.title, Qt.ElideRight, 130))
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.typ)


def _clamp(v, lo, hi): return max(lo, min(hi, v))


def _f(px, bold=False):
    f = QFont(QApplication.font()); f.setPixelSize(px); f.setBold(bold); return f


class EffectPicker(QFrame):
    """Popup with every effect as a picture of itself on your current frame. Click one to add it."""
    picked = Signal(str)
    def __init__(self, app, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint); self.setAttribute(Qt.WA_DeleteOnClose); c = pal()
        self.setStyleSheet("QFrame#Pick{background:%s;border:1px solid %s;border-radius:12px;}" % (c["card"], c["line"])); self.setObjectName("Pick")
        v = QVBoxLayout(self); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(6); head = QHBoxLayout(); t = label("Choose an effect", False, 14); t.setStyleSheet(t.styleSheet() + "font-weight:700;"); head.addWidget(t); head.addStretch(); v.addLayout(head)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setStyleSheet("background:transparent;"); host = QWidget(); host.setStyleSheet("background:transparent;"); hv = QVBoxLayout(host); hv.setContentsMargins(0, 0, 4, 0); hv.setSpacing(8)
        base = sample_frame(app, 200)
        for cat in FX_CATS:
            l = label(cat.upper(), True, 11); l.setStyleSheet(l.styleSheet() + "font-weight:700;letter-spacing:1px;"); hv.addWidget(l); g = QGridLayout(); g.setSpacing(8); i = 0
            for typ, sp in FX.items():
                if sp["cat"] != cat: continue
                pm = fx_preview(app, [new_effect(typ)], base); t = _Tile(typ, sp["title"], pm); t.clicked.connect(self._pick); g.addWidget(t, i // 2, i % 2); i += 1
            hv.addLayout(g)
        hv.addStretch(); sa.setWidget(host); v.addWidget(sa); self.setFixedSize(350, 520)
    def _pick(self, typ): self.picked.emit(typ); self.close()


# ========================================================= sound ========================================================
class WaveView(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self.cid = None; self.pos = None; self.setFixedHeight(84)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = QRectF(self.rect())
        p.setPen(Qt.NoPen); p.setBrush(QColor("#17171b")); p.drawRoundedRect(r, 9, 9)
        clip = self.app.sel_clip()
        if not clip: return
        gain = float(self.app.settings["waveform_gain"]); n = max(8, int(r.width() / 3)); mid = r.center().y(); amp = r.height() / 2 - 8; lines = []
        peaks = None
        if clip["kind"] in ("audio", "video") and clip.get("path"): peaks = self.app.thumbs.wave(clip["path"])
        for i in range(n):
            lt = src_time(clip, clip["dur"] * (i + .5) / n)
            if clip["kind"] == "compound": a = self.app.timeline._compound_amp(clip, lt, gain)
            elif peaks is not None and len(peaks):
                idx = int(lt * 100); a = min(1.0, peaks[idx] * gain) if 0 <= idx < len(peaks) else 0.0
            else: a = 0.0
            a = max(1.0, a * amp); x = r.left() + 6 + (r.width() - 12) * i / n; lines.append(QLineF(x, mid - a, x, mid + a))
        p.setPen(QPen(QColor(c["accent"]), 2, Qt.SolidLine, Qt.RoundCap)); p.drawLines(lines)
        if peaks is None and clip["kind"] != "compound": p.setPen(QColor(c["dim"])); p.setFont(_f(12)); p.drawText(r, Qt.AlignCenter, "Reading the sound…")
        if self.pos is not None:
            x = r.left() + 6 + (r.width() - 12) * _clamp(self.pos, 0, 1); p.setPen(QPen(QColor("#ffffff"), 2)); p.drawLine(QPointF(x, r.top() + 4), QPointF(x, r.bottom() - 4))


class SoundPreview(Section):
    """The sound of the selected clip: its waveform, and a Listen button that plays only this clip (effects included)."""
    def __init__(self, app):
        super().__init__("Sound", "sound"); self.app = app; self.cid = None; self.listening = False
        self.wave = WaveView(app); self.body.addWidget(self.wave)
        r = QHBoxLayout(); self.btn = Btn("Listen", "play", "accent", "Play only this clip, with its sound effects", self.toggle); r.addWidget(self.btn); r.addStretch(); self.body.addLayout(r)
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._tick); self._wt = QTimer(self); self._wt.setInterval(500); self._wt.timeout.connect(self.wave.update)
    def load(self, c):
        self.setVisible(c is not None and c.get("kind") in ("audio", "video", "compound"))
        if c is None or c["id"] != self.cid:
            self.stop(); self.cid = c["id"] if c else None
        self.wave.update()
        if self.isVisible() and not self._wt.isActive(): self._wt.start()
    def toggle(self):
        if self.listening: self.stop(); return
        c = self.app.sel_clip()
        if c is None: return
        if self.app.playing: self.app.stop_play()
        shim = copy.copy(self.app.proj); shim.clips = [c]; t0 = c["start"] if not (c["start"] <= self.app.t < c["start"] + c["dur"] - 0.1) else self.app.t
        self._end = c["start"] + c["dur"]; self._t0 = t0; self.app.audio.start(shim, t0); self.listening = True; self.btn.label = "Stop"; self.btn.setIconName("stop"); self.btn.update(); self.timer.start()
    def stop(self):
        if self.listening:
            self.app.audio.stop()
        self.listening = False; self.timer.stop(); self.wave.pos = None; self.btn.label = "Listen"; self.btn.setIconName("play"); self.btn.update(); self.wave.update()
    def _tick(self):
        c = self.app.sel_clip()
        if c is None: self.stop(); return
        now = self.app.audio.clock()
        if now >= self._end: self.stop(); return
        self.wave.pos = (now - c["start"]) / max(0.01, c["dur"]); self.wave.update()

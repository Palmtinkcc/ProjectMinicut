"""Auto adjust window for the noise filters: the loudness of the clip is drawn over time and one horizontal line says
how loud the noise is. Drag the line up and down (everything under it is noise) and press Apply: the filter is set to match."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.ui import *
from ..render.noisecal import *

NAMES = {"denoise": "Denoise", "gate": "Noise gate", "hiss": "Hiss remover"}


class NoiseGraph(QWidget):
    moved = Signal(float)
    TOP, BOT = -6.0, -90.0
    def __init__(self, db, thr):
        super().__init__(); self.db = db; self.thr = thr; self._drag = False; self.setMinimumSize(620, 250); self.setMouseTracking(True); self.setCursor(Qt.SizeVerCursor)
    def _plot(self): return QRectF(46, 12, self.width() - 60, self.height() - 34)
    def _y(self, db): r = self._plot(); return r.bottom() - (db - self.BOT) / (self.TOP - self.BOT) * r.height()
    def _db(self, y): r = self._plot(); return self.BOT + (r.bottom() - y) / r.height() * (self.TOP - self.BOT)
    def setThr(self, v): self.thr = float(np.clip(v, -85, -12)); self.update(); self.moved.emit(self.thr)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = self._plot()
        p.setPen(Qt.NoPen); p.setBrush(QColor("#17171b")); p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.setFont(QFont(QApplication.font().family(), 8))
        for d in range(-10, -90, -10):
            y = self._y(d); p.setPen(QPen(QColor(255, 255, 255, 22), 1)); p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(c["dim"])); p.drawText(QRectF(0, y - 8, 40, 16), Qt.AlignRight | Qt.AlignVCenter, "%d dB" % d)
        n = len(self.db)
        if n:
            cols = int(r.width()); idx = np.linspace(0, n, cols + 1).astype(int); loud = np.array([self.db[a:max(b, a + 1)].max() for a, b in zip(idx[:-1], idx[1:])])
            for i, v in enumerate(loud):
                x = r.left() + i; y = self._y(max(v, self.BOT)); noise = v < self.thr
                p.setPen(QPen(QColor(255, 107, 107, 190) if noise else QColor(c["accent"]), 1)); p.drawLine(QPointF(x, r.bottom()), QPointF(x, y))
        ty = self._y(self.thr); p.fillRect(QRectF(r.left(), ty, r.width(), r.bottom() - ty), QColor(255, 107, 107, 28))
        p.setPen(QPen(QColor("#ffd24a"), 2)); p.drawLine(QPointF(r.left() - 4, ty), QPointF(r.right(), ty)); p.setBrush(QColor("#ffd24a")); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(r.right() - 26, ty - 8, 26, 16), 4, 4); p.setPen(QColor("#1a1a1a")); p.drawText(QRectF(r.right() - 26, ty - 8, 26, 16), Qt.AlignCenter, "\u21c5")
        p.setPen(QColor(c["dim"])); p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, "start of the clip")
        p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 16), Qt.AlignRight | Qt.AlignVCenter, "end")
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag = True; self.setThr(self._db(e.position().y()))
    def mouseMoveEvent(self, e):
        if self._drag: self.setThr(self._db(e.position().y()))
    def mouseReleaseEvent(self, e): self._drag = False


class NoiseDialog(QDialog):
    """exec(); then .params holds the settings to apply (or None)."""
    def __init__(self, parent, clip, etype):
        super().__init__(parent); self.setWindowTitle("Auto adjust \u2013 " + NAMES.get(etype, etype)); self.etype = etype; self.params = None; self.setModal(True)
        self.mono = clip_mono(clip); v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)
        if self.mono is None:
            v.addWidget(label("This clip has no sound that can be analysed.", False, 13)); b = Btn("Close", None, "soft", "", self.reject); v.addWidget(b); self.graph = None; return
        self.db = levels_db(self.mono); thr = guess_noise_db(self.db)
        intro = label("Drag the yellow line up or down: everything under the line (red) is noise that you want to remove, "
                      "everything above it is sound you want to keep. MiniCut then sets the filter to fit.", True, 12); intro.setWordWrap(True); v.addWidget(intro)
        self.graph = NoiseGraph(self.db, thr); v.addWidget(self.graph); self.info = QLabel(""); self.info.setStyleSheet("color:#ececf1;font-size:12px;"); self.info.setWordWrap(True); v.addWidget(self.info)
        row = QHBoxLayout(); row.addStretch(); self.auto = Btn("Guess it", None, "soft", "Put the line where the quiet parts of the clip are", lambda: self.graph.setThr(guess_noise_db(self.db)))
        cancel = Btn("Cancel", None, "soft", "", self.reject); ok = Btn("Apply", None, "accent", "Set the filter", self.accept); [row.addWidget(b) for b in (self.auto, cancel, ok)]; v.addLayout(row)
        self.graph.moved.connect(self._refresh); self._refresh(thr)
    def _refresh(self, thr):
        an = analyze(self.mono, self.db, thr); self.an = an; self.params = auto_params(self.etype, thr, an); P = self.params
        txt = {"denoise": "Noise level %(noise_db).0f dB \u00b7 Amount %(amount)d %% \u00b7 Floor %(floor)d %%", "gate": "Opens above %(threshold).0f dB \u00b7 Reduce by %(reduction)d dB",
               "hiss": "Hiss reduced from %(cutoff).0f Hz \u00b7 Amount %(amount)d %%"}.get(self.etype, "") % P
        self.info.setText("%.0f %% of the clip is under the line.   The filter will be set to:  %s" % (an["noise_share"] * 100, txt))
    def accept(self):
        if self.graph is None: self.reject(); return
        super().accept()
    def reject(self): self.params = None; super().reject()

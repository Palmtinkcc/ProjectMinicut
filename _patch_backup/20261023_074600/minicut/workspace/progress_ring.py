"""Progress ring at the bottom right of the window: shows the background work that is running."""
import time
from ..shared.deps import *
from ..shared.tasks import TASKS
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMessageBox

RING_ACCENT = "#2fb6ff"      # the blue arc (fixed colour, so it is visible in every theme)
RING_TRACK = "#3a4150"


class ProgressRing(QWidget):
    def __init__(self, parent):
        super().__init__(parent); self.setFixedSize(46, 46); self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)   # no square behind the ring
        self.shown = []; self.hide()
        self.timer = QTimer(self); self.timer.setInterval(120); self.timer.timeout.connect(self._poll); self.timer.start()
    def _poll(self):
        self.shown = TASKS.snapshot()
        self.setVisible(bool(self.shown))
        if self.shown:
            lines = []
            for t in self.shown:
                f = t.fraction()
                pct = ("%d%%" % round(f * 100)) if f is not None else "starting…"
                lines.append("%s   %s%s" % (t.title, pct, ("   " + t.detail) if t.detail else ""))
            self.setToolTip("\n".join(lines))
        self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(6, 6, 34, 34)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(RING_TRACK), 4)); p.drawEllipse(r)
        if not self.shown: return
        t = self.shown[-1]; f = t.fraction()
        p.setPen(QPen(QColor(RING_ACCENT), 4, Qt.SolidLine, Qt.RoundCap))
        if f is None:                                  # not known yet: a turning arc
            start = int((time.monotonic() * 360 * 1.5) % 360); p.drawArc(r, start * 16, -110 * 16)
        else:
            p.drawArc(r, 90 * 16, -max(1, int(f * 360 * 16)))
        p.setPen(QColor("#dfe3ea")); font = QFont(p.font()); font.setPointSize(max(7, font.pointSize() - 2)); p.setFont(font)
        label = str(len(self.shown)) if len(self.shown) > 1 else ("%d" % round(f * 100) if f is not None else "")
        p.drawText(self.rect(), Qt.AlignCenter, label)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.shown:
            QMessageBox.information(self.window(), "MiniCut: working on", self.toolTip())


class _Placer(QObject):
    def __init__(self, ring):
        super().__init__(); self.ring = ring
    def place(self, main):
        self.ring.move(main.width() - self.ring.width() - 16, main.height() - self.ring.height() - 16); self.ring.raise_()
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize: self.place(obj)
        return False


def install_progress(main):
    ring = ProgressRing(main); pl = _Placer(ring); main._progress_placer = pl
    main.installEventFilter(pl); pl.place(main); return ring

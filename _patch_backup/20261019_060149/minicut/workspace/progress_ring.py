"""Progress ring at the bottom right of the window: shows the background work that is running."""
import time
from ..shared.deps import *
from ..shared.tasks import TASKS
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMessageBox


class ProgressRing(QWidget):
    def __init__(self, parent):
        super().__init__(parent); self.setFixedSize(46, 46); self.setCursor(Qt.PointingHandCursor)
        self.shown = []; self.hide()
        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self._poll); self.timer.start()
    def _poll(self):
        self.shown = TASKS.snapshot()
        self.setVisible(bool(self.shown))
        if self.shown:
            lines = []
            for t in self.shown:
                f = t.fraction()
                pct = ("%d%%" % round(f * 100)) if f is not None else "…"
                lines.append("%s   %s%s" % (t.title, pct, ("   " + t.detail) if t.detail else ""))
            self.setToolTip("\n".join(lines)); self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(5, 5, 36, 36)
        p.setPen(QPen(QColor("#2b2f38"), 4)); p.drawEllipse(r)
        if not self.shown: return
        t = self.shown[-1]; f = t.fraction()
        p.setPen(QPen(QColor(UI["ui_accent"]), 4))
        if f is None:
            start = int((time.monotonic() * 360 * 1.2) % 360); p.drawArc(r, start * 16, -100 * 16)
        else:
            p.drawArc(r, 90 * 16, -int(f * 360 * 16))
        p.setPen(QColor("#dfe3ea")); font = QFont(p.font()); font.setPointSize(max(7, font.pointSize() - 2)); p.setFont(font)
        label = str(len(self.shown)) if len(self.shown) > 1 else ("%d" % round(f * 100) if f is not None else "…")
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

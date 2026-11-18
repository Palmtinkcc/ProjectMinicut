"""Frame build preview (Patch 38): the frame an export is building, shown in the Tasks window next to the progress bar.
Like Blender's render window: the picture is made of tiles; the tiles of the newest frame appear one after the other starting
from the middle, the one that is being filled is outlined, the tiles still waiting show the previous frame, dimmed."""
import time
from ..shared.deps import *


class BuildPreview(QWidget):
    SWEEP = 0.30          # seconds for the tiles of one picture to fill in (a new picture arrives about 8 times a second)
    COLS = 8
    def __init__(self):
        super().__init__(); self.setFixedSize(176, 100); self.cur = None; self.old = None; self.key = None; self.t0 = 0.0; self.label = ""; self.order = None; self.grid = (0, 0)
        self.timer = QTimer(self); self.timer.setInterval(33); self.timer.timeout.connect(self._tick)
    def feed(self, thumb):
        """thumb: (BGR picture, frame number, total frames) or None."""
        if thumb is None:
            self.cur = self.old = None; self.update(); return
        img, i, total = thumb
        if (i, id(img)) == self.key: return
        self.key = (i, id(img)); self.old = self.cur
        h, w = img.shape[:2]; rgb = np.ascontiguousarray(img[:, :, ::-1])
        q = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy(); self.cur = q; self.label = "Frame %d / %d" % (i + 1, total)
        cols = self.COLS; rows = max(1, int(round(cols * h / float(w)))); self.grid = (cols, rows)
        cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
        self.order = sorted(range(cols * rows), key=lambda k: (((k % cols) - cx) ** 2 + ((k // cols) - cy) ** 2, k))        # from the middle outwards
        self.t0 = time.monotonic()
        if not self.timer.isActive(): self.timer.start()
        self.update()
    def _tick(self):
        if self.cur is None or time.monotonic() - self.t0 > self.SWEEP + 0.1: self.timer.stop()
        self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, False); R = self.rect().adjusted(1, 1, -1, -1)
        p.fillRect(self.rect(), QColor("#1b1b1b"))
        if self.cur is None:
            p.setPen(QColor("#6b6b73")); p.drawText(self.rect(), Qt.AlignCenter, "waiting for the first frame"); return
        cols, rows = self.grid; n = cols * rows; ar = self.cur.width() / float(self.cur.height())
        w = R.width(); h = int(w / ar)
        if h > R.height(): h = R.height(); w = int(h * ar)
        box = QRectF(R.x() + (R.width() - w) / 2.0, R.y() + (R.height() - h) / 2.0, w, h)
        prog = min(1.0, (time.monotonic() - self.t0) / self.SWEEP); done = int(prog * n); active = done if prog < 1.0 else -1
        rank = {k: r for r, k in enumerate(self.order)}; tw, th = w / float(cols), h / float(rows)
        sw, sh = self.cur.width() / float(cols), self.cur.height() / float(rows)
        for k in range(n):
            c, r = k % cols, k // cols; dst = QRectF(box.x() + c * tw, box.y() + r * th, tw + 0.6, th + 0.6); src = QRectF(c * sw, r * sh, sw, sh); rk = rank[k]
            if rk < done or rk == active: p.drawImage(dst, self.cur, src)
            elif self.old is not None:
                p.drawImage(dst, self.old, QRectF(c * (self.old.width() / float(cols)), r * (self.old.height() / float(rows)), self.old.width() / float(cols), self.old.height() / float(rows)))
                p.fillRect(dst, QColor(0, 0, 0, 120))
            else: p.fillRect(dst, QColor("#2a2a2a"))
            if rk == active:                                  # the tile being built: a bright frame with corner marks (like Blender)
                p.setPen(QPen(QColor("#ffffff"), 1)); p.setBrush(Qt.NoBrush); p.drawRect(dst.adjusted(0.5, 0.5, -1, -1))
                p.setPen(QPen(QColor("#ff9d2e"), 2)); L = min(tw, th) * 0.35
                for (x, y, dx, dy) in ((dst.left(), dst.top(), 1, 1), (dst.right(), dst.top(), -1, 1), (dst.left(), dst.bottom(), 1, -1), (dst.right(), dst.bottom(), -1, -1)):
                    p.drawLine(QPointF(x, y), QPointF(x + dx * L, y)); p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))
        p.setPen(QColor(255, 255, 255, 60)); p.setBrush(Qt.NoBrush); p.drawRect(box.adjusted(0, 0, -1, -1))
        f = QFont(QApplication.font()); f.setPixelSize(10); f.setBold(True); p.setFont(f); fm = p.fontMetrics(); tw_ = fm.horizontalAdvance(self.label) + 8
        p.fillRect(QRectF(box.left() + 3, box.bottom() - 16, tw_, 13), QColor(0, 0, 0, 160)); p.setPen(QColor("#e6e6e6")); p.drawText(QRectF(box.left() + 3, box.bottom() - 16, tw_, 13), Qt.AlignCenter, self.label)

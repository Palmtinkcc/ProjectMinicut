"""Small widgets used by the Settings window: usage ring, hardware card, side navigation, option list, theme map."""
from .deps import *
from .theme import *
from .ui import pal

__all__ = ["Ring", "HwCard", "SideNav", "OptionList", "ThemeMap"]


class Ring(QWidget):
    """A round gauge: a grey track and a coloured arc for value 0..100 (None = unknown), the text in the middle."""
    def __init__(self, size=62, color="#00ffef", width=7):
        super().__init__(); self.setFixedSize(size, size); self.value = None; self.color = color; self.pw = width; self.text = None; self.sub = ""
    def set(self, value, text=None, sub=""):
        self.value = value; self.text = text; self.sub = sub; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); m = self.pw / 2.0 + 1; r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#5d5d5d"), self.pw)); p.drawEllipse(r)
        if self.value is not None and self.value > 0:
            pen = QPen(QColor(self.color), self.pw); pen.setCapStyle(Qt.FlatCap); p.setPen(pen); p.drawArc(r, 90 * 16, -int(360 * 16 * min(100.0, self.value) / 100.0))
        t = self.text if self.text is not None else ("--" if self.value is None else "%d%%" % round(self.value))
        f = QFont(QApplication.font()); f.setPixelSize(max(9, int(self.width() * 0.22))); f.setBold(True); p.setFont(f); p.setPen(QColor("#e6e6e6"))
        p.drawText(QRectF(0, 0, self.width(), self.height() * (0.56 if self.sub else 1.0) + (self.height() * 0.1 if self.sub else 0)), Qt.AlignCenter, t)
        if self.sub:
            f.setPixelSize(max(7, int(self.width() * 0.13))); f.setBold(False); p.setFont(f); p.setPen(QColor("#9a9aa2"))
            p.drawText(QRectF(0, self.height() * 0.52, self.width(), self.height() * 0.3), Qt.AlignHCenter | Qt.AlignTop, self.sub)


class HwCard(QFrame):
    """[icon] name + a ring with the load. kind: 'gpu' (a card with two fans) or 'cpu' (a chip)."""
    def __init__(self, kind, name="..."):
        super().__init__(); self.kind = kind; self.setObjectName("HwCard")
        self.setStyleSheet("QFrame#HwCard{background:#2a2a2a;border:1px solid #3c3c3c;border-radius:12px;}QLabel{background:transparent;border:none;}")
        h = QHBoxLayout(self); h.setContentsMargins(10, 8, 10, 8); h.setSpacing(10)
        self.pic = QLabel(); self.pic.setFixedSize(62, 44); h.addWidget(self.pic)
        col = QVBoxLayout(); col.setSpacing(1)
        self.title = QLabel("GPU" if kind == "gpu" else "CPU"); self.title.setStyleSheet("color:#8e8e9b;font-size:11px;font-weight:700;")
        self.name = QLabel(name); self.name.setStyleSheet("color:#ffffff;font-size:14px;font-weight:700;"); self.name.setWordWrap(True)
        self.detail = QLabel(""); self.detail.setStyleSheet("color:#8e8e9b;font-size:11px;")
        col.addWidget(self.title); col.addWidget(self.name); col.addWidget(self.detail); h.addLayout(col, 1)
        self.ring = Ring(54); h.addWidget(self.ring); self._draw()
    def _draw(self):
        pm = QPixmap(62, 44); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
        if self.kind == "gpu":
            p.setPen(Qt.NoPen); p.setBrush(QColor("#414141")); p.drawRoundedRect(QRectF(1, 3, 60, 38), 6, 6)
            for cx in (19, 43): p.setBrush(QColor("#505050")); p.drawEllipse(QPointF(cx, 22), 13, 13); p.setBrush(QColor("#2a2a2a")); p.drawEllipse(QPointF(cx, 22), 4, 4)
        else:
            p.setPen(QPen(QColor("#5d5d5d"), 1.5))
            for k in range(4):
                o = 15 + k * 8; p.drawLine(QPointF(o, 1), QPointF(o, 43)); p.drawLine(QPointF(10, o - 5), QPointF(52, o - 5))
            p.setPen(Qt.NoPen); p.setBrush(QColor("#414141")); p.drawRoundedRect(QRectF(13, 6, 36, 32), 5, 5)
            p.setBrush(QColor("#505050")); p.drawRoundedRect(QRectF(20, 13, 22, 18), 3, 3)
        p.end(); self.pic.setPixmap(pm)
    def set(self, name, detail, load):
        self.name.setText(name); self.detail.setText(detail); self.ring.set(load)


class SideNav(QWidget):
    """The list on the left of the Settings window. Items are (key, text); a gap can be put before an item."""
    changed = Signal(int)
    def __init__(self, items, gap_before=()):
        super().__init__(); self.setFixedWidth(120); v = QVBoxLayout(self); v.setContentsMargins(0, 4, 8, 4); v.setSpacing(2); self.btns = []
        for i, t in enumerate(items):
            if i in gap_before: v.addSpacing(14)
            b = QPushButton(t); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setFixedHeight(32)
            b.clicked.connect(lambda _=False, k=i: self.select(k, True)); v.addWidget(b); self.btns.append(b)
        v.addStretch(1); self._style(); self.select(0, False)
    def _style(self):
        a = UI["ui_accent"]
        for b in self.btns:
            b.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:8px;text-align:left;padding-left:12px;color:#c9c9d3;font-weight:700;font-size:13px;}"
                            "QPushButton:hover{background:#2a2a2e;}QPushButton:checked{background:#2a2a2e;color:%s;}QPushButton:disabled{color:#5a5a62;}" % a)
    def select(self, i, emit=True):
        for k, b in enumerate(self.btns): b.setChecked(k == i)
        self.cur = i
        if emit: self.changed.emit(i)
    def dim(self, i, on): self.btns[i].setEnabled(not on)


class OptionList(QWidget):
    """A vertical list where exactly one option is selected, on a thin track (the preset / space lists of the Export page)."""
    changed = Signal(int)
    def __init__(self, labels):
        super().__init__(); v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3); self.btns = []; self.cur = 0
        for i, t in enumerate(labels):
            b = QPushButton(t); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, k=i: self.set(k, True)); v.addWidget(b); self.btns.append(b)
        a = UI["ui_accent"]
        for b in self.btns:
            b.setStyleSheet("QPushButton{background:#2a2a2e;border:1px solid #3c3c3c;border-radius:8px;text-align:left;padding-left:12px;color:#c9c9d3;}"
                            "QPushButton:hover{border-color:#5a5a62;}QPushButton:checked{border:1px solid %s;color:#ffffff;background:#26343a;}" % a)
        self.set(0, False)
    def set(self, i, emit=False):
        i = max(0, min(len(self.btns) - 1, int(i))); self.cur = i
        for k, b in enumerate(self.btns): b.setChecked(k == i)
        if emit: self.changed.emit(i)
    def index(self): return self.cur


class ThemeMap(QWidget):
    """A small picture of the editor. Click a part to choose which colour to change. parts: key -> (label, theme key); the colours are read from UI."""
    picked = Signal(str)
    PARTS = (("window", "Background", "ui_window", (0, 0, 1, 1)), ("pool", "Pool", "ui_panel", (0.03, 0.05, 0.22, 0.60)), ("view", "Viewport", "vp_bg", (0.27, 0.05, 0.46, 0.60)),
             ("props", "Properties", "ui_input", (0.75, 0.05, 0.22, 0.60)), ("time", "Timeline", "tl_bg", (0.03, 0.68, 0.94, 0.27)))
    def __init__(self):
        super().__init__(); self.setMinimumHeight(150); self.setCursor(Qt.PointingHandCursor); self.cur = "tl_bg"; self.color_of = lambda k: UI[k]
    def _rects(self):
        W, H = self.width(), self.height(); out = []
        for name, label, key, (x, y, w, h) in self.PARTS: out.append((name, label, key, QRectF(x * W, y * H, w * W, h * H)))
        return out
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        for name, label, key, r in self._rects():
            if name == "window": r = r.adjusted(1, 1, -1, -1)
            p.setPen(QPen(QColor("#ffffff") if key == self.cur else QColor(255, 255, 255, 40), 2 if key == self.cur else 1)); p.setBrush(QColor(self.color_of(key)))
            p.drawRoundedRect(r, 8, 8)
            if name != "window":
                p.setPen(QColor("#e6e6e6" if QColor(self.color_of(key)).lightness() < 140 else "#202020")); f = QFont(QApplication.font()); f.setPixelSize(11); p.setFont(f); p.drawText(r, Qt.AlignCenter, label)
    def mousePressEvent(self, e):
        for name, label, key, r in reversed(self._rects()):
            if name != "window" and r.contains(e.position()): self.cur = key; self.update(); self.picked.emit(key); return
        self.cur = "ui_window"; self.update(); self.picked.emit("ui_window")

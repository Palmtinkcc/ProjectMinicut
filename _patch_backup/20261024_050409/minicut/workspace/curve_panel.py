"""Keyframes tab helpers: curve presets drawn as small pictures, and the curve preset list."""
from ..shared.deps import *
from ..shared.core import *


def bezier_points(e, n=40):
    x1, y1, x2, y2 = [float(v) for v in e]; pts = []
    for i in range(n + 1):
        t = i / n; u = 1 - t
        pts.append((3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3, 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3))
    return pts


def all_presets(settings):
    out = OrderedDict(EASE_PRESETS)
    for k, v in (settings["curve_presets"] or {}).items(): out[k] = v
    return out


class PresetTile(QWidget):
    clicked = Signal(object)
    def __init__(self, name, curve, selected=False):
        super().__init__(); self.name = name; self.curve = [float(v) for v in curve]; self.selected = selected
        self.setFixedSize(92, 84); self.setCursor(Qt.PointingHandCursor); self.setToolTip(name)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.curve)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(UI["ui_input"]))
        p.setPen(QPen(QColor(UI["ui_accent"]) if self.selected else QColor("#3a3a40"), 2 if self.selected else 1))
        p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -24)
        def mp(x, y): return QPointF(r.left() + x * r.width(), r.bottom() - (y + 0.4) / 1.8 * r.height())
        path = QPainterPath(mp(0, 0))
        for x, y in bezier_points(self.curve)[1:]: path.lineTo(mp(x, y))
        p.setPen(QPen(QColor(UI["ui_accent"]), 2.2)); p.drawPath(path)
        p.setPen(QColor("#9aa0aa")); f = QFont(p.font()); f.setPointSize(max(7, f.pointSize() - 2)); p.setFont(f)
        p.drawText(QRectF(0, self.height() - 22, self.width(), 20), Qt.AlignCenter, self.name)

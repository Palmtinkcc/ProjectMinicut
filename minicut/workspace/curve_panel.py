"""Keyframes tab helpers: curve presets drawn as small pictures, and the curve preset list."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.theme import UI


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
        self.setMinimumSize(70, 88); self.setFixedHeight(88); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.setCursor(Qt.PointingHandCursor); self.setToolTip(name)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.curve)
    def enterEvent(self, e): self._h = True; self.update()
    def leaveEvent(self, e): self._h = False; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); acc = QColor(UI["ui_accent"]); h = getattr(self, "_h", False)
        p.setPen(QPen(acc if (self.selected or h) else QColor("#34343c"), 2 if self.selected else 1)); p.setBrush(QColor("#2a2a30" if h else "#222227")); p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        r = QRectF(self.rect()).adjusted(14, 12, -14, -28)
        def mp(x, y): return QPointF(r.left() + x * r.width(), r.bottom() - (y + 0.4) / 1.8 * r.height())
        base = QPainterPath(mp(0, 0)); path = QPainterPath(mp(0, 0))
        for x, y in bezier_points(self.curve)[1:]: path.lineTo(mp(x, y))
        p.setPen(QPen(QColor("#3a3a44"), 1, Qt.DashLine)); p.drawLine(mp(0, 0), mp(1, 1))
        p.setPen(QPen(acc, 2.6, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush); p.drawPath(path)
        p.setPen(QColor("#ececf1" if self.selected else "#9aa0aa")); f = QFont(p.font()); f.setPixelSize(11); f.setBold(self.selected); p.setFont(f)
        p.drawText(QRectF(0, self.height() - 24, self.width(), 20), Qt.AlignCenter, p.fontMetrics().elidedText(self.name, Qt.ElideRight, self.width() - 8))

"""Generic widgets: panels, dialog frame, toast, color picker, curve / ease editors."""
from .deps import *
from .icons import *
from .theme import *
from .core import *


def tool(text, tip="", cb=None, checkable=False, icon=None, isize=None):
    b = QToolButton(); b.setText(text); b.setToolTip(tip); b.setFocusPolicy(Qt.NoFocus); b.setCheckable(checkable)
    if icon is not None:
        n = isize or int(UI["icon_size"]); b.setIcon(icon if isinstance(icon, QIcon) else app_icon(icon)); b.setIconSize(QSize(n, n))
        if isize is None: b.setProperty("iconDefault", True)
        if text: b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    if cb: b.clicked.connect(lambda *_: cb())
    return b


class Panel(QFrame):
    def __init__(self, title=""):
        super().__init__(); self.setObjectName("Panel")
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(6)
        self.head = QHBoxLayout(); self.head.setSpacing(4)
        if title:
            lbl = QLabel(title); lbl.setObjectName("PanelTitle"); self.head.addWidget(lbl)
        self.head.addStretch(); lay.addLayout(self.head); self.body = lay
        self.setMinimumSize(1, 1)


class SmoothSplitter(QSplitter):
    def __init__(self, orient):
        super().__init__(orient); self.setHandleWidth(6); self.setChildrenCollapsible(True); self._saved = {}; self._anim = None
    def toggle(self, i, show=None):
        sizes = self.sizes(); total = sum(sizes)
        visible = sizes[i] > 0
        if show is not None and show == visible: return
        others = [k for k in range(len(sizes)) if k != i]
        j = max(others, key=lambda k: sizes[k]); tgt = list(sizes)
        if visible: self._saved[i] = sizes[i]; tgt[j] += sizes[i]; tgt[i] = 0
        else:
            want = min(self._saved.get(i, total // 4), max(50, sizes[j] - 120)); tgt[i] = want; tgt[j] -= want
        self.animate_to(tgt)
    def animate_to(self, tgt):
        start = self.sizes(); a = QVariantAnimation(self); a.setStartValue(0.0); a.setEndValue(1.0)
        a.setDuration(280); a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v: self.setSizes([int(s + (e - s) * v) for s, e in zip(start, tgt)]))
        a.start(); self._anim = a


class AnimatedDialog(QDialog):
    def __init__(self, parent, title, width=460):
        super().__init__(parent); self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setMinimumWidth(width); self._closing = False
        outer = QVBoxLayout(self); outer.setContentsMargins(16, 16, 16, 16)
        self.card = QFrame(); self.card.setObjectName("Card"); outer.addWidget(self.card)
        sh = QGraphicsDropShadowEffect(self.card); sh.setBlurRadius(32); sh.setColor(QColor(0, 0, 0, 170)); sh.setOffset(0, 6)
        self.card.setGraphicsEffect(sh)
        lay = QVBoxLayout(self.card); lay.setContentsMargins(18, 12, 18, 16); lay.setSpacing(10)
        head = QHBoxLayout(); t = QLabel(title); t.setObjectName("H2"); head.addWidget(t); head.addStretch()
        x = tool("", "Close", self.reject, icon="close", isize=14); x.setObjectName("WinClose"); head.addWidget(x); lay.addLayout(head)
        self.body = QVBoxLayout(); self.body.setSpacing(10); lay.addLayout(self.body)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 56 and self.windowHandle(): self.windowHandle().startSystemMove()
    def showEvent(self, e):
        super().showEvent(e); self.setWindowOpacity(0.0)
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"windowOpacity", self); a.setDuration(220); a.setStartValue(0.0); a.setEndValue(1.0)
        b = QPropertyAnimation(self, b"pos", self); b.setDuration(260); b.setStartValue(self.pos() + QPointF(0, 18).toPoint())
        b.setEndValue(self.pos()); b.setEasingCurve(QEasingCurve.OutCubic)
        g.addAnimation(a); g.addAnimation(b); g.start(); self._open_anim = g
    def done(self, r):
        if self._closing: return
        self._closing = True
        a = QPropertyAnimation(self, b"windowOpacity", self); a.setDuration(160); a.setStartValue(self.windowOpacity()); a.setEndValue(0.0)
        a.finished.connect(lambda: QDialog.done(self, r)); a.start(); self._close_anim = a


def ask(parent, title, text, buttons=("OK", "Cancel")):
    d = AnimatedDialog(parent, title, 380); lbl = QLabel(text); lbl.setWordWrap(True); d.body.addWidget(lbl)
    row = QHBoxLayout(); row.addStretch(); d.choice = None
    for i, b in enumerate(buttons):
        btn = QPushButton(b)
        if i == 0: btn.setObjectName("Accent")
        btn.clicked.connect(lambda _=False, b=b: (setattr(d, "choice", b), d.accept())); row.addWidget(btn)
    d.body.addLayout(row); d.exec(); return d.choice


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent); self.setObjectName("Toast"); self.hide()
        self.eff = QGraphicsOpacityEffect(self); self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self); self.anim.setDuration(220)
        self.anim.finished.connect(lambda: self.hide() if self.eff.opacity() < 0.05 else None)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self._out)
    def show_msg(self, text, ms=1800):
        self.setText(text); self.adjustSize(); p = self.parent()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 30); self.raise_(); self.show()
        self.anim.stop(); self.anim.setStartValue(self.eff.opacity() if self.isVisible() else 0.0); self.anim.setEndValue(1.0); self.anim.start()
        self.timer.start(ms)
    def _out(self):
        self.anim.stop(); self.anim.setStartValue(1.0); self.anim.setEndValue(0.0); self.anim.start()


COLOR_PRESETS = ["#ffffff", "#000000", "#8e8e93", "#3a3a3c", "#ff3b30", "#ff9500", "#ffcc00", "#34c759",
           "#00c2d1", "#30b0ff", "#007aff", "#5856d6", "#af52de", "#ff2d55", "#f5e6c8", "#7a4b2a"]


POPUP_QSS = """
QFrame#ColorPopup { background:#232327; border:1px solid #3a3a40; border-radius:10px; }
QLineEdit { background:#18181b; color:#e6e6e6; border:1px solid #3a3a40; border-radius:5px; padding:4px 6px; font-family:Consolas; }
QLineEdit:focus { border-color:#22d3ee; }
"""


class _SVBox(QWidget):
    def __init__(self, pop):
        super().__init__(pop); self.pop = pop; self.setFixedSize(232, 150); self.setCursor(Qt.CrossCursor)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = QRectF(self.rect())
        clip = QPainterPath(); clip.addRoundedRect(r, 6, 6); p.setClipPath(clip)
        p.fillRect(r, QColor.fromHsvF(self.pop.h, 1, 1))
        g = QLinearGradient(r.topLeft(), r.topRight()); g.setColorAt(0, QColor(255, 255, 255, 255)); g.setColorAt(1, QColor(255, 255, 255, 0)); p.fillRect(r, g)
        g = QLinearGradient(r.topLeft(), r.bottomLeft()); g.setColorAt(0, QColor(0, 0, 0, 0)); g.setColorAt(1, QColor(0, 0, 0, 255)); p.fillRect(r, g)
        pt = QPointF(self.pop.s * r.width(), (1 - self.pop.v) * r.height())
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(0, 0, 0, 150), 3)); p.drawEllipse(pt, 6, 6)
        p.setPen(QPen(QColor("#ffffff"), 2)); p.drawEllipse(pt, 6, 6)
    def _at(self, pos):
        self.pop.s = min(1.0, max(0.0, pos.x() / self.width()))
        self.pop.v = 1 - min(1.0, max(0.0, pos.y() / self.height())); self.pop.sync()
    def mousePressEvent(self, e): self._at(e.position())
    def mouseMoveEvent(self, e): self._at(e.position())
    def mouseReleaseEvent(self, e): self.pop.commit()


class _HueBar(QWidget):
    def __init__(self, pop):
        super().__init__(pop); self.pop = pop; self.setFixedSize(232, 16); self.setCursor(Qt.PointingHandCursor)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = QRectF(self.rect()).adjusted(0, 3, 0, -3)
        g = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7): g.setColorAt(i / 6, QColor.fromHsvF(min(i / 6, .9999), 1, 1))
        p.setPen(Qt.NoPen); p.setBrush(g); p.drawRoundedRect(r, 5, 5)
        x = min(self.width() - 7, max(7, self.pop.h * self.width()))
        p.setBrush(QColor.fromHsvF(self.pop.h, 1, 1)); p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QPointF(x, self.height() / 2), 6, 6)
    def _at(self, pos): self.pop.h = min(.9999, max(0.0, pos.x() / self.width())); self.pop.sync()
    def mousePressEvent(self, e): self._at(e.position())
    def mouseMoveEvent(self, e): self._at(e.position())
    def mouseReleaseEvent(self, e): self.pop.commit()


class ColorPopup(QFrame):
    live = Signal(str); picked = Signal(str)
    def __init__(self, color, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose); self.setObjectName("ColorPopup"); self.setStyleSheet(POPUP_QSS)
        c = QColor(color); self.h = max(0.0, c.hsvHueF()); self.s = c.hsvSaturationF(); self.v = c.valueF()
        v = QVBoxLayout(self); v.setContentsMargins(12, 12, 12, 12); v.setSpacing(10)
        self.sv = _SVBox(self); self.hue = _HueBar(self); v.addWidget(self.sv); v.addWidget(self.hue)
        row = QHBoxLayout(); row.setSpacing(8)
        self.sw = QLabel(); self.sw.setFixedSize(26, 26)
        self.hex = QLineEdit(); self.hex.setMaxLength(7); self.hex.editingFinished.connect(self._hex)
        row.addWidget(self.sw); row.addWidget(self.hex, 1); v.addLayout(row)
        grid = QGridLayout(); grid.setSpacing(6)
        for i, col in enumerate(COLOR_PRESETS):
            b = QToolButton(); b.setFixedSize(22, 22); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QToolButton{{background:{col};border:1px solid #44444a;border-radius:4px;}}"
                            f"QToolButton:hover{{border:2px solid #ffffff;}}")
            b.clicked.connect(lambda _=False, col=col: self.set_hex(col, True)); grid.addWidget(b, i // 8, i % 8)
        v.addLayout(grid); self.sync(emit=False)
    def color(self): return QColor.fromHsvF(self.h, self.s, self.v).name()
    def sync(self, emit=True):
        c = self.color(); self.sw.setStyleSheet(f"background:{c};border:1px solid #55555c;border-radius:5px;")
        if not self.hex.hasFocus(): self.hex.setText(c)
        self.sv.update(); self.hue.update()
        if emit: self.live.emit(c)
    def set_hex(self, h, commit=False):
        c = QColor(h)
        if not c.isValid(): return
        hh = c.hsvHueF(); self.h = self.h if hh < 0 else hh; self.s = c.hsvSaturationF(); self.v = c.valueF()
        self.sync()
        if commit: self.commit()
    def _hex(self):
        t = self.hex.text().strip(); self.set_hex(t if t.startswith("#") else "#" + t, True)
    def commit(self): self.picked.emit(self.color())


class ColorButton(QPushButton):
    changed = Signal(str)
    def __init__(self, c="#ffffff"):
        super().__init__(); self.setFixedSize(46, 24); self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor); self.c = "#ffffff"; self.set(c); self.clicked.connect(self.pick)
    def set(self, c):
        q = QColor(c); self.c = q.name() if q.isValid() else "#ffffff"; self.update()
    def paintEvent(self, e):   # วาดเอง ไม่ใช้ stylesheet จึงไม่ลามไปที่ widget ลูก
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor("#ffffff" if self.underMouse() else "#4a4a52"), 1)); p.setBrush(QColor(self.c))
        p.drawRoundedRect(r, 5, 5)
    def pick(self):
        pop = ColorPopup(self.c, self.window())
        pop.live.connect(self._live); pop.picked.connect(self._picked); pop.adjustSize()
        g = self.mapToGlobal(QPoint(0, self.height() + 4)); scr = self.screen().availableGeometry()
        x = min(g.x(), scr.right() - pop.width() - 4)
        y = g.y() if g.y() + pop.height() < scr.bottom() else self.mapToGlobal(QPoint(0, 0)).y() - pop.height() - 4
        pop.move(x, y); pop.show()
    def _live(self, c): self.c = c; self.update()
    def _picked(self, c): self.set(c); self.changed.emit(c)


class PathEdit(QWidget):
    def __init__(self, path):
        super().__init__(); lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.e = QLineEdit(path); b = QPushButton("…"); b.setFixedWidth(34); lay.addWidget(self.e, 1); lay.addWidget(b)
        b.clicked.connect(lambda: (lambda d: self.e.setText(d) if d else None)(QFileDialog.getExistingDirectory(self, "Choose folder", self.e.text())))
    def text(self): return self.e.text().strip()


class CurveEditor(QWidget):
    changed = Signal()
    COLORS = {"m": "#e6eeff", "r": "#ff5a6a", "g": "#4ade80", "b": "#5aa2ff"}
    def __init__(self):
        super().__init__(); self.curves = copy.deepcopy(DEFAULT_CURVE); self.ch = "m"; self.drag = None
        self.setMinimumHeight(200)
    def area(self):
        s = max(40, min(self.width(), self.height()) - 16); return QRectF((self.width() - s) / 2, 8, s, s)
    def to_w(self, x, y): a = self.area(); return QPointF(a.left() + x * a.width(), a.bottom() - y * a.height())
    def to_n(self, p):
        a = self.area()
        return min(1, max(0, (p.x() - a.left()) / a.width())), min(1, max(0, (a.bottom() - p.y()) / a.height()))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); a = self.area()
        p.setPen(Qt.NoPen); p.setBrush(QColor("#0a1020")); p.drawRoundedRect(a.adjusted(-5, -5, 5, 5), 8, 8)
        p.setPen(QPen(QColor("#18233d"), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(a.left() + a.width() * i / 4, a.top()), QPointF(a.left() + a.width() * i / 4, a.bottom()))
            p.drawLine(QPointF(a.left(), a.top() + a.height() * i / 4), QPointF(a.right(), a.top() + a.height() * i / 4))
        p.setPen(QPen(QColor("#22314f"), 1, Qt.DashLine)); p.drawLine(a.bottomLeft(), a.topRight())
        xs = np.linspace(0, 1, 65)
        for ch in ("r", "g", "b", "m"):
            if ch == self.ch or self.curves[ch] == IDENT: continue
            self._draw(p, ch, xs, 1, 90)
        self._draw(p, self.ch, xs, 2, 255)
        for x, y in self.curves[self.ch]:
            p.setPen(QPen(QColor("#0a1020"), 2)); p.setBrush(QColor(self.COLORS[self.ch])); p.drawEllipse(self.to_w(x, y), 5, 5)
    def _draw(self, p, ch, xs, w, alpha):
        ys = curve_eval(self.curves[ch], xs); col = QColor(self.COLORS[ch]); col.setAlpha(alpha)
        path = QPainterPath(self.to_w(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]): path.lineTo(self.to_w(x, y))
        p.setPen(QPen(col, w)); p.setBrush(Qt.NoBrush); p.drawPath(path)
    def mousePressEvent(self, e):
        pts = self.curves[self.ch]; pos = e.position()
        for i, (x, y) in enumerate(pts):
            q = self.to_w(x, y)
            if math.hypot(q.x() - pos.x(), q.y() - pos.y()) < 9:
                if e.button() == Qt.RightButton and 0 < i < len(pts) - 1:
                    pts.pop(i); self.update(); self.changed.emit(); return
                self.drag = i; return
        if e.button() == Qt.LeftButton:
            x, y = self.to_n(pos); idx = next((i for i, pt in enumerate(pts) if pt[0] > x), len(pts))
            pts.insert(idx, [x, y]); self.drag = idx; self.update(); self.changed.emit()
    def mouseMoveEvent(self, e):
        if self.drag is None: return
        pts = self.curves[self.ch]; i = self.drag; x, y = self.to_n(e.position())
        lo = pts[i - 1][0] + 0.01 if i > 0 else 0.0; hi = pts[i + 1][0] - 0.01 if i < len(pts) - 1 else 1.0
        pts[i] = [min(hi, max(lo, x)), y]; self.update(); self.changed.emit()
    def mouseReleaseEvent(self, e): self.drag = None


class EaseEditor(QWidget):
    changed = Signal(list)
    def __init__(self):
        super().__init__(); self.e = [0, 0, 1, 1]; self.drag = None; self.setMinimumHeight(180)
    def set_e(self, e): self.e = list(e); self.update()
    def area(self): return QRectF(self.rect()).adjusted(18, 14, -18, -14)
    def m(self, x, y): a = self.area(); return QPointF(a.left() + x * a.width(), a.bottom() - (y + .4) / 1.8 * a.height())
    def um(self, p):
        a = self.area()
        return min(1, max(0, (p.x() - a.left()) / a.width())), min(1.4, max(-.4, (a.bottom() - p.y()) / a.height() * 1.8 - .4))
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#0a1020")); p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 4, -4, -4), 10, 10)
        p.setPen(QPen(QColor("#1f2d4a"), 1, Qt.DashLine)); p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(self.m(0, 1), self.m(1, 0)))
        x1, y1, x2, y2 = self.e; a, b, c, d = self.m(0, 0), self.m(x1, y1), self.m(x2, y2), self.m(1, 1)
        p.setPen(QPen(QColor("#4a5f8a"), 1)); p.drawLine(a, b); p.drawLine(d, c)
        path = QPainterPath(a); path.cubicTo(b, c, d); p.setPen(QPen(QColor("#5aa2ff"), 2.5)); p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#ffd166"))
        for q in (b, c): p.drawEllipse(q, 6, 6)
    def mousePressEvent(self, e):
        pos = e.position(); x1, y1, x2, y2 = self.e
        for i, q in enumerate((self.m(x1, y1), self.m(x2, y2))):
            if math.hypot(q.x() - pos.x(), q.y() - pos.y()) < 12: self.drag = i
    def mouseMoveEvent(self, e):
        if self.drag is None: return
        x, y = self.um(e.position()); self.e[self.drag * 2] = round(x, 3); self.e[self.drag * 2 + 1] = round(y, 3)
        self.update(); self.changed.emit(list(self.e))
    def mouseReleaseEvent(self, e): self.drag = None

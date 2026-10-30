"""Generic widgets: panels, dialog frame, toast, color picker, curve / ease editors."""
from .deps import *
from .icons import *
from .theme import *
from .core import *
from .ui import *


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
        ico = {"Media": "photo_library", "Properties": "tune"}.get(title, "")
        if ico: self.head.addWidget(icon_label(ico, "#8e8e9b", 18))
        if title and title != "Player":
            lbl = QLabel({"Properties": "Properties"}.get(title, title)); lbl.setObjectName("PanelTitle"); lbl.setStyleSheet("color:#c9c9d3;font-weight:700;font-size:13px;"); self.head.addWidget(lbl)
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
        self.e = TextField(path); b = Btn("", "folder_open", "soft", "Choose a folder", None, h=30); b.setFixedWidth(40); lay.addWidget(self.e, 1); lay.addWidget(b)
        b.clicked.connect(lambda: (lambda d: self.e.setText(d) if d else None)(QFileDialog.getExistingDirectory(self, "Choose folder", self.e.text())))
    def text(self): return self.e.text().strip()


def _clamp_f(v): return max(-0.2, min(1.2, v))


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
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); a = self.area(); box = a.adjusted(-6, -6, 6, 6)
        p.setPen(QPen(QColor("#2c2c33"), 1)); p.setBrush(QColor("#17171b")); p.drawRoundedRect(box, 12, 12)
        p.setPen(QPen(QColor("#25252b"), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(a.left() + a.width() * i / 4, a.top()), QPointF(a.left() + a.width() * i / 4, a.bottom()))
            p.drawLine(QPointF(a.left(), a.top() + a.height() * i / 4), QPointF(a.right(), a.top() + a.height() * i / 4))
        p.setPen(QPen(QColor("#3a3a44"), 1, Qt.DashLine)); p.drawLine(a.bottomLeft(), a.topRight())
        xs = np.linspace(0, 1, 65)
        for ch in ("r", "g", "b", "m"):
            if ch == self.ch or self.curves[ch] == IDENT: continue
            self._draw(p, ch, xs, 1.6, 80)
        self._draw(p, self.ch, xs, 3, 255)
        for x, y in self.curves[self.ch]:
            q = self.to_w(x, y); col = QColor(self.COLORS[self.ch]); glow = QColor(col); glow.setAlpha(60)
            p.setPen(Qt.NoPen); p.setBrush(glow); p.drawEllipse(q, 10, 10); p.setBrush(QColor("#ffffff")); p.setPen(QPen(col, 2.4)); p.drawEllipse(q, 5.5, 5.5)
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
        self._ph = 0.0; self._last_step = None
        try:
            _hz = max(30, min(360, int(QApplication.primaryScreen().refreshRate() or 60)))
        except Exception: _hz = 60
        self._tm = QTimer(self); self._tm.setInterval(max(1, int(round(1000 / _hz)))); self._tm.timeout.connect(self._step)

    def _step(self):
        import time as _t
        now = _t.monotonic()
        dt = (now - self._last_step) if self._last_step is not None else 0.016
        self._last_step = now
        # ~0.9 s per cycle; 0.12 s pause at each end
        self._ph = (self._ph + dt / 0.90) % 1.0
        self.update()

    def set_e(self, e): self.e = list(e); self.update()
    def area(self): return QRectF(self.rect()).adjusted(18, 14, -18, -34)
    def m(self, x, y): a = self.area(); return QPointF(a.left() + x * a.width(), a.bottom() - (y + .4) / 1.8 * a.height())
    def um(self, p):
        a = self.area()
        return min(1, max(0, (p.x() - a.left()) / a.width())), min(1.4, max(-.4, (a.bottom() - p.y()) / a.height() * 1.8 - .4))
    def showEvent(self, ev): self._last_step = None; self._tm.start()
    def hideEvent(self, ev): self._tm.stop()

    @staticmethod
    def _solve_t(k, x1, x2):
        """Binary-search for Bézier parameter t where B_x(t) ≈ k. 20 iterations ≈ 1e-6 precision."""
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) * 0.5
            bx = 3*(1-mid)**2*mid*x1 + 3*(1-mid)*mid**2*x2 + mid**3
            if bx < k: lo = mid
            else: hi = mid
        return (lo + hi) * 0.5

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); box = QRectF(self.rect()).adjusted(2, 2, -2, -2); acc = QColor(UI["ui_accent"])
        p.setPen(QPen(QColor("#2c2c33"), 1)); p.setBrush(QColor("#17171b")); p.drawRoundedRect(box, 12, 12)
        p.setPen(QPen(QColor("#2a2a31"), 1))
        for i in range(1, 4): p.drawLine(self.m(i / 4, -.4), self.m(i / 4, 1.0))
        p.setPen(QPen(QColor("#3a3a44"), 1, Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawRect(QRectF(self.m(0, 1), self.m(1, 0)))
        x1, y1, x2, y2 = self.e; a, b, c, d = self.m(0, 0), self.m(x1, y1), self.m(x2, y2), self.m(1, 1)
        path = QPainterPath(a); path.cubicTo(b, c, d)
        fill = QPainterPath(path); fill.lineTo(self.m(1, 0)); fill.lineTo(self.m(0, 0))
        g = QLinearGradient(0, self.area().top(), 0, self.area().bottom()); ca = QColor(acc); ca.setAlpha(70); cb = QColor(acc); cb.setAlpha(0)
        g.setColorAt(0, ca); g.setColorAt(1, cb); p.setPen(Qt.NoPen); p.setBrush(g); p.drawPath(fill)
        p.setPen(QPen(QColor("#6a6a78"), 1.2)); p.drawLine(a, b); p.drawLine(d, c)
        p.setPen(QPen(acc, 3, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush); p.drawPath(path)
        for q in (b, c):
            gl = QColor("#ffd166"); gl.setAlpha(70); p.setPen(Qt.NoPen); p.setBrush(gl); p.drawEllipse(q, 11, 11)
            p.setBrush(QColor("#ffffff")); p.setPen(QPen(QColor("#ffd166"), 2.4)); p.drawEllipse(q, 5.5, 5.5)
        # Animated ball with smooth binary-search solver
        HOLD = 0.12; ph = self._ph
        k = 0.0 if ph < HOLD else (1.0 if ph > (1.0 - HOLD) else (ph - HOLD) / (1.0 - 2*HOLD))
        if k <= 0.0: yy = 0.0
        elif k >= 1.0: yy = 1.0
        else:
            u = self._solve_t(k, x1, x2)
            yy = 3*(1-u)**2*u*y1 + 3*(1-u)*u**2*y2 + u**3
        tr = QRectF(box.left() + 16, box.bottom() - 15, box.width() - 32, 4)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#2c2c33")); p.drawRoundedRect(tr, 2, 2)
        p.setBrush(acc); p.drawEllipse(QPointF(tr.left() + _clamp_f(yy) * tr.width(), tr.center().y()), 6, 6)

    def mousePressEvent(self, e):
        pos = e.position(); x1, y1, x2, y2 = self.e
        for i, q in enumerate((self.m(x1, y1), self.m(x2, y2))):
            if math.hypot(q.x() - pos.x(), q.y() - pos.y()) < 12: self.drag = i
    def mouseMoveEvent(self, e):
        if self.drag is None: return
        x, y = self.um(e.position()); self.e[self.drag * 2] = round(x, 3); self.e[self.drag * 2 + 1] = round(y, 3)
        self.update(); self.changed.emit(list(self.e))
    def mouseReleaseEvent(self, e): self.drag = None

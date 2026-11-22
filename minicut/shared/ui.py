"""MiniCut's own input widgets. Nothing here is a stock Qt slider / spin box / combo box / check box: every control is painted by
the program, so they all look the same, react the same way and can be restyled in one place (the PAL colours below).

    Slider        drag, wheel (Shift = fine), double-click = back to the default
    NumberField   drag sideways to change the value, click to type it (Enter = OK, Esc = cancel), Shift = fine, Ctrl = coarse
    Dial          a round knob for angles (drag around it, Shift = steps of 15 degrees)
    Toggle        on/off switch with its label
    Dropdown      a button that opens a list of choices
    Segmented     a few choices side by side (like tabs)
    TextField / TextBox   one line / many lines of text (the typing itself is Qt's text engine, so Thai and IME input work)
    Section       a titled card that groups controls that belong together
    Btn           button with an icon and a text
    NavTabs / TabHost   tab strip with icon + label, and the pages below it
    KeyDot        the keyframe diamond
"""
from .deps import *
from .icons import *
from .theme import UI
from PySide6.QtGui import QFontDatabase, QTextDocument


def pal():
    """Colours (read every time, so a changed theme is followed)."""
    return {"card": "#202024", "field": "#2a2a30", "field_h": "#34343c", "line": "#3a3a43", "text": "#ececf1", "dim": "#8e8e9b",
            "accent": UI.get("ui_accent", "#22d3ee"), "accent_d": "#0e5a66", "key": "#ffd166", "danger": "#ff6b6b", "bg": "#1b1b1e"}


LIGHT = {"card": "#ffffff", "field": "#b8ffffff", "field_h": "#dcffffff", "line": "#33000000", "text": "#1f2430", "dim": "#5b6577", "accent": "#0fa5c0", "accent_d": "#a8e8f3", "key": "#d9a000", "danger": "#d64545", "bg": "#ffffff"}


def _p(w):
    """The colours a control uses: light ones for controls that sit on a pastel node, the normal dark ones elsewhere."""
    return LIGHT if getattr(w, "light", False) else pal()


def _font(px, bold=False, base=None):
    f = QFont(base or QApplication.font()); f.setPixelSize(px); f.setBold(bold); return f


def _clamp(v, lo, hi): return max(lo, min(hi, v))


# ---------------------------------------------------- animation helpers (shared by every control) ------------------------------
def anim_to(w, name, target, ms=150, default=0.0, curve=QEasingCurve.OutCubic):
    """Slide the number w._v_<name> to `target` and repaint on every step (hover fades, switch knobs, tab underlines ...)."""
    a = getattr(w, "_a_" + name, None)
    if a is None:
        a = QVariantAnimation(w); setattr(w, "_a_" + name, a)
        def step(v, n=name): setattr(w, "_v_" + n, float(v)); w.update()
        def done(n=name): setattr(w, "_r_" + n, False); w.update()
        a.valueChanged.connect(step); a.finished.connect(done)
    a.stop(); a.setEasingCurve(curve); a.setDuration(ms); a.setStartValue(getattr(w, "_v_" + name, default)); a.setEndValue(float(target)); setattr(w, "_r_" + name, True); a.start()


def anim_val(w, name, default=0.0): return getattr(w, "_v_" + name, default)
def anim_running(w, name): return bool(getattr(w, "_r_" + name, False))


def mixc(a, b, t):
    """Colour between a and b (t = 0..1), alpha included. 'transparent' borrows the other colour so it fades instead of going grey."""
    ca, cb = QColor(a), QColor(b)
    if ca.alpha() == 0: ca = QColor(cb.red(), cb.green(), cb.blue(), 0)
    if cb.alpha() == 0: cb = QColor(ca.red(), ca.green(), ca.blue(), 0)
    t = _clamp(t, 0.0, 1.0); f = lambda x, y: int(round(x + (y - x) * t))
    return QColor(f(ca.red(), cb.red()), f(ca.green(), cb.green()), f(ca.blue(), cb.blue()), f(ca.alpha(), cb.alpha()))


def slide_visible(w, on, ms=230):
    """Show / hide a panel by sliding its height instead of popping (works with a minimum height too)."""
    try:
        a = getattr(w, "_slide", None)
        if a is not None: a.stop()
        BIG = 16777215
        omin = getattr(w, "_orig_min_h", None)
        if omin is None: omin = w._orig_min_h = w.minimumHeight()
        if on and w.isVisible() and w.maximumHeight() >= BIG and not a: return
        if (not on) and not w.isVisible(): return
        if on: nat = max(getattr(w, "_nat_h", 0) or w.sizeHint().height() or 200, omin); w.setMaximumHeight(0); w.setMinimumHeight(0); w.setVisible(True)
        else: nat = max(w.height(), 1); w._nat_h = nat
        def put(v): v = int(v); w.setMinimumHeight(min(omin, v)); w.setMaximumHeight(v)
        a = QVariantAnimation(w); a.setDuration(ms); a.setEasingCurve(QEasingCurve.OutCubic)
        a.setStartValue(0 if on else nat); a.setEndValue(nat if on else 0); a.valueChanged.connect(put)
        def done():
            w.setMinimumHeight(omin); w.setMaximumHeight(BIG)
            if not on: w.setVisible(False)
            w._slide = None
        a.finished.connect(done); w._slide = a; a.start()
    except Exception: w.setVisible(on)


class RoundTip(QWidget):
    """The one tip bubble of the program: rounded, with an arrow when it points at a button, and a TIP badge for a description."""
    _inst = None
    ARROW, PAD = 7, 10
    @classmethod
    def get(cls):
        if cls._inst is None: cls._inst = RoundTip()
        return cls._inst
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating); self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text = ""; self.badge = False; self.arrow = "none"; self.ax = 0; self._owner = None
        self.fade = QPropertyAnimation(self, b"windowOpacity", self); self.fade.setDuration(140)
        self.life = QTimer(self); self.life.setSingleShot(True); self.life.timeout.connect(self.hide_tip)
    def _measure(self):
        fm = QFontMetrics(_font(13)); bw = 38 if self.badge else 0
        r = fm.boundingRect(0, 0, 300 - 2 * self.PAD - bw, 10000, int(Qt.TextWordWrap), self.text)
        self.tw = r.width() + 2; w = self.tw + 2 * self.PAD + bw; h = max(r.height(), 18) + 2 * self.PAD - 4
        self.bw = bw; self.body = QRectF(0.5, (self.ARROW if self.arrow == "up" else 0) + .5, w - 1, h - 1)
        self.setFixedSize(int(w), int(h + (self.ARROW if self.arrow != "none" else 0)))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal()
        path = QPainterPath(); path.addRoundedRect(self.body, 10, 10)
        if self.arrow != "none":
            ax = _clamp(self.ax, 16, self.width() - 16); tri = QPainterPath()
            if self.arrow == "down": y0 = self.body.bottom(); tri.moveTo(ax - self.ARROW, y0 - 1); tri.lineTo(ax, y0 + self.ARROW); tri.lineTo(ax + self.ARROW, y0 - 1)
            else: y0 = self.body.top(); tri.moveTo(ax - self.ARROW, y0 + 1); tri.lineTo(ax, y0 - self.ARROW); tri.lineTo(ax + self.ARROW, y0 + 1)
            tri.closeSubpath(); path = path.united(tri)
        p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor("#26262d")); p.drawPath(path)
        x = self.PAD; cy = self.body.center().y()
        if self.badge:
            pill = QRectF(x, cy - 9, 32, 18); p.setPen(Qt.NoPen); p.setBrush(QColor(c["accent_d"])); p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(c["accent"])); p.setFont(_font(10, True)); p.drawText(pill, Qt.AlignCenter, "TIP"); x += self.bw
        p.setPen(QColor(c["text"])); p.setFont(_font(13)); p.drawText(QRectF(x, self.body.top() + self.PAD - 2, self.tw + 4, self.body.height() - 2 * self.PAD + 4), int(Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap), self.text)
    def _screen(self, pt):
        return QApplication.screenAt(pt) or QApplication.primaryScreen()
    def _show(self, owner, ms):
        self._owner = owner; self._measure(); self.update(); self.setWindowOpacity(0.0); self.show(); self.raise_()
        self.fade.stop(); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start(); self.life.start(ms)
    def show_for(self, w, text, ms=4000):
        """A small bubble above the button, its arrow pointing down at it (below with the arrow up when there is no room)."""
        self.text = text; self.badge = False; self.arrow = "down"; self._measure()
        top = w.mapToGlobal(QPoint(0, 0)); bot = w.mapToGlobal(QPoint(0, w.height())); cx = top.x() + w.width() // 2; scr = self._screen(QPoint(cx, top.y())).availableGeometry()
        x = int(_clamp(cx - self.width() / 2, scr.left() + 4, scr.right() - self.width() - 4)); y = top.y() - self.height() - 3
        if y < scr.top() + 2: self.arrow = "up"; self._measure(); y = bot.y() + 3
        self.ax = cx - x; self.move(x, y); self._show(w, ms)
    def show_at(self, text, gpos, owner=None, ms=7000):
        """A description under the mouse (what Qt calls a tooltip), with the TIP badge in front."""
        self.text = text; self.badge = True; self.arrow = "none"; self._measure(); scr = self._screen(gpos).availableGeometry()
        x = int(_clamp(gpos.x() + 12, scr.left() + 4, scr.right() - self.width() - 4)); y = gpos.y() + 22
        if y + self.height() > scr.bottom() - 4: y = gpos.y() - self.height() - 10
        self.move(x, y); self._show(owner, ms)
    def hide_tip(self): self.fade.stop(); self.hide(); self._owner = None
    def hide_for(self, w):
        if self._owner is w: self.hide_tip()


class TipManager(QObject):
    """Replaces Qt's square tooltips everywhere with RoundTip."""
    def __init__(self, app): super().__init__(app); self.tip = RoundTip.get()
    @staticmethod
    def install(app):
        m = TipManager(app); app.installEventFilter(m); app._tip_manager = m; return m
    def eventFilter(self, o, e):
        t = e.type()
        try:
            if t == QEvent.ToolTip and isinstance(o, QWidget):
                txt = o.toolTip()
                if not txt: return False
                if Qt.mightBeRichText(txt): d = QTextDocument(); d.setHtml(txt); txt = d.toPlainText()
                self.tip.show_at(txt.strip(), e.globalPos(), o); return True
            if t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel, QEvent.KeyPress, QEvent.WindowDeactivate):
                if self.tip.isVisible() and (t != QEvent.Leave or o is self.tip._owner): self.tip.hide_tip()
        except Exception: pass
        return False


class FadeStack(QStackedWidget):
    """A QStackedWidget that cross-fades when the page changes: a picture of the old page fades away over the new one."""
    DUR = 200
    def _fade_from(self, old):
        try:
            if old is None or not self.isVisible() or self.width() < 8 or self.height() < 8: return
            pix = old.grab(); ov = QLabel(self); ov.setPixmap(pix); ov.setScaledContents(True); ov.setGeometry(self.rect()); ov.setAttribute(Qt.WA_TransparentForMouseEvents)
            eff = QGraphicsOpacityEffect(ov); ov.setGraphicsEffect(eff); ov.show(); ov.raise_()
            a = QPropertyAnimation(eff, b"opacity", ov); a.setDuration(self.DUR); a.setStartValue(1.0); a.setEndValue(0.0); a.setEasingCurve(QEasingCurve.OutCubic)
            a.finished.connect(ov.deleteLater); a.start(); ov._a = a
        except Exception: pass
    def setCurrentIndex(self, i):
        old = self.currentWidget() if i != self.currentIndex() else None
        super().setCurrentIndex(i); self._fade_from(old)
    def setCurrentWidget(self, w):
        old = self.currentWidget() if w is not self.currentWidget() else None
        super().setCurrentWidget(w); self._fade_from(old)


def fmt_num(v, dec, suffix=""):
    s = ("%.*f" % (dec, v)) if dec > 0 else ("%d" % round(v))
    if dec > 0 and "." in s: s = s.rstrip("0").rstrip(".") if dec > 1 else s
    return s + suffix


# ======================================================== Slider ========================================================
class Slider(QWidget):
    changed = Signal(float)          # while dragging
    pressed = Signal()
    released = Signal()
    def __init__(self, lo=0.0, hi=100.0, value=0.0, default=None, dec=0, bipolar=None):
        super().__init__(); self.lo, self.hi, self.v = float(lo), float(hi), float(value); self.default = value if default is None else default; self.dec = dec
        self.bipolar = (lo < 0 < hi) if bipolar is None else bipolar; self._drag = False; self._hover = False
        self.setFixedHeight(24); self.setMinimumWidth(50); self.setMouseTracking(True); self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.NoFocus)
    def value(self): return self.v
    def setRange(self, lo, hi): self.lo, self.hi = float(lo), float(hi); self.update()
    def setValue(self, v): self.v = float(v); self.update()
    def setTrack(self, spec):
        """spec = {"stops": [(0..1, colour), ...], "alpha": bool}: the track shows a colour gradient (hue, a fade of opacity ...)."""
        self.track = spec; self.update()
    def _paint_track(self, p, tr, c, cy):
        r = QRectF(8, cy - 5, self.width() - 16, 10); path = QPainterPath(); path.addRoundedRect(r, 5, 5); p.save(); p.setClipPath(path)
        if tr.get("alpha"):                      # a chequer under a see-through gradient
            s = 5.0
            for i in range(int(r.width() // s) + 1):
                for j in range(2): p.fillRect(QRectF(r.left() + i * s, r.top() + j * s, s, s), QColor("#8a8a92" if (i + j) % 2 else "#d0d0d6"))
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        for pos, col in tr["stops"]: g.setColorAt(pos, QColor(col))
        p.fillRect(r, QBrush(g)); p.restore(); p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(0, 0, 0, 110), 1)); p.drawRoundedRect(r, 5, 5)
        x = self._x(self.v)
        if self.bipolar: x0 = self._x(0); p.setPen(QPen(QColor(255, 255, 255, 150), 1)); p.drawLine(QPointF(x0, r.top() - 2), QPointF(x0, r.bottom() + 2))
        p.setPen(Qt.NoPen)
        if self._hover or self._drag: p.setBrush(QColor(34, 211, 238, 50)); p.drawEllipse(QPointF(x, cy), 11, 11)
        p.setPen(QPen(QColor(0, 0, 0, 150), 1.5)); p.setBrush(QColor("#ffffff")); p.drawEllipse(QPointF(x, cy), 6.5, 6.5)
    def _x(self, v): return 8 + _clamp((v - self.lo) / ((self.hi - self.lo) or 1), 0, 1) * (self.width() - 16)
    def _val_at(self, x):
        t = _clamp((x - 8) / max(1, self.width() - 16), 0, 1); v = self.lo + t * (self.hi - self.lo)
        return round(v, self.dec) if self.dec else float(round(v))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); cy = self.height() / 2
        tr = getattr(self, "track", None)
        if tr: self._paint_track(p, tr, c, cy); return
        p.setPen(Qt.NoPen); p.setBrush(QColor(c["field_h"])); p.drawRoundedRect(QRectF(8, cy - 2.5, self.width() - 16, 5), 2.5, 2.5)
        x = self._x(self.v); x0 = self._x(0) if self.bipolar else 8
        p.setBrush(QColor(c["accent"])); p.drawRoundedRect(QRectF(min(x0, x), cy - 2.5, abs(x - x0), 5), 2.5, 2.5)
        if self.bipolar: p.setBrush(QColor(c["dim"])); p.drawRect(QRectF(x0 - 0.5, cy - 5, 1, 10))
        if self._hover or self._drag: p.setBrush(QColor(34, 211, 238, 50)); p.drawEllipse(QPointF(x, cy), 11, 11)
        p.setBrush(QColor("#ffffff")); p.drawEllipse(QPointF(x, cy), 6.5, 6.5)
    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def _set(self, v):
        if v != self.v: self.v = v; self.update(); self.changed.emit(v)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag = True; self.pressed.emit(); self._set(self._val_at(e.position().x()))
    def mouseMoveEvent(self, e):
        if self._drag: self._set(self._val_at(e.position().x()))
    def mouseReleaseEvent(self, e):
        if self._drag: self._drag = False; self.update(); self.released.emit()
    def mouseDoubleClickEvent(self, e): self.pressed.emit(); self._set(float(self.default)); self.released.emit()
    def wheelEvent(self, e):
        step = (self.hi - self.lo) / (400 if e.modifiers() & Qt.ShiftModifier else 40); d = step if e.angleDelta().y() > 0 else -step
        self.pressed.emit(); self._set(_clamp(round(self.v + d, self.dec), self.lo, self.hi)); self.released.emit(); e.accept()


# ====================================================== NumberField =====================================================
class NumberField(QWidget):
    changed = Signal(float)
    finished = Signal()
    def __init__(self, value=0.0, lo=-1e9, hi=1e9, dec=0, suffix="", prefix="", scrub=1.0, width=None):
        super().__init__(); self.v = float(value); self.lo, self.hi, self.dec, self.suffix, self.prefix, self.scrub = lo, hi, dec, suffix, prefix, scrub
        self._press = None; self._moved = False; self._hover = False; self.setFixedHeight(28); self.setMinimumWidth(width or 64); self.setMouseTracking(True)
        self.setCursor(Qt.SizeHorCursor); self.setFocusPolicy(Qt.NoFocus)
        if width: self.setFixedWidth(width)
        self.ed = QLineEdit(self); self.ed.hide(); self.ed.setFrame(False); self.ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ed.setStyleSheet("QLineEdit{background:transparent;border:none;color:#ffffff;selection-background-color:%s;selection-color:#06121a;padding:0 8px;}" % pal()["accent"])
        self.ed.editingFinished.connect(self._commit); self.ed.installEventFilter(self)
    def value(self): return self.v
    def setValue(self, v): self.v = float(v); self.update()
    def setRange(self, lo, hi): self.lo, self.hi = lo, hi
    def setLight(self):
        """Dark text on a pale field (for a node, which is drawn in pastel colours)."""
        self.light = True; self.ed.setStyleSheet("QLineEdit{background:transparent;border:none;color:#1f2430;selection-background-color:#0fa5c0;selection-color:#ffffff;padding:0 8px;}"); self.update(); return self
    def _norm(self, v):
        v = _clamp(v, self.lo, self.hi); return round(v, self.dec) if self.dec else float(round(v))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = _p(self); r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        editing = self.ed.isVisible()
        p.setPen(QPen(QColor(c["accent"]) if editing else QColor(c["line"] if not self._hover else c["dim"]), 1)); p.setBrush(QColor(c["field"] if not self._hover else c["field_h"])); p.drawRoundedRect(r, 7, 7)
        if self.prefix: p.setPen(QColor(c["dim"])); p.setFont(_font(11, True)); p.drawText(QRectF(9, 0, 22, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.prefix)
        if not editing:
            txt = fmt_num(self.v, self.dec); p.setFont(_font(13)); tw = p.fontMetrics().horizontalAdvance(txt)
            p.setPen(QColor(c["text"])); p.drawText(QRectF(0, 0, self.width() - 9 - (p.fontMetrics().horizontalAdvance(self.suffix) + 2 if self.suffix else 0), self.height()), Qt.AlignVCenter | Qt.AlignRight, txt)
            if self.suffix: p.setPen(QColor(c["dim"])); p.setFont(_font(11)); p.drawText(QRectF(0, 0, self.width() - 9, self.height()), Qt.AlignVCenter | Qt.AlignRight, self.suffix)
    def resizeEvent(self, e): self.ed.setGeometry(24 if self.prefix else 0, 1, self.width() - (24 if self.prefix else 0), self.height() - 2)
    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.ed.isVisible(): self._press = (e.globalPosition().x(), self.v); self._moved = False
    def mouseMoveEvent(self, e):
        if self._press is None: return
        dx = e.globalPosition().x() - self._press[0]
        if abs(dx) > 3: self._moved = True
        if self._moved:
            k = self.scrub * (0.1 if e.modifiers() & Qt.ShiftModifier else (10 if e.modifiers() & Qt.ControlModifier else 1))
            nv = self._norm(self._press[1] + dx * k)
            if nv != self.v: self.v = nv; self.update(); self.changed.emit(nv)
    def mouseReleaseEvent(self, e):
        if self._press is None: return
        was_moved = self._moved; self._press = None
        if was_moved: self.finished.emit()
        else: self.edit()
    def mouseDoubleClickEvent(self, e): pass
    def wheelEvent(self, e):
        if not self.underMouse(): return
        k = self.scrub * (0.1 if e.modifiers() & Qt.ShiftModifier else 1) * 3; nv = self._norm(self.v + (k if e.angleDelta().y() > 0 else -k))
        if nv != self.v: self.v = nv; self.update(); self.changed.emit(nv); self.finished.emit()
        e.accept()
    def edit(self):
        self.ed.setText(fmt_num(self.v, self.dec).replace(",", "")); self.ed.show(); self.ed.setFocus(); self.ed.selectAll(); self.setCursor(Qt.IBeamCursor); self.update()
    def eventFilter(self, o, ev):
        if o is self.ed and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape: self._stop_edit(); return True
        return False
    def _stop_edit(self): self.ed.hide(); self.setCursor(Qt.SizeHorCursor); self.update()
    def _commit(self):
        if not self.ed.isVisible(): return
        t = self.ed.text().strip().replace(",", ".")
        self._stop_edit()
        try: nv = self._norm(float(t))
        except ValueError: return
        if nv != self.v: self.v = nv; self.changed.emit(nv)
        self.finished.emit(); self.update()


# ========================================================== Dial ========================================================
class Dial(QWidget):
    """Round knob for an angle in degrees (0 = up, clockwise is positive). The value can go past a full turn."""
    changed = Signal(float)
    finished = Signal()
    def __init__(self, value=0.0, lo=-36000.0, hi=36000.0, size=92):
        super().__init__(); self.v = float(value); self.lo, self.hi = lo, hi; self._last = None; self.setFixedSize(size, size); self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.NoFocus)
    def value(self): return self.v
    def setValue(self, v): self.v = float(v); self.update()
    def _ang(self, pos):
        c = QPointF(self.width() / 2, self.height() / 2); return math.degrees(math.atan2(pos.x() - c.x(), -(pos.y() - c.y())))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); w = self.width(); r = QRectF(8, 8, w - 16, w - 16); ctr = r.center()
        p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawEllipse(r)
        for i in range(24):
            a = math.radians(i * 15); big = i % 6 == 0; r0, r1 = r.width() / 2 - (7 if big else 4), r.width() / 2 - 2
            p.setPen(QPen(QColor(c["dim"] if big else c["line"]), 1.4 if big else 1))
            p.drawLine(QPointF(ctr.x() + r0 * math.sin(a), ctr.y() - r0 * math.cos(a)), QPointF(ctr.x() + r1 * math.sin(a), ctr.y() - r1 * math.cos(a)))
        a_deg = self.v % 360; arc = QRectF(r).adjusted(-4, -4, 4, 4)
        p.setPen(QPen(QColor(c["accent"]), 3.2, Qt.SolidLine, Qt.RoundCap)); p.drawArc(arc, 90 * 16, int(-a_deg * 16))
        a = math.radians(self.v); n = r.width() / 2 - 12; tip = QPointF(ctr.x() + n * math.sin(a), ctr.y() - n * math.cos(a))
        p.setPen(QPen(QColor("#ffffff"), 2.4, Qt.SolidLine, Qt.RoundCap)); p.drawLine(ctr, tip); p.setBrush(QColor("#ffffff")); p.setPen(Qt.NoPen); p.drawEllipse(ctr, 3.5, 3.5)
    def _move(self, pos, snap):
        a = self._ang(pos)
        if self._last is None: self._last = a; return
        d = (a - self._last + 180) % 360 - 180; self._last = a; nv = self.v + d
        if snap: nv = round(nv / 15) * 15
        nv = round(_clamp(nv, self.lo, self.hi), 1)
        if nv != self.v: self.v = nv; self.update(); self.changed.emit(nv)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._last = None; a = self._ang(e.position()); cur = self.v % 360; d = (a - cur + 180) % 360 - 180      # jump to where it was clicked
            nv = round(_clamp(self.v + d, self.lo, self.hi), 1)
            if e.modifiers() & Qt.ShiftModifier: nv = round(nv / 15) * 15
            self._last = a
            if nv != self.v: self.v = nv; self.update(); self.changed.emit(nv)
    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton: self._move(e.position(), bool(e.modifiers() & Qt.ShiftModifier))
    def mouseReleaseEvent(self, e): self._last = None; self.finished.emit()
    def mouseDoubleClickEvent(self, e):
        if self.v != 0: self.v = 0.0; self.update(); self.changed.emit(0.0); self.finished.emit()


# ========================================================= Toggle =======================================================
class Toggle(QWidget):
    toggled = Signal(bool)
    def __init__(self, text="", checked=False, tip=""):
        super().__init__(); self.on = bool(checked); self.text = text; self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.NoFocus); self.setFixedHeight(24)
        if tip: self.setToolTip(tip)
        fm = QFontMetrics(_font(13)); self.setMinimumWidth(40 + (min(fm.horizontalAdvance(text), 120) + 8 if text else 0))
        if len(text) > 18:
            sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); sp.setHeightForWidth(True); self.setSizePolicy(sp)
    def setLight(self): self.light = True; self.update(); return self
    def hasHeightForWidth(self): return bool(self.text)
    def heightForWidth(self, w):
        if not self.text: return 24
        return max(24, QFontMetrics(_font(13)).boundingRect(0, 0, max(40, w - 44), 10000, int(Qt.TextWordWrap), self.text).height() + 6)
    def sizeHint(self): return QSize(self.minimumWidth() if len(self.text) < 18 else 300, self.heightForWidth(300) if self.text else 24)
    def isChecked(self): return self.on
    def setChecked(self, v):
        v = bool(v)
        if v != self.on: self.on = v; anim_to(self, "k", 1.0 if v else 0.0, 170, 0.0 if v else 1.0, QEasingCurve.OutBack)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = _p(self); cy = self.height() / 2; k = anim_val(self, "k", 1.0 if self.on else 0.0)
        off = c["line"] if getattr(self, "light", False) else c["field_h"]
        p.setPen(Qt.NoPen); p.setBrush(mixc(off, c["accent"], k)); p.drawRoundedRect(QRectF(1, cy - 9, 34, 18), 9, 9)
        p.setBrush(mixc("#b9b9c4", "#06121a", k)); p.drawEllipse(QPointF(10 + 17 * k, cy), 6.5 + 0.8 * math.sin(math.pi * _clamp(k, 0, 1)), 6.5 + 0.8 * math.sin(math.pi * _clamp(k, 0, 1)))
        if self.text: p.setPen(QColor(c["text"])); p.setFont(_font(13)); p.drawText(QRectF(44, 0, self.width() - 44, self.height()), int(Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap), self.text)
    def mousePressEvent(self, e): e.accept()
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()): self.on = not self.on; anim_to(self, "k", 1.0 if self.on else 0.0, 170, 0.0 if self.on else 1.0, QEasingCurve.OutBack); self.toggled.emit(self.on)


def _view_of(w):
    """The (proxy, view) a widget lives in when it sits on a node inside the node canvas; (None, None) for a normal widget."""
    try:
        top = w.window(); px = top.graphicsProxyWidget()
        if px is not None and px.scene() is not None and px.scene().views(): return px, px.scene().views()[0]
    except Exception: pass
    return None, None


def _global_pt(w, pt):
    """mapToGlobal that also works for a widget embedded in the node canvas (there mapToGlobal gives a wrong place, so the list never showed)."""
    px, view = _view_of(w)
    if px is None: return w.mapToGlobal(pt)
    p = w.mapTo(w.window(), pt); sp = px.mapToScene(QPointF(p))
    return view.viewport().mapToGlobal(view.mapFromScene(sp))


def _popup_parent(w):
    px, view = _view_of(w)
    return view.window() if view is not None else w.window()


def _place_popup(owner, pop):
    """Open a pop-up under the owner (above it when there is no room), always inside the screen."""
    below = _global_pt(owner, QPoint(0, owner.height() + 3)); above = _global_pt(owner, QPoint(0, -3))
    try: scr = owner.screen().availableGeometry()
    except Exception: scr = QApplication.primaryScreen().availableGeometry()
    y = below.y() if below.y() + pop.height() < scr.bottom() else above.y() - pop.height()
    y = max(scr.top() + 4, min(y, scr.bottom() - pop.height() - 4))
    pop.move(max(scr.left() + 4, min(below.x(), scr.right() - pop.width() - 4)), y)


# ======================================================= Dropdown =======================================================
class _PopupBase(QFrame):
    """Frameless pop-up with real round corners (a see-through window) that fades and slides in."""
    def __init__(self, owner):
        super().__init__(_popup_parent(owner), Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose); self.setAttribute(Qt.WA_TranslucentBackground)
    def paintEvent(self, e):
        # a see-through window has no background of its own, so the rounded card is painted here
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal()
        p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor(c["card"])); p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10)
    def showEvent(self, e):
        super().showEvent(e)
        try:
            end = self.pos(); self.setWindowOpacity(0.0); g = QParallelAnimationGroup(self)
            a = QPropertyAnimation(self, b"windowOpacity", self); a.setDuration(150); a.setStartValue(0.0); a.setEndValue(1.0)
            b = QPropertyAnimation(self, b"pos", self); b.setDuration(190); b.setStartValue(end + QPoint(0, -8)); b.setEndValue(end); b.setEasingCurve(QEasingCurve.OutCubic)
            g.addAnimation(a); g.addAnimation(b); g.start(); self._open_anim = g
        except Exception: self.setWindowOpacity(1.0)


class _DropPopup(_PopupBase):
    picked = Signal(int)
    MAXH = 320
    def __init__(self, owner, items, cur):
        super().__init__(owner); self.setObjectName("DropPop"); c = pal()
        self.setStyleSheet("QFrame#DropPop{background:%s;border:1px solid %s;border-radius:10px;}" % (c["card"], c["line"]))
        outer = QVBoxLayout(self); outer.setContentsMargins(4, 4, 4, 4); outer.setSpacing(0)
        self.sc = QScrollArea(); self.sc.setWidgetResizable(True); self.sc.setFrameShape(QFrame.NoFrame); self.sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sc.setStyleSheet("QScrollArea{background:transparent;border:none;}QScrollArea>QWidget>QWidget{background:transparent;}"
                              "QScrollBar:vertical{background:transparent;width:8px;margin:2px;}QScrollBar::handle:vertical{background:%s;border-radius:3px;min-height:24px;}"
                              "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}" % c["line"])
        inner = QWidget(); inner.setStyleSheet("background:transparent;border:none;"); v = QVBoxLayout(inner); v.setContentsMargins(1, 1, 1, 1); v.setSpacing(1); self._cur_btn = None
        for i, (text, _d) in enumerate(items):
            b = QPushButton(text); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); on = i == cur
            b.setStyleSheet("QPushButton{background:%s;color:%s;border:none;border-radius:6px;text-align:left;padding:6px 12px;font-size:13px;}QPushButton:hover{background:%s;}"
                            % (c["accent_d"] if on else "transparent", "#ffffff" if on else c["text"], c["field_h"]))
            b.clicked.connect(lambda _=False, i=i: (self.picked.emit(i), self.close())); v.addWidget(b)
            if on: self._cur_btn = b
        self.sc.setWidget(inner); outer.addWidget(self.sc)
        sh = inner.sizeHint(); self.sc.setMinimumWidth(sh.width() + 12); self.sc.setFixedHeight(min(self.MAXH, sh.height() + 2))
    def showEvent(self, e):
        super().showEvent(e)
        if self._cur_btn is not None: QTimer.singleShot(0, lambda: self.sc.ensureWidgetVisible(self._cur_btn, 0, 40) if self._cur_btn is not None else None)


class Dropdown(QWidget):
    changed = Signal(int)
    def __init__(self, items=(), width=None):
        super().__init__(); self.items = []; self.cur = -1; self._hover = False; self.setFixedHeight(28); self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.NoFocus); self.setMinimumWidth(width or 90)
        for it in items: self.addItem(*(it if isinstance(it, (tuple, list)) else (it, it)))
    def setLight(self): self.light = True; self.update(); return self
    def addItem(self, text, data=None):
        self.items.append((text, text if data is None else data))
        if self.cur < 0: self.cur = 0
        self.update()
    def addItems(self, texts):
        for t in texts: self.addItem(t)
    def clear(self): self.items = []; self.cur = -1
    def count(self): return len(self.items)
    def currentIndex(self): return self.cur
    def currentData(self): return self.items[self.cur][1] if 0 <= self.cur < len(self.items) else None
    def currentText(self): return self.items[self.cur][0] if 0 <= self.cur < len(self.items) else ""
    def findData(self, d): return next((i for i, (_t, x) in enumerate(self.items) if x == d), -1)
    def setCurrentIndex(self, i):
        if 0 <= i < len(self.items): self.cur = i; self.update()
    def setCurrentData(self, d): self.setCurrentIndex(self.findData(d))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = _p(self); r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        h = anim_val(self, "h", 1.0 if self._hover else 0.0)
        p.setPen(QPen(mixc(c["line"], c["dim"], h), 1)); p.setBrush(mixc(c["field"], c["field_h"], h)); p.drawRoundedRect(r, 7, 7)
        p.setPen(QColor(c["text"])); p.setFont(self._label_font()); p.drawText(QRectF(10, 0, self.width() - 32, self.height()), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.currentText(), Qt.ElideRight, self.width() - 34))
        p.drawPixmap(self.width() - 22, int(self.height() / 2 - 8), svg_pixmap("expand_more", c["dim"], 16))
    def _label_font(self): return _font(13 if self.height() >= 26 else 11)
    def enterEvent(self, e): self._hover = True; anim_to(self, "h", 1.0, 140, 0.0)
    def leaveEvent(self, e): self._hover = False; anim_to(self, "h", 0.0, 200, 1.0)
    def _open_popup(self):
        pop = _DropPopup(self, self.items, self.cur); pop.picked.connect(self._pick); pop.setMinimumWidth(self.width()); pop.adjustSize(); _place_popup(self, pop); pop.show()
    def mousePressEvent(self, e): e.accept()          # a press that is not accepted never gets its release inside the node canvas (QGraphicsProxyWidget), so the list never opened
    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.items: return
        self._open_popup()
    def _pick(self, i):
        if i != self.cur: self.cur = i; self.update(); self.changed.emit(i)


# ===================================================== Font picker ======================================================
class _FontList(QListWidget):
    """The list of fonts: every row shows the font's name written in that font (like CapCut); the star on the right marks a favourite."""
    toggled = Signal(str)
    picked = Signal(str)
    STAR_W = 38
    def mouseReleaseEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        if it is not None and e.button() == Qt.LeftButton:
            fam = it.data(Qt.UserRole)
            if e.position().x() > self.viewport().width() - self.STAR_W: self.toggled.emit(fam)
            else: self.picked.emit(fam)
        e.accept()


class _FontDelegate(QStyledItemDelegate):
    def __init__(self, owner): super().__init__(owner); self.o = owner
    def sizeHint(self, opt, idx): return QSize(10, 34)
    def paint(self, p, opt, idx):
        c = pal(); fam = idx.data(Qt.UserRole); r = QRectF(opt.rect).adjusted(2, 1, -2, -1); hov = bool(opt.state & QStyle.State_MouseOver)
        p.save(); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        on = fam == self.o.current
        if on: p.setBrush(QColor(c["accent_d"])); p.drawRoundedRect(r, 6, 6)
        elif hov: p.setBrush(QColor(c["field_h"])); p.drawRoundedRect(r, 6, 6)
        f = QFont(fam); f.setPixelSize(17); p.setFont(f); p.setPen(QColor("#ffffff" if on else c["text"]))
        p.drawText(QRectF(r.left() + 10, r.top(), r.width() - _FontList.STAR_W - 12, r.height()), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(fam, Qt.ElideRight, int(r.width() - _FontList.STAR_W - 14)))
        fav = fam in self.o.favs
        p.setFont(_font(18)); p.setPen(QColor(c["key"] if fav else c["dim"])); p.drawText(QRectF(r.right() - _FontList.STAR_W, r.top(), _FontList.STAR_W - 4, r.height()), Qt.AlignCenter, "\u2605" if fav else "\u2606")
        p.restore()


class _FontPopup(_PopupBase):
    picked = Signal(str)
    def __init__(self, owner, families, cur, favs, on_fav):
        super().__init__(owner); self.setObjectName("FontPop"); c = pal()
        self.families = list(families); self.current = cur; self.favs = set(favs); self.on_fav = on_fav
        self.setStyleSheet("QFrame#FontPop{background:%s;border:1px solid %s;border-radius:10px;}" % (c["card"], c["line"]))
        v = QVBoxLayout(self); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(6)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search fonts"); self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet("QLineEdit{background:%s;border:1px solid %s;border-radius:7px;color:%s;padding:5px 9px;font-size:13px;}QLineEdit:focus{border-color:%s;}" % (c["field"], c["line"], c["text"], c["accent"]))
        self.search.textChanged.connect(self._fill); v.addWidget(self.search)
        self.lst = _FontList(); self.lst.setFrameShape(QFrame.NoFrame); self.lst.setItemDelegate(_FontDelegate(self)); self.lst.setMouseTracking(True); self.lst.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.lst.setUniformItemSizes(True)
        self.lst.setStyleSheet("QListWidget{background:transparent;border:none;outline:none;}QScrollBar:vertical{background:transparent;width:8px;margin:2px;}"
                               "QScrollBar::handle:vertical{background:%s;border-radius:3px;min-height:24px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}" % c["line"])
        self.lst.picked.connect(lambda f: (self.picked.emit(f), self.close())); self.lst.toggled.connect(self._toggle); v.addWidget(self.lst)
        self.hint = QLabel(""); self.hint.setStyleSheet("color:%s;font-size:11px;padding:0 4px;" % c["dim"]); v.addWidget(self.hint)
        self.setFixedSize(max(300, owner.width()), 380); self._fill()
        self.search.returnPressed.connect(self._pick_first)
    def _fill(self, *_):
        q = self.search.text().strip().lower(); keep = self.lst.verticalScrollBar().value() if self.lst.count() else 0
        fams = [f for f in self.families if q in f.lower()]
        fams = [f for f in fams if f in self.favs] + [f for f in fams if f not in self.favs]       # favourites first
        self.lst.clear()
        for f in fams: it = QListWidgetItem(); it.setData(Qt.UserRole, f); self.lst.addItem(it)
        self.hint.setText("%d fonts  \u00b7  \u2605 = favourite" % len(fams) if fams else "No font found")
        if keep and not q: self.lst.verticalScrollBar().setValue(keep)
    def _toggle(self, fam):
        (self.favs.discard if fam in self.favs else self.favs.add)(fam); self.on_fav(sorted(self.favs)); self._fill()
    def _pick_first(self):
        if self.lst.count(): self.picked.emit(self.lst.item(0).data(Qt.UserRole)); self.close()
    def showEvent(self, e):
        super().showEvent(e); self.search.setFocus()
        def go():                                          # bring the current font into view (when there is no search)
            for i in range(self.lst.count()):
                if self.lst.item(i).data(Qt.UserRole) == self.current: self.lst.scrollToItem(self.lst.item(i), QAbstractItemView.PositionAtCenter); break
        QTimer.singleShot(0, go)


class FontPicker(Dropdown):
    """A font chooser: the pop-up is short, has a search box, a star to keep favourites and shows each name in its own font.
    store = anything with ["fav_fonts"] and save() (the app Settings); favourites are kept there."""
    def __init__(self, families=None, store=None):
        fams = sorted(set(families if families is not None else QFontDatabase.families()), key=str.lower)
        super().__init__([(f, f) for f in fams]); self.store = store
    def _label_font(self):
        f = QFont(self.currentText() or QApplication.font().family()); f.setPixelSize(15); return f
    def favs(self):
        try: return list(self.store["fav_fonts"]) if self.store is not None else list(getattr(self, "_favs", []))
        except Exception: return []
    def _save_favs(self, lst):
        try:
            if self.store is not None: self.store["fav_fonts"] = list(lst); self.store.save()
            else: self._favs = list(lst)
        except Exception: pass
    def _open_popup(self):
        pop = _FontPopup(self, [t for t, _d in self.items], self.currentText(), self.favs(), self._save_favs)
        pop.picked.connect(lambda f: self._pick(self.findData(f))); _place_popup(self, pop); pop.show()


# ======================================================= Segmented ======================================================
class Segmented(QWidget):
    changed = Signal(object)
    def __init__(self, items, value=None):
        super().__init__(); self.items = list(items); self.cur = value if value is not None else (items[0][1] if items else None); self._hov = -1
        self.setFixedHeight(28); self.setMouseTracking(True); self.setCursor(Qt.PointingHandCursor)
    def value(self): return self.cur
    def _idx(self): return next((i for i, (_t, v) in enumerate(self.items) if v == self.cur), -1)
    def _go(self, v):
        old = self._idx(); self.cur = v; new = self._idx()
        if old >= 0 and new >= 0: anim_to(self, "pos", new, 220, old, QEasingCurve.OutCubic)
        self.update()
    def setValue(self, v): self._go(v)
    def _rects(self):
        n = max(1, len(self.items)); w = self.width() / n; return [QRectF(i * w, 0, w, self.height()) for i in range(n)]
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); p.setPen(Qt.NoPen); p.setBrush(QColor(c["field"])); p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        n = max(1, len(self.items)); cw = self.width() / n; ci = self._idx()
        if ci >= 0:
            pos = anim_val(self, "pos", ci) if anim_running(self, "pos") else ci
            p.setBrush(QColor(c["accent_d"])); p.setPen(QPen(QColor(c["accent"]), 1)); p.drawRoundedRect(QRectF(pos * cw, 0, cw, self.height()).adjusted(2, 2, -2, -2), 6, 6)
        for i, (r, (text, val)) in enumerate(zip(self._rects(), self.items)):
            on = val == self.cur; rr = r.adjusted(2, 2, -2, -2)
            if (not on) and i == self._hov: p.setBrush(QColor(c["field_h"])); p.setPen(Qt.NoPen); p.drawRoundedRect(rr, 6, 6)
            p.setPen(QColor("#ffffff" if on else c["dim"])); p.setFont(_font(12, on)); p.drawText(r, Qt.AlignCenter, text)
    def mouseMoveEvent(self, e):
        h = next((i for i, r in enumerate(self._rects()) if r.contains(e.position())), -1)
        if h != self._hov: self._hov = h; self.update()
    def leaveEvent(self, e): self._hov = -1; self.update()
    def mousePressEvent(self, e): e.accept()
    def mouseReleaseEvent(self, e):
        for r, (_t, val) in zip(self._rects(), self.items):
            if r.contains(e.position()) and val != self.cur: self._go(val); self.changed.emit(val); return


# ====================================================== Text inputs =====================================================
class TextField(QWidget):
    textChanged = Signal(str)
    def __init__(self, text="", placeholder=""):
        super().__init__(); self.setFixedHeight(30); self._focus = False
        self.ed = QLineEdit(self); self.ed.setFrame(False); self.ed.setPlaceholderText(placeholder); self.ed.setText(text)
        self.ed.setStyleSheet("QLineEdit{background:transparent;border:none;color:#ececf1;padding:0 10px;selection-background-color:%s;selection-color:#06121a;}" % pal()["accent"])
        self.ed.textChanged.connect(self.textChanged); self.ed.installEventFilter(self)
    def text(self): return self.ed.text()
    def setText(self, t): self.ed.setText(t)
    def resizeEvent(self, e): self.ed.setGeometry(0, 1, self.width(), self.height() - 2)
    def eventFilter(self, o, ev):
        if ev.type() in (QEvent.FocusIn, QEvent.FocusOut): self._focus = ev.type() == QEvent.FocusIn; self.update()
        return False
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal()
        p.setPen(QPen(QColor(c["accent"] if self._focus else c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 7, 7)


class TextBox(QWidget):
    textChanged = Signal()
    def __init__(self, height=84):
        super().__init__(); self.setFixedHeight(height); self._focus = False
        self.ed = QPlainTextEdit(self); self.ed.setFrameShape(QFrame.NoFrame)
        self.ed.setStyleSheet("QPlainTextEdit{background:transparent;border:none;color:#ececf1;padding:6px 8px;selection-background-color:%s;selection-color:#06121a;}" % pal()["accent"])
        self.ed.textChanged.connect(self.textChanged); self.ed.installEventFilter(self)
    def toPlainText(self): return self.ed.toPlainText()
    def setPlainText(self, t): self.ed.setPlainText(t)
    def resizeEvent(self, e): self.ed.setGeometry(1, 1, self.width() - 2, self.height() - 2)
    def eventFilter(self, o, ev):
        if ev.type() in (QEvent.FocusIn, QEvent.FocusOut): self._focus = ev.type() == QEvent.FocusIn; self.update()
        return False
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal()
        p.setPen(QPen(QColor(c["accent"] if self._focus else c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)


# ========================================================= Btn ==========================================================
class Btn(QPushButton):
    """Button with an icon and a text. kind: "ghost" (quiet), "soft" (filled), "accent" (the main action), "danger".
    In toolbar mode (_toolbar=True) the label hides unless the button is hovered or checked/active."""
    def __init__(self, text="", icon=None, kind="soft", tip="", cb=None, checkable=False, h=30):
        super().__init__(); self.label = text; self.ic = icon; self.kind = kind; self._h = h; self.setCheckable(checkable); self.setFocusPolicy(Qt.NoFocus); self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(h); self._toolbar = False; self.bubble = False
        if tip: self.setToolTip(tip)
        if cb: self.clicked.connect(cb)
        fm = QFontMetrics(_font(13, True)); self._full = 10 + (22 if icon else 0) + (fm.horizontalAdvance(text) + 4 if text else 0); self._compact = False; self.setMinimumWidth(self._full)
    def fullWidth(self): return self._full + 8
    def setCompact(self, c):
        """Icon only (used when the toolbar is too narrow for the words)."""
        c = bool(c) and bool(self.ic) and bool(self.label)
        if c != self._compact: self._compact = c; self.setMinimumWidth(34 if c else self._full); self.updateGeometry(); self.update()
    def setToolbarMode(self, on):
        """In toolbar mode the label is hidden unless hovered or active; always shows when no icon."""
        self._toolbar = bool(on) and bool(self.ic) and bool(self.label)
        self.setMinimumWidth(34 if self._toolbar else self._full); self.updateGeometry(); self.update()
    def _show_label(self):
        """Whether the text label should be rendered right now."""
        if self._compact: return False
        if self._toolbar: return False                   # the name is shown in a small bubble above the button instead
        return bool(self.label)
    def sizeHint(self):
        if self._compact: return QSize(34 + 8, self._h)
        if self._toolbar: return QSize(34 + 8, self._h)
        return QSize(self._full + 8, self._h)
    def enterEvent(self, e):
        anim_to(self, "h", 1.0, 130, 0.0)
        if getattr(self, "bubble", False) or self._toolbar: QTimer.singleShot(90, self._bubble_now)
        super().enterEvent(e)
    def leaveEvent(self, e):
        anim_to(self, "h", 0.0, 220, 1.0); RoundTip.get().hide_for(self)
        super().leaveEvent(e)
    def _bubble_now(self):
        try:
            if not (self.underMouse() and self.isVisible()): return
            name = self.label or (self.toolTip() or "").split("\n")[0]
            if name: RoundTip.get().show_for(self, name)
        except RuntimeError: pass
    def setIconName(self, n): self.ic = n; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5); on = self.isChecked(); en = self.isEnabled()
        down = self.isDown(); h = anim_val(self, "h", 1.0 if (self.underMouse() and en) else 0.0) if en else 0.0
        def look(hov):
            if self.kind == "accent": return (c["accent"] if not hov else "#4ae0f5"), "#06121a", c["accent"]
            if self.kind == "danger": return (c["field"] if not hov else "#4a2a2e"), c["danger"], c["line"]
            if self.kind == "ghost": return (c["field_h"] if hov else "transparent"), c["text"], "transparent"
            return (c["field_h"] if hov else c["field"]), c["text"], c["line"]
        (b0, fg, br0), (b1, _f1, br1) = look(False), look(True)
        bg, br = mixc(b0, b1, h), mixc(br0, br1, h)
        if on: bg, fg, br = QColor(c["accent_d"]), "#ffffff", QColor(c["accent"])
        if down: bg = QColor(c["field_h"] if self.kind != "accent" else "#1aa9c0"); r = r.adjusted(1, 1, -1, -1)         # a small push when pressed
        if not en: fg = "#5d6476"
        p.setPen(QPen(QColor(br), 1)); p.setBrush(QColor(bg)); p.drawRoundedRect(r, 8, 8)
        show_lbl = self._show_label()
        fm = QFontMetrics(_font(13, True)); tw = fm.horizontalAdvance(self.label) if show_lbl else 0; iw = 18 if self.ic else 0; gap = 6 if (self.ic and show_lbl) else 0
        x = (self.width() - (tw + iw + gap)) / 2
        if self.ic: p.drawPixmap(int(x), int(self.height() / 2 - 9), svg_pixmap(self.ic, fg, 18)); x += iw + gap
        if show_lbl: p.setPen(QColor(fg)); p.setFont(_font(13, True)); p.drawText(QRectF(x, 0, tw + 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)


# ======================================================= Section ========================================================
class Section(QFrame):
    """A titled card. Put the controls of one subject in it, so related things sit together."""
    def __init__(self, title, icon=None, right=None):
        super().__init__(); self.setObjectName("Sec"); self.setStyleSheet("QFrame#Sec{background:%s;border:1px solid #2c2c33;border-radius:12px;}" % pal()["card"])
        v = QVBoxLayout(self); v.setContentsMargins(12, 10, 12, 12); v.setSpacing(8)
        self.head = QHBoxLayout(); self.head.setSpacing(6)
        if icon: self.head.addWidget(icon_label(icon, "#8e8e9b", 16))
        t = QLabel(title); t.setStyleSheet("color:#c9c9d3;font-weight:700;font-size:12px;background:transparent;border:none;"); self.title = t; self.head.addWidget(t); self.head.addStretch(1)
        if right is not None: self.head.addWidget(right)
        v.addLayout(self.head); self.body = QVBoxLayout(); self.body.setSpacing(8); self.body.setContentsMargins(0, 0, 0, 0); v.addLayout(self.body)
    def addRight(self, w): self.head.addWidget(w)


def label(text, dim=True, px=12):
    l = QLabel(text); l.setStyleSheet("color:%s;font-size:%dpx;background:transparent;border:none;" % (pal()["dim"] if dim else pal()["text"], px)); return l


# ======================================================= KeyDot =========================================================
class KeyDot(QWidget):
    """Keyframe diamond: grey = no keyframes, cyan = this property is animated, yellow = a keyframe sits at the playhead."""
    clicked = Signal()
    def __init__(self):
        super().__init__(); self.state = 0; self.setFixedSize(22, 22); self.setCursor(Qt.PointingHandCursor); self.setToolTip("Keyframe: add / remove at the playhead")
    def setState(self, on, any_): self.state = 2 if on else (1 if any_ else 0); self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); col = {0: "#4a4a54", 1: c["accent"], 2: c["key"]}[self.state]
        cx, cy, r = self.width() / 2, self.height() / 2, 5.5; poly = QPolygonF([QPointF(cx, cy - r), QPointF(cx + r, cy), QPointF(cx, cy + r), QPointF(cx - r, cy)])
        p.setPen(QPen(QColor(col), 1.4)); p.setBrush(QColor(col) if self.state == 2 else Qt.NoBrush); p.drawPolygon(poly)
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit()


# ======================================================= Tabs ===========================================================
class NavTabs(QWidget):
    """Tabs with an icon and a word. Horizontal: icon above the word (side panels). Items are (icon, text, tooltip)."""
    changed = Signal(int)
    def __init__(self, items, h=52, line=True):
        super().__init__(); self.items = list(items); self.cur = 0; self.vis = [True] * len(self.items); self._hov = -1; self.line = line
        self.setFixedHeight(h); self.setMouseTracking(True); self.setCursor(Qt.PointingHandCursor)
    def go(self, i):
        """Move the underline to tab i (animated) and make it the current one."""
        if 0 <= i < len(self.items) and i != self.cur: anim_to(self, "ci", i, 240, self.cur, QEasingCurve.OutCubic)
        self.cur = i; self.update()
    def _cx(self, f):
        R = self._rects(); lo = int(math.floor(f)); t = f - lo; a, b = R.get(lo), R.get(lo + 1)
        if a is not None and b is not None: return a.center().x() * (1 - t) + b.center().x() * t
        r = R.get(int(round(f))) or R.get(self.cur); return r.center().x() if r is not None else 0.0
    def setCurrent(self, i):
        if 0 <= i < len(self.items) and i != self.cur: self.go(i); self.changed.emit(i)
    def setTabVisible(self, i, v):
        if self.vis[i] != v: self.vis[i] = v; self.update()
    def _rects(self):
        idx = [i for i, v in enumerate(self.vis) if v]; n = max(1, len(idx)); w = self.width() / n
        return {i: QRectF(k * w, 0, w, self.height()) for k, i in enumerate(idx)}
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal()
        if self.line: p.setPen(QPen(QColor("#2c2c33"), 1)); p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        for i, r in self._rects().items():
            ic, text, _tip = self.items[i]; on = i == self.cur; col = c["accent"] if on else (c["text"] if i == self._hov else c["dim"])
            p.drawPixmap(int(r.center().x() - 11), int(r.top() + 6), svg_pixmap(ic, col, 22)); p.setPen(QColor(col)); p.setFont(_font(11, on))
            p.drawText(QRectF(r.left(), r.top() + 30, r.width(), 18), Qt.AlignHCenter | Qt.AlignTop, text)
        if self.cur in self._rects():
            cx = self._cx(anim_val(self, "ci", self.cur)) if anim_running(self, "ci") else self._rects()[self.cur].center().x()
            p.setPen(Qt.NoPen); p.setBrush(QColor(c["accent"])); p.drawRoundedRect(QRectF(cx - 14, self.height() - 3, 28, 3), 1.5, 1.5)
    def mouseMoveEvent(self, e):
        h = next((i for i, r in self._rects().items() if r.contains(e.position())), -1)
        if h != self._hov: self._hov = h; self.update(); self.setToolTip(self.items[h][2] if h >= 0 else "")
    def leaveEvent(self, e): self._hov = -1; self.update()
    def mouseReleaseEvent(self, e):
        for i, r in self._rects().items():
            if r.contains(e.position()): self.setCurrent(i); return


class TabHost(QWidget):
    """NavTabs + the pages. Same calls as a QTabWidget (addTab, setTabVisible, setCurrentIndex ...)."""
    currentChanged = Signal(int)
    def __init__(self):
        super().__init__(); v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0); self.nav = NavTabs([]); self.stack = FadeStack(); v.addWidget(self.nav); v.addWidget(self.stack, 1)
        self.nav.changed.connect(self._ch)
    def addTab(self, page, text, icon="adjust", tip=""):
        self.nav.items.append((icon, text, tip or text)); self.nav.vis.append(True); self.stack.addWidget(page); self.nav.update(); return self.stack.count() - 1
    def _ch(self, i): self.stack.setCurrentIndex(i); self.currentChanged.emit(i)
    def setCurrentIndex(self, i):
        if self.nav.vis[i]: self.nav.go(i); self.stack.setCurrentIndex(i); self.currentChanged.emit(i)
    def currentIndex(self): return self.nav.cur
    def setTabVisible(self, i, v):
        self.nav.setTabVisible(i, v)
        if not v and self.nav.cur == i:
            j = next((k for k, x in enumerate(self.nav.vis) if x), 0); self.setCurrentIndex(j)
    def isTabVisible(self, i): return self.nav.vis[i]


# ================================================ drop-in replacements ==================================================
# The dialogs were written with the stock Qt controls. These have the same calls but are drawn by the program, so
# a dialog only has to say  QSpinBox = SpinBox  to get the same look as the rest of the program.
class SpinBox(NumberField):
    valueChanged = Signal(float)
    editingFinished = Signal()
    def __init__(self):
        super().__init__(0, 0, 100, 0, "", "", 1.0); self.changed.connect(self.valueChanged); self.finished.connect(self.editingFinished)
    def setSuffix(self, t): self.suffix = t; self.update()
    def setSingleStep(self, v): self.scrub = float(v); 
    def setDecimals(self, n): self.dec = int(n); self.update()
    def setKeyboardTracking(self, v): pass
    def setValue(self, v): self.v = float(v); self.update()
    def value(self): return int(round(self.v)) if self.dec == 0 else self.v
    def setMinimum(self, v): self.lo = v
    def setMaximum(self, v): self.hi = v
    def setAlignment(self, a): pass
    def setPrefix(self, t): self.prefix = t; self.update()


class DoubleSpinBox(SpinBox):
    def __init__(self): super().__init__(); self.dec = 2; self.scrub = 0.1
    def value(self): return float(self.v)


class ComboBox(Dropdown):
    currentIndexChanged = Signal(int)
    activated = Signal(int)
    def __init__(self, *a): super().__init__(); self.changed.connect(self.currentIndexChanged); self.changed.connect(self.activated)
    def setCurrentText(self, t):
        i = next((k for k, (x, _d) in enumerate(self.items) if x == t), -1); self.setCurrentIndex(i)
    def setEditable(self, v): pass
    def setMaxVisibleItems(self, n): pass
    def itemText(self, i): return self.items[i][0]
    def itemData(self, i): return self.items[i][1]


class CheckBox(Toggle):
    def __init__(self, text="", *a): super().__init__(text, False)
    def setText(self, t): self.text = t; self.update()
    def setTristate(self, v): pass


class IntSlider(Slider):
    """A Slider with the calls of the old integer slider (setRange / value / valueChanged)."""
    valueChanged = Signal(int)
    def __init__(self, *a): super().__init__(0, 100, 0, 0, 0); self.changed.connect(lambda v: self.valueChanged.emit(int(round(v))))
    def value(self): return int(round(self.v))
    def setValue(self, v): self.v = float(v); self.update()
    def setFocusPolicy(self, p): pass

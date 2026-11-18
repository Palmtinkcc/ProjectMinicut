"""Touch support (Windows tablet). One app-wide event filter, installed by touch.install(app).

A widget takes part by setting `touch_ok = True` (the filter then turns on touch events for it when it is shown) and, optionally:
    touch_menu = True               a long press (0.55 s, finger not moving) opens the widget's context menu
    touch_pinch(factor, pos)        two fingers: zoom by `factor` around `pos`  (pos in the widget's / view's viewport coordinates)
    touch_pan(dx, dy)               two fingers: the middle point moved by dx, dy pixels
One finger = the normal left mouse button (press / move / release); two quick taps = double click. A small jitter of the finger
(under 8 px) does not start a drag, so a tap stays a tap. Widgets without `touch_ok` are not touched: Qt's own touch -> mouse handling stays.
"""
import math
from PySide6.QtCore import Qt, QObject, QEvent, QPointF, QPoint, QTimer, QElapsedTimer
from PySide6.QtGui import QMouseEvent, QContextMenuEvent, QEventPoint, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QAbstractScrollArea

SLOP = 8.0                  # px the finger may move before it counts as a drag
LONG_MS = 550               # long press = context menu
DBL_MS, DBL_PX = 400, 30    # two taps this close in time / place = double click
_TOUCH = (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel)


def view_pinch(v, f, pos):
    """Zoom a QGraphicsView by f around viewport point pos (limits 0.25 .. 2.5, the same as the wheel)."""
    cur = v.transform().m11()
    if cur <= 0: return
    f = max(0.25 / cur, min(2.5 / cur, f))
    if abs(f - 1.0) < 1e-4: return
    p = pos.toPoint(); before = v.mapToScene(p)
    anchor = v.transformationAnchor(); v.setTransformationAnchor(v.ViewportAnchor.NoAnchor); v.scale(f, f); v.setTransformationAnchor(anchor)
    q = v.mapFromScene(before)
    v.horizontalScrollBar().setValue(v.horizontalScrollBar().value() + q.x() - p.x())
    v.verticalScrollBar().setValue(v.verticalScrollBar().value() + q.y() - p.y())


def view_pan(v, dx, dy):
    v.horizontalScrollBar().setValue(int(v.horizontalScrollBar().value() - dx))
    v.verticalScrollBar().setValue(int(v.verticalScrollBar().value() - dy))


class TouchFilter(QObject):
    def __init__(self):
        super().__init__(); self.st = {}; self.tap = {}; self.clock = QElapsedTimer(); self.clock.start()

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _owner(w):
        for _ in range(4):
            if w is None: return None
            if getattr(w, "touch_ok", False): return w
            w = w.parentWidget()
        return None

    @staticmethod
    def _mouse(obj, typ, pos, button, buttons):
        gp = QPointF(obj.mapToGlobal(pos.toPoint())); mods = QGuiApplication.keyboardModifiers()
        try: ev = QMouseEvent(typ, pos, pos, gp, button, buttons, mods)
        except TypeError: ev = QMouseEvent(typ, pos, gp, button, buttons, mods)
        QApplication.sendEvent(obj, ev)

    def _release(self, obj, s):
        if s["down"]:
            s["down"] = False; self._mouse(obj, QEvent.MouseButtonRelease, s["last"], Qt.LeftButton, Qt.NoButton)

    def _long(self, obj, key):
        s = self.st.get(key)
        if not s or not s["down"] or s["moved"] or s["gesture"]: return
        s["long"] = True; self._release(obj, s); pos = s["last"].toPoint()
        QApplication.sendEvent(obj, QContextMenuEvent(QContextMenuEvent.Mouse, pos, obj.mapToGlobal(pos)))

    # ---------------------------------------------------------------- the filter
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Show:
            if isinstance(obj, QWidget) and getattr(obj, "touch_ok", False):
                obj.setAttribute(Qt.WA_AcceptTouchEvents, True)
                if isinstance(obj, QAbstractScrollArea): obj.viewport().setAttribute(Qt.WA_AcceptTouchEvents, True)
            return False
        if t not in _TOUCH or not isinstance(obj, QWidget): return False
        owner = self._owner(obj)
        if owner is None: return False
        self._touch(obj, owner, ev); ev.accept(); return True

    def _touch(self, obj, owner, ev):
        key = id(obj); t = ev.type()
        s = self.st.get(key)
        if s is None or t == QEvent.TouchBegin:
            if s and s.get("timer"): s["timer"].stop()
            s = self.st[key] = {"pts": {}, "down": False, "began": False, "moved": False, "long": False, "gesture": False, "p0": QPointF(), "last": QPointF(), "d": 1.0, "c": QPointF(), "timer": None}
        for p in ev.points():
            if t == QEvent.TouchCancel or p.state() == QEventPoint.State.Released: s["pts"].pop(p.id(), None)
            else: s["pts"][p.id()] = QPointF(p.position())
        n = len(s["pts"])

        if s["gesture"]:                                             # two (or more) fingers: zoom + pan; stays so until every finger is up
            if n >= 2: self._gesture(obj, owner, s, False)
            elif n == 0: self._end(key, s)
            return
        if n >= 2:                                                   # a second finger: drop the press, start the gesture
            if s["timer"]: s["timer"].stop()
            self._release(obj, s)
            if hasattr(owner, "touch_pinch") or hasattr(owner, "touch_pan"): s["gesture"] = True; self._gesture(obj, owner, s, True)
            else: s["gesture"] = True
            return
        if n == 1:
            pos = next(iter(s["pts"].values()))
            if not s["began"]:                                       # first contact = left press (a second quick tap = double click)
                s["began"] = True; s["down"] = True; s["p0"] = pos; s["last"] = pos
                prev = self.tap.get(key); now = self.clock.elapsed()
                dbl = prev is not None and now - prev[0] <= DBL_MS and math.hypot(pos.x() - prev[1].x(), pos.y() - prev[1].y()) <= DBL_PX
                self.tap[key] = None if dbl else (now, pos)
                self._mouse(obj, QEvent.MouseButtonDblClick if dbl else QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton)
                if getattr(owner, "touch_menu", False) and not dbl:
                    tm = QTimer(self); tm.setSingleShot(True); tm.timeout.connect(lambda o=obj, k=key: self._long(o, k)); tm.start(LONG_MS); s["timer"] = tm
            elif s["down"]:
                if not s["moved"] and math.hypot(pos.x() - s["p0"].x(), pos.y() - s["p0"].y()) > SLOP:
                    s["moved"] = True
                    if s["timer"]: s["timer"].stop()
                if s["moved"]: s["last"] = pos; self._mouse(obj, QEvent.MouseMove, pos, Qt.NoButton, Qt.LeftButton)
            return
        # n == 0: every finger is up
        if s["timer"]: s["timer"].stop()
        if s["down"] and not s["long"]: self._release(obj, s)
        self._end(key, s)

    def _end(self, key, s):
        if s.get("timer"): s["timer"].stop()
        self.st.pop(key, None)

    def _gesture(self, obj, owner, s, first):
        a, b = list(s["pts"].values())[:2]; c = (a + b) / 2.0; d = max(1.0, math.hypot(a.x() - b.x(), a.y() - b.y()))
        if not first:
            f = d / max(1.0, s["d"]); dc = c - s["c"]
            tgt = owner.viewport() if isinstance(owner, QAbstractScrollArea) else owner
            cp = c if tgt is obj else QPointF(tgt.mapFromGlobal(obj.mapToGlobal(c.toPoint())))
            if hasattr(owner, "touch_pan") and (abs(dc.x()) > 0 or abs(dc.y()) > 0): owner.touch_pan(dc.x(), dc.y())
            if hasattr(owner, "touch_pinch") and abs(f - 1.0) > 0.002: owner.touch_pinch(f, cp)
        s["d"] = d; s["c"] = c


_FILTER = [None]


def install(app=None):
    """Turn touch support on for the whole program (call once, after the QApplication exists)."""
    if _FILTER[0] is not None: return
    app = app or QApplication.instance(); f = TouchFilter(); app.installEventFilter(f); _FILTER[0] = f

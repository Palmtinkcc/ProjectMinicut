"""Round controls for effect parameters (Patch 47).

The effect card used a plain slider for every number. Angles are now dials (like the rotation dial of the Basic tab, but small),
the speed of a turn (deg / s) is a speed wheel, and the three 3D objects (Cube, Card, Sphere, Cylinder) get a small box that you
drag to tilt and turn it, shown in the same position the result has. Angles that belong together share one row.

  plan(typ, params)  ->  what to build, in order: ("std", prm) = the normal slider row, ("cells", None, [cell, ...]) = one row of round controls
  build(panel, v, e, info, item)  adds that row to the card (any error: the card falls back to the normal rows)

A cell is ("dial", prm), ("wheel", prm) or ("box", [prm_rx, prm_ry]); prm = (key, label, kind, default, lo, hi) as in the effect list.
"""
import math, re
import numpy as np
from ..shared.deps import *
from ..shared.ui import pal, _clamp, _font, Dial, NumberField, KeyDot

_ANGLE_LABELS = {"angle", "direction", "rotate", "rotation", "start angle", "tilt", "tilt x", "turn y", "roll", "light direction", "shift direction", "twist"}
_SPIN = re.compile(r"\(deg\s*/\s*s\)", re.I)
_BOX_KEYS = ("rx", "ry")
_VERT = np.array([[-.5, -.5, -.5], [.5, -.5, -.5], [.5, .5, -.5], [-.5, .5, -.5], [-.5, -.5, .5], [.5, -.5, .5], [.5, .5, .5], [-.5, .5, .5]], np.float32)
_FACES = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]      # the same faces, in the same order, as the Cube effect


def _rot(ax, ay, az):
    """The same rotation the 3D effects use (render/fxpack/particle.py)."""
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    return np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])


def is_spin(label): return bool(_SPIN.search(label or ""))


def is_angle(label, kind, lo, hi):
    return kind in ("float", "int") and (label or "").strip().lower() in _ANGLE_LABELS and round(float(hi) - float(lo)) in (360, 720, 1440)


def cell_params(cell):
    return list(cell[1]) if cell[0] == "box" else [cell[1]]


def plan(typ, params):
    """The card is built in this order: normal rows stay as they are; angles and spin speeds that follow each other become one row
    of round controls (at most three per row)."""
    keys = {p[0] for p in params}; box = all(k in keys for k in _BOX_KEYS) and any(p[1].strip().lower() == "roll" for p in params)
    items, cells = [], []

    def flush():
        for i in range(0, len(cells), 3): items.append(("cells", None, cells[i:i + 3]))
        del cells[:]
    for prm in params:
        key, label_, kind, dflt, lo, hi = prm
        if box and key in _BOX_KEYS:
            if key == _BOX_KEYS[0]: cells.append(("box", [p for p in params if p[0] in _BOX_KEYS]))
            continue
        if kind in ("float", "int") and is_spin(label_): cells.append(("wheel", prm)); continue
        if is_angle(label_, kind, lo, hi): cells.append(("dial", prm)); continue
        flush(); items.append(("std", prm))
    flush(); return items


# =================================================================================================== widgets
class MiniDial(Dial):
    """The rotation dial of the Basic tab, small. Same behaviour (drag, click to jump, Shift = 15 degree steps, double click = default)."""
    def __init__(self, value=0.0, lo=-36000.0, hi=36000.0, size=54, default=0.0):
        super().__init__(value, lo, hi, size); self.dflt = float(default)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); w = self.width(); m = max(3.0, w * 0.07)
        r = QRectF(m, m, w - 2 * m, w - 2 * m); ctr = r.center(); R = r.width() / 2
        p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawEllipse(r)
        for i in range(12):
            a = math.radians(i * 30); big = i % 3 == 0; r0, r1 = R - (R * 0.28 if big else R * 0.16), R - 1.5
            p.setPen(QPen(QColor(c["dim"] if big else c["line"]), 1.3 if big else 1))
            p.drawLine(QPointF(ctr.x() + r0 * math.sin(a), ctr.y() - r0 * math.cos(a)), QPointF(ctr.x() + r1 * math.sin(a), ctr.y() - r1 * math.cos(a)))
        a_deg = self.v % 360; arc = QRectF(r).adjusted(-m * 0.45, -m * 0.45, m * 0.45, m * 0.45)
        p.setPen(QPen(QColor(c["accent"]), max(2.4, w * 0.055), Qt.SolidLine, Qt.RoundCap)); p.drawArc(arc, 90 * 16, int(-a_deg * 16))
        a = math.radians(self.v); n = R - R * 0.34; tip = QPointF(ctr.x() + n * math.sin(a), ctr.y() - n * math.cos(a))
        p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap)); p.drawLine(ctr, tip)
        p.setBrush(QColor("#ffffff")); p.setPen(Qt.NoPen); p.drawEllipse(ctr, 2.8, 2.8)
    def mouseDoubleClickEvent(self, e):
        if self.v != self.dflt: self.v = self.dflt; self.update(); self.changed.emit(self.dflt); self.finished.emit()


class SpeedWheel(QWidget):
    """Turn speed in degrees per second. OUTER ring: drag it to set the speed (top = still, clockwise = faster, counter-clockwise = reverse).
    INNER disc: shows how far it has turned by now (clip time x speed): a needle and the angle."""
    changed = Signal(float)
    finished = Signal()
    SWEEP = 150.0
    def __init__(self, value=0.0, lo=-360.0, hi=360.0, size=66, default=0.0, phase_fn=None):
        super().__init__(); self.v = float(value); self.lo, self.hi = float(lo), float(hi); self.dflt = float(default); self.phase_fn = phase_fn
        self._drag = False; self._shown = None; self.setFixedSize(size, size); self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.NoFocus)
        self._tm = QTimer(self); self._tm.timeout.connect(self._tick)
    def value(self): return self.v
    def setValue(self, v): self.v = _clamp(float(v), self.lo, self.hi); self.update()
    def vmax(self): return max(abs(self.lo), abs(self.hi), 1e-6)
    def phase(self):
        try: lt = float(self.phase_fn()) if self.phase_fn else 0.0
        except Exception: lt = 0.0
        return (lt * self.v) % 360.0
    def showEvent(self, e): self._tm.start(80)
    def hideEvent(self, e): self._tm.stop()
    def _tick(self):
        ph = round(self.phase())
        if ph != self._shown: self._shown = ph; self.update()
    def _ring_ang(self):
        return _clamp(self.v / self.vmax() * self.SWEEP, -self.SWEEP, self.SWEEP)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); w = self.width(); R = w / 2 - 2.0; ctr = QPointF(w / 2, w / 2)
        ring = max(5.0, w * 0.11); rr = R - ring / 2
        p.setPen(QPen(QColor(c["line"]), ring, Qt.SolidLine, Qt.FlatCap)); p.setBrush(Qt.NoBrush); p.drawEllipse(ctr, rr, rr)
        ang = self._ring_ang(); rect = QRectF(ctr.x() - rr, ctr.y() - rr, 2 * rr, 2 * rr)
        p.setPen(QPen(QColor(c["accent"]), ring, Qt.SolidLine, Qt.RoundCap)); p.drawArc(rect, 90 * 16, int(-ang * 16))
        p.setPen(QPen(QColor(c["dim"]), 1.4)); p.drawLine(QPointF(ctr.x(), ctr.y() - R), QPointF(ctr.x(), ctr.y() - R + ring))             # the "still" mark
        a = math.radians(ang); hp = QPointF(ctr.x() + rr * math.sin(a), ctr.y() - rr * math.cos(a))
        p.setPen(QPen(QColor(c["accent_d"]), 1.2)); p.setBrush(QColor("#ffffff")); p.drawEllipse(hp, ring * 0.62, ring * 0.62)
        rin = R - ring - 2.5; p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawEllipse(ctr, rin, rin)
        for i in range(8):
            t = math.radians(i * 45); r0, r1 = rin - (rin * 0.2 if i % 2 == 0 else rin * 0.12), rin - 1
            p.setPen(QPen(QColor(c["dim"] if i % 2 == 0 else c["line"]), 1)); p.drawLine(QPointF(ctr.x() + r0 * math.sin(t), ctr.y() - r0 * math.cos(t)), QPointF(ctr.x() + r1 * math.sin(t), ctr.y() - r1 * math.cos(t)))
        ph = self.phase(); t = math.radians(ph); n = rin * 0.72
        p.setPen(QPen(QColor("#ffffff"), 1.8, Qt.SolidLine, Qt.RoundCap)); p.drawLine(ctr, QPointF(ctr.x() + n * math.sin(t), ctr.y() - n * math.cos(t)))
        tr = QRectF(ctr.x() - rin * 0.62, ctr.y() + rin * 0.30, rin * 1.24, rin * 0.46); p.setPen(Qt.NoPen); p.setBrush(QColor(c["bg"])); p.drawRoundedRect(tr, 5, 5)      # the angle sits on a small plate so the needle does not cross it
        p.setPen(QColor(c["text"])); p.setFont(_font(max(8, int(w * 0.15)), True)); p.drawText(tr, Qt.AlignCenter, "%d\u00b0" % round(ph))
    def _set_from(self, pos, snap):
        dx, dy = pos.x() - self.width() / 2, pos.y() - self.height() / 2
        ang = math.degrees(math.atan2(dx, -dy))                         # 0 = up, clockwise positive
        ang = _clamp(ang, -self.SWEEP, self.SWEEP); v = ang / self.SWEEP * self.vmax()
        if snap: v = round(v / 15.0) * 15.0
        v = round(_clamp(v, self.lo, self.hi), 1)
        if v != self.v: self.v = v; self.update(); self.changed.emit(v)
    def _on_ring(self, pos):
        d = math.hypot(pos.x() - self.width() / 2, pos.y() - self.height() / 2); R = self.width() / 2
        return d >= R * 0.56
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._on_ring(e.position()): self._drag = True; self._set_from(e.position(), bool(e.modifiers() & Qt.ShiftModifier))
    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.LeftButton: self._set_from(e.position(), bool(e.modifiers() & Qt.ShiftModifier))
    def mouseReleaseEvent(self, e):
        if self._drag: self._drag = False; self.finished.emit()
    def wheelEvent(self, e):
        step = 5.0 if e.angleDelta().y() > 0 else -5.0; v = round(_clamp(self.v + step, self.lo, self.hi), 1)
        if v != self.v: self.v = v; self.update(); self.changed.emit(v); self.finished.emit()
    def mouseDoubleClickEvent(self, e):
        if self.v != self.dflt: self.v = self.dflt; self.update(); self.changed.emit(self.dflt); self.finished.emit()


class Box3D(QWidget):
    """A small box for Tilt X and Turn Y. Drag it: it turns the way the result turns (it is drawn with the same rotation and the same faces
    as the Cube effect, including the current spin). A white dot marks the top-left corner of the picture on each face."""
    changed = Signal(float, float)
    finished = Signal()
    def __init__(self, rx=15.0, ry=25.0, rz=0.0, size=76, defaults=(15.0, 25.0), phase_fn=None):
        super().__init__(); self.rx, self.ry, self.rz = float(rx), float(ry), float(rz); self.dflts = defaults; self.phase_fn = phase_fn
        self._last = None; self._shown = None; self.setFixedSize(size, size); self.setCursor(Qt.OpenHandCursor); self.setFocusPolicy(Qt.NoFocus)
        self._tm = QTimer(self); self._tm.timeout.connect(self._tick)
    def setAngles(self, rx=None, ry=None):
        if rx is not None: self.rx = float(rx)
        if ry is not None: self.ry = float(ry)
        self.update()
    def setRoll(self, rz): self.rz = float(rz); self.update()
    def phase(self):
        try: return float(self.phase_fn()) if self.phase_fn else 0.0
        except Exception: return 0.0
    def showEvent(self, e): self._tm.start(80)
    def hideEvent(self, e): self._tm.stop()
    def _tick(self):
        ph = round(self.phase())
        if ph != self._shown: self._shown = ph; self.update()
    def project(self):
        """(2D points (8x2), 3D points (8x3)) of the box in widget pixels: the Cube effect's own projection."""
        w = self.width(); Rm = _rot(math.radians(self.rx), math.radians(self.ry + self.phase()), math.radians(self.rz))
        p3 = _VERT @ Rm.T; zc = 3.2 - p3[:, 2] * 0.6; S = w * 2.0
        return np.stack([w / 2 + p3[:, 0] / zc * S * 0.5, w / 2 + p3[:, 1] / zc * S * 0.5], 1), p3
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); w = self.width()
        p.setPen(QPen(QColor(c["line"]), 1)); p.setBrush(QColor(c["field"])); p.drawRoundedRect(QRectF(1, 1, w - 2, w - 2), 12, 12)
        P2, P3 = self.project(); acc = QColor(c["accent"]); light = np.array([-0.4, -0.5, 0.75])
        for fi in sorted(range(6), key=lambda i: float(np.mean(P3[list(_FACES[i])][:, 2]))):
            q = _FACES[fi]; nrm = np.cross(P3[q[1]] - P3[q[0]], P3[q[2]] - P3[q[1]])
            if nrm[2] > 0: continue                                       # facing away
            k = float(np.clip(0.35 + 0.65 * float(-nrm / (np.linalg.norm(nrm) + 1e-6) @ light), 0.0, 1.0)); s = 0.42 + 0.58 * k
            fill = QColor(int(acc.red() * s), int(acc.green() * s), int(acc.blue() * s), 235)
            poly = QPolygonF([QPointF(float(P2[i][0]), float(P2[i][1])) for i in q]); p.setPen(QPen(QColor(255, 255, 255, 120), 0.9)); p.setBrush(fill); p.drawPolygon(poly)
            a0, a1, a3 = P2[q[0]], P2[q[1]], P2[q[3]]; d = a0 + 0.2 * (a1 - a0) + 0.2 * (a3 - a0)
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 230)); p.drawEllipse(QPointF(float(d[0]), float(d[1])), 1.6, 1.6)
    def _wrap(self, v): return ((v + 180.0) % 360.0) - 180.0
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._last = e.position(); self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self, e):
        if self._last is None or not (e.buttons() & Qt.LeftButton): return
        dx, dy = e.position().x() - self._last.x(), e.position().y() - self._last.y(); self._last = e.position()
        self.ry = round(self._wrap(self.ry + dx * 0.9), 1); self.rx = round(self._wrap(self.rx - dy * 0.9), 1)      # dragged right: the face goes right; dragged down: it goes down
        self.update(); self.changed.emit(self.rx, self.ry)
    def mouseReleaseEvent(self, e):
        if self._last is not None: self._last = None; self.setCursor(Qt.OpenHandCursor); self.finished.emit()
    def mouseDoubleClickEvent(self, e):
        self.rx, self.ry = self.dflts; self.update(); self.changed.emit(self.rx, self.ry); self.finished.emit()


# =================================================================================================== building the rows
def _title(text):
    t = QLabel(text); t.setStyleSheet("color:#8e8e9b;font-size:10px;font-weight:600;background:transparent;border:none;"); return t


def _keydot(panel, e, info, key, keys):
    kd = KeyDot(); kd.setToolTip("Add/remove keyframe for this filter parameter at the playhead")
    kd.clicked.connect(lambda eid=e["id"], keys=tuple(keys): [panel._toggle_param_key(eid, k) for k in keys])
    lt_now = max(0.0, float(panel.app.t - (panel.app.sel_clip() or {}).get("start", 0.0))); ks_now = (e.get("keys") or {}).get(key) or []
    kd.setState(any(abs(float(k.get("t", -99)) - lt_now) < 1.0 / 60.0 for k in ks_now), bool(ks_now))
    info.setdefault("keydots", {})[key] = kd; return kd


def _clip_time(panel):
    c = panel.app.sel_clip() or {}; return float(panel.app.t - c.get("start", 0.0))


def _cell_frame(title, keydot):
    box = QFrame(); box.setStyleSheet("QFrame{background:transparent;border:none;}"); v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
    top = QHBoxLayout(); top.setSpacing(2); top.setContentsMargins(0, 0, 0, 0); top.addWidget(_title(title), 1); top.addWidget(keydot); v.addLayout(top); return box, v


def _num(value, lo, hi, dec, suffix, width):
    return NumberField(float(value), lo, hi, dec, suffix, "", scrub=max(0.05, (hi - lo) / 300.0), width=width)


def _dial_cell(panel, e, info, prm, shared):
    key, label_, kind, dflt, lo, hi = prm; eid = e["id"]; cur = float(e["p"].get(key, dflt)); isint = kind == "int"
    dial = MiniDial(cur, lo, hi, 54, dflt); dec = 0 if isint or (hi - lo) >= 60 else 1; nf = _num(cur, lo, hi, dec, "\u00b0", 58)
    box, v = _cell_frame(label_, _keydot(panel, e, info, key, [key])); v.addWidget(dial, 0, Qt.AlignHCenter); v.addWidget(nf, 0, Qt.AlignHCenter)

    def push(x, key=key):
        b = shared.get("box")
        if b is not None and key == "rz": b.setRoll(x)
        panel._edit(eid, key, int(round(x)) if isint else x)
    dial.changed.connect(lambda x: (nf.setValue(x), push(x))); nf.changed.connect(lambda x: (dial.setValue(x), push(x)))

    def setter(x, d=dial, nf=nf, key=key):
        if d._last is not None or nf._press is not None or nf.ed.isVisible(): return
        d.setValue(float(x)); nf.setValue(float(x))
        b = shared.get("box")
        if b is not None and key == "rz": b.setRoll(float(x))
    info["set"][key] = (setter, dflt)
    if key == "rz": shared["rz_value"] = cur
    return box


def _wheel_cell(panel, e, info, prm, shared):
    key, label_, kind, dflt, lo, hi = prm; eid = e["id"]; cur = float(e["p"].get(key, dflt)); isint = kind == "int"
    wheel = SpeedWheel(cur, lo, hi, 66, dflt, lambda: _clip_time(panel)); nf = _num(cur, lo, hi, 0, "\u00b0/s", 64)
    box, v = _cell_frame(label_.replace("(deg / s)", "").strip() or "Speed", _keydot(panel, e, info, key, [key])); v.addWidget(wheel, 0, Qt.AlignHCenter); v.addWidget(nf, 0, Qt.AlignHCenter)
    def push(x): panel._edit(eid, key, int(round(x)) if isint else x)
    wheel.changed.connect(lambda x: (nf.setValue(x), push(x))); nf.changed.connect(lambda x: (wheel.setValue(x), push(x)))

    def setter(x, w=wheel, nf=nf):
        if w._drag or nf._press is not None or nf.ed.isVisible(): return
        w.setValue(float(x)); nf.setValue(float(x))
    info["set"][key] = (setter, dflt)
    if key == "spin": shared["spin"] = wheel
    return box


def _box_cell(panel, e, info, prms, shared):
    by = {p[0]: p for p in prms}; px, py = by["rx"], by["ry"]; eid = e["id"]
    rx, ry = float(e["p"].get("rx", px[3])), float(e["p"].get("ry", py[3])); rz = float(e["p"].get("rz", 0.0))
    spin = lambda: _clip_time(panel) * float(e["p"].get("spin", 0.0))
    b3 = Box3D(rx, ry, rz, 76, (float(px[3]), float(py[3])), spin); shared["box"] = b3
    nx = _num(rx, px[4], px[5], 0, "\u00b0", 50); ny = _num(ry, py[4], py[5], 0, "\u00b0", 50)
    box, v = _cell_frame("Tilt X / Turn Y", _keydot(panel, e, info, "rx", ["rx", "ry"])); v.addWidget(b3, 0, Qt.AlignHCenter)
    r = QHBoxLayout(); r.setSpacing(2); r.addWidget(nx); r.addWidget(ny); v.addLayout(r)
    b3.changed.connect(lambda a, b: (nx.setValue(a), ny.setValue(b), panel._edit(eid, "rx", a), panel._edit(eid, "ry", b)))
    nx.changed.connect(lambda a: (b3.setAngles(rx=a), panel._edit(eid, "rx", a))); ny.changed.connect(lambda b: (b3.setAngles(ry=b), panel._edit(eid, "ry", b)))

    def set_rx(x, nx=nx):
        if b3._last is not None or nx._press is not None or nx.ed.isVisible(): return
        b3.setAngles(rx=float(x)); nx.setValue(float(x))

    def set_ry(x, ny=ny):
        if b3._last is not None or ny._press is not None or ny.ed.isVisible(): return
        b3.setAngles(ry=float(x)); ny.setValue(float(x))
    info["set"]["rx"] = (set_rx, px[3]); info["set"]["ry"] = (set_ry, py[3]); return box


def build(panel, v, e, info, item):
    """Add one row of round controls to the effect card `v`."""
    shared = {}; row = QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(0, 2, 0, 2); cells = item[2]; widgets = []
    for cell in sorted(cells, key=lambda c: 0 if c[0] == "box" else 1):       # the box first, so the roll dial can find it
        kind = cell[0]
        w = _box_cell(panel, e, info, cell[1], shared) if kind == "box" else _wheel_cell(panel, e, info, cell[1], shared) if kind == "wheel" else _dial_cell(panel, e, info, cell[1], shared)
        widgets.append((cell, w))
    order = {id(c): i for i, c in enumerate(cells)}
    for cell, w in sorted(widgets, key=lambda cw: order[id(cw[0])]): row.addWidget(w)
    row.addStretch(1); v.addLayout(row)

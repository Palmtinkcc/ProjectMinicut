"""Points you can drag on the preview.

* The CENTRE of an effect (the point a Spin Blur / Zoom Blur / Swirl ... works around). It is shown only while the Effects tab of the
  Properties panel is open (and the clip has such an effect that is switched on), and it is hidden in every other mode.
* The ORIGIN of the media (the pivot it turns and scales around). It is shown while "Show on preview" is on in the Origin card of the Basic tab.

Both snap to the centre and the edges of the media. Alt, or the Snap button of the timeline switched off, turns the snapping off.
Mixed into Viewport (see viewport.py); this file only holds the point logic.
"""
from ..shared.deps import *
from ..shared.core import prop_at, set_prop
from ..render.effects import FX
from ..render.renderer import clip_origin, origin_vec

HIT_PX = 10.0                 # how close (screen pixels) the mouse has to be to grab a point
SNAP_PX = 8.0                 # how close (screen pixels) a point has to come to the centre / an edge to snap
SNAP_FRACS = (0.0, 0.5, 1.0)  # edge, centre, edge (as a part of the media width / height)
ORIGIN_COLOR = "#ffb020"


# ---------------------------------------------------------------- effect centre parameters
def center_params(type_):
    """((key, label, kind, default, lo, hi) of the X parameter, the same of the Y parameter) when the effect has a centre point, else None.
    An effect has one when it has two number parameters named cx / cy (or x / y) whose labels say "Center"."""
    spec = FX.get(type_)
    if not spec: return None
    byk = {sp[0]: sp for sp in spec["params"]}
    for kx, ky in (("cx", "cy"), ("x", "y")):
        a, b = byk.get(kx), byk.get(ky)
        if a and b and a[2] == "float" and b[2] == "float" and "center" in str(a[1]).lower() and "center" in str(b[1]).lower(): return a, b
    return None


def _offset_style(sp): return float(sp[3]) == 0.0 and float(sp[4]) < 0          # 0 = the middle of the picture (Vignette Pro) instead of 50 = the middle


def val_to_frac(sp, v):
    """Value of a centre parameter -> position in the picture as a part of its width / height (0 = left / top edge, 1 = right / bottom edge)."""
    return (0.5 if _offset_style(sp) else 0.0) + float(v) / 100.0


def frac_to_val(sp, f):
    """Position in the picture (0..1) -> value of the centre parameter, kept inside the range of the parameter."""
    v = (float(f) - (0.5 if _offset_style(sp) else 0.0)) * 100.0
    return round(max(float(sp[4]), min(float(sp[5]), v)), 2)


# ---------------------------------------------------------------- origin
def apply_origin(app, c, lt, o1, st, o0, bs):
    """Move the origin of clip c to o1 = (x, y) in percent of the media size from its centre, WITHOUT moving the picture at clip time lt:
    Position X / Y are where the origin sits, so they change by the same amount the origin moved (scale and rotation applied).
    st = {x, y, sx, sy, rot} and o0 = the origin when the change started (so a drag never adds rounding errors), bs = (width, height) of the media.
    If position, scale or rotation are animated, the picture is exact at lt only (as with any pivot change)."""
    a = origin_vec(o1[0], o1[1], bs[0], bs[1], st["sx"], st["sy"], st["rot"])
    b = origin_vec(o0[0], o0[1], bs[0], bs[1], st["sx"], st["sy"], st["rot"])
    c["origin"] = [float(o1[0]), float(o1[1])]
    set_prop(c, "x", lt, round(st["x"] + a[0] - b[0], 2)); set_prop(c, "y", lt, round(st["y"] + a[1] - b[1], 2))


def set_origin_now(app, c, ox, oy):
    """Set the origin from a number field: the state of the clip at the playhead is the starting point. Returns False when the media has no size yet."""
    lt = app.t - c["start"]; bs = app.renderer.base_size(app.proj, c)
    st = {k: prop_at(c, k, lt) for k in ("x", "y", "sx", "sy", "rot")}
    if not bs: c["origin"] = [float(ox), float(oy)]; return False
    apply_origin(app, c, lt, (ox, oy), st, clip_origin(c), bs); return True


class PointOverlay:
    """Mixin for Viewport."""
    pt_lines = ()          # snap lines to draw: [(QPointF, QPointF)]
    _pt_last = None        # the point that was grabbed last (to step through points that lie on top of each other)

    # ---- what is shown ----
    def _pt_fx_mode(self):
        """True while the Effects tab of the Properties panel is the open one."""
        insp = getattr(self.app, "inspector", None)
        try: return bool(insp is not None and insp.tabs.isVisible() and insp.tabs.currentIndex() == insp.fx_tab)
        except Exception: return False

    def _pt_clip(self):
        c = self.app.sel_clip()
        if c is None or getattr(self.app, "_mprev", None) is not None or self._multi_ids() or not self._active(c): return None
        return c

    def _pt_map(self, pts, u, v):
        """Screen position of the point (u, v) of the media (0..1 across, 0..1 down); the corners are the 4 screen points of the clip."""
        tl, tr, br, bl = pts
        return tl + (tr - tl) * u + (bl - tl) * v

    def _pt_unmap(self, pts, pos):
        """(u, v) of the media under a screen position; None when the clip is squashed flat."""
        tl, tr, br, bl = pts; a = tr - tl; b = bl - tl; d = pos - tl
        det = a.x() * b.y() - a.y() * b.x()
        if abs(det) < 1e-9: return None
        return (d.x() * b.y() - d.y() * b.x()) / det, (a.x() * d.y() - a.y() * d.x()) / det

    def _pt_items(self):
        """The points that are shown now: dicts with kind ('fx' / 'org'), pos (screen), and what is needed to move them."""
        c = self._pt_clip()
        if c is None: return []
        pts = self._pts(c)
        if not pts: return []
        out = []
        if self._pt_fx_mode():
            from .effects_panel import _fx_key_value
            lt = self.app.t - c["start"]; ratio = None
            for e in c.get("effects") or []:
                if not e.get("on", True) or e.get("type") not in FX: continue
                cp = center_params(e["type"])
                if cp is None: continue
                spx, spy = cp; pr = e.get("p") or {}
                try: vx = float(_fx_key_value(e, spx[0], lt, pr.get(spx[0], spx[3]))); vy = float(_fx_key_value(e, spy[0], lt, pr.get(spy[0], spy[3])))
                except Exception: continue
                a = b = 0.0
                if e.get("spill"):          # the effect works on the media with an empty border: its picture is bigger than the media
                    if ratio is None: ratio = self.app.renderer.spill_ratio(self.app.proj, c, self.app.t)
                    a, b = ratio
                u = val_to_frac(spx, vx) * (1 + 2 * a) - a; v = val_to_frac(spy, vy) * (1 + 2 * b) - b
                out.append({"kind": "fx", "eid": e["id"], "title": FX[e["type"]]["title"], "pos": self._pt_map(pts, u, v), "sp": (spx, spy), "pad": (a, b)})
        elif getattr(self.app, "origin_edit", False):
            ox, oy = clip_origin(c); out.append({"kind": "org", "eid": None, "title": "Origin", "pos": self._pt_map(pts, 0.5 + ox / 100.0, 0.5 + oy / 100.0)})
        return out

    # ---- drawing ----
    def _pt_paint(self, p):
        items = self._pt_items()
        if not items and not self.pt_lines: return
        p.save()
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            if self.pt_lines:
                p.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DashLine)); p.setBrush(Qt.NoBrush)
                for a, b in self.pt_lines: p.drawLine(a, b)
            f = QFont(QApplication.font()); f.setPixelSize(11); f.setBold(True); p.setFont(f); fm = p.fontMetrics(); seen = []
            for it in items:
                q = it["pos"]; col = QColor(ORIGIN_COLOR) if it["kind"] == "org" else QColor("#22d3ee")
                r = 8.0 if it["kind"] == "org" else 7.0; arm = r + 8
                p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(0, 0, 0, 190), 4)); p.drawEllipse(q, r, r)
                p.drawLine(QPointF(q.x() - arm, q.y()), QPointF(q.x() + arm, q.y())); p.drawLine(QPointF(q.x(), q.y() - arm), QPointF(q.x(), q.y() + arm))
                p.setPen(QPen(col, 2)); p.drawEllipse(q, r, r)
                p.drawLine(QPointF(q.x() - arm, q.y()), QPointF(q.x() + arm, q.y())); p.drawLine(QPointF(q.x(), q.y() - arm), QPointF(q.x(), q.y() + arm))
                p.setPen(Qt.NoPen); p.setBrush(col); p.drawEllipse(q, 2.5, 2.5)
                k = sum(1 for s in seen if abs(s.x() - q.x()) < 3 and abs(s.y() - q.y()) < 3); seen.append(q)      # points on top of each other: the labels step upwards
                if it["kind"] == "org": continue          # the origin has no text next to it (the effect centres keep the name of their effect)
                txt = it["title"]; tw = fm.horizontalAdvance(txt) + 10; rect = QRectF(q.x() + r + 6, q.y() - r - 18 - 16 * k, tw, 16)
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 175)); p.drawRoundedRect(rect, 4, 4)
                p.setPen(col); p.drawText(rect, Qt.AlignCenter, txt)
        finally: p.restore()

    # ---- grabbing and dragging ----
    def _pt_hit(self, pos):
        near = []
        for it in self._pt_items():
            d = math.hypot(it["pos"].x() - pos.x(), it["pos"].y() - pos.y())
            if d <= HIT_PX: near.append((d, it))
        if not near: return None
        near.sort(key=lambda t: t[0]); d0 = near[0][0]; ties = [it for d, it in near if d - d0 < 2.0]
        if len(ties) > 1:             # several points on the same spot: every press takes the next one
            ids = [it["eid"] or "org" for it in ties]
            if self._pt_last in ids: return ties[(ids.index(self._pt_last) + 1) % len(ties)]
        return ties[0]

    def _pt_press(self, e):
        """True when the press grabbed a point (then nothing else may react to it)."""
        if e.button() != Qt.LeftButton: return False
        it = self._pt_hit(e.position())
        if it is None: return False
        app = self.app; c = app.sel_clip(); tr = app.proj.track(c["track"])
        if tr and tr["locked"]: return False
        self._pt_last = it["eid"] or "org"
        if it["kind"] == "fx": self.drag = {"mode": "fxc", "item": it}; return True
        bs = app.renderer.base_size(app.proj, c)
        if not bs: return False
        lt = app.t - c["start"]
        self.drag = {"mode": "org", "item": it, "clip": c, "before": app.begin(), "lt": lt, "bs": bs, "o0": clip_origin(c),
                     "st": {k: prop_at(c, k, lt) for k in ("x", "y", "sx", "sy", "rot")}}
        return True

    def _pt_snap(self, pts, u, v):
        """Pull (u, v) to the centre / edges of the media when it is close (in screen pixels); also gives the lines to show."""
        tl, tr, br, bl = pts; lu = math.hypot((tr - tl).x(), (tr - tl).y()); lv = math.hypot((bl - tl).x(), (bl - tl).y()); lines = []
        best = min(((lu * abs(u - t), t) for t in SNAP_FRACS), key=lambda x: x[0])
        if best[0] < SNAP_PX: u = best[1]; lines.append((self._pt_map(pts, u, 0.0), self._pt_map(pts, u, 1.0)))
        best = min(((lv * abs(v - t), t) for t in SNAP_FRACS), key=lambda x: x[0])
        if best[0] < SNAP_PX: v = best[1]; lines.append((self._pt_map(pts, 0.0, v), self._pt_map(pts, 1.0, v)))
        return u, v, lines

    def _pt_move(self, e):
        """True when the mouse move belongs to a point (hover cursor, or a drag in progress)."""
        d = self.drag
        if d is None:
            if self._pt_hit(e.position()) is not None: self.setCursor(Qt.CrossCursor); return True
            return False
        if d.get("mode") not in ("fxc", "org"): return False
        app = self.app; c = app.sel_clip(); pts = self._pts(c) if c is not None else None
        if not pts: return True
        uv = self._pt_unmap(pts, e.position())
        if uv is None: return True
        u, v = uv; self.pt_lines = ()
        if app.snap_on and not (e.modifiers() & Qt.AltModifier): u, v, self.pt_lines = self._pt_snap(pts, u, v)
        if d["mode"] == "org":
            apply_origin(app, c, d["lt"], (round((u - 0.5) * 100.0, 2), round((v - 0.5) * 100.0, 2)), d["st"], d["o0"], d["bs"])
            app.request_render()
        else:
            spx, spy = d["item"]["sp"]; a, b = d["item"]["pad"]; fx = app.inspector.fx_panel
            fx._edit(d["item"]["eid"], spx[0], frac_to_val(spx, (u + a) / (1 + 2 * a)))
            fx._edit(d["item"]["eid"], spy[0], frac_to_val(spy, (v + b) / (1 + 2 * b)))
        self.update(); app.inspector.refresh()
        return True

    def _pt_release(self, d):
        """Called when a drag ends (the origin drag is finished by the normal release code, which stores the undo step)."""
        self.pt_lines = ()
        if d and d.get("mode") == "fxc":
            try: self.app.inspector.fx_panel._commit()
            except Exception as ex: print("[points]", ex)

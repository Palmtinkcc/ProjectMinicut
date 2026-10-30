"""Viewport: preview image, selection handles, box selection, audio level meter."""
from ..shared.deps import *
from ..shared.theme import *
from ..shared.core import *
from ..render.audio import *


def snap_angle(a):
    mods = QApplication.keyboardModifiers()
    if mods & Qt.ControlModifier: return a
    if mods & Qt.ShiftModifier: return float(round(a / 15) * 15)
    n = round(a / 45) * 45
    return float(n) if abs(a - n) <= 3 else a


class Viewport(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self.img = None; self.zoom = 1.0; self.pan = QPointF(); self.drag = None
        self.guides = []; self.setMouseTracking(True); self.setMinimumSize(1, 1); self.setAcceptDrops(True)
        self._lv = [0.0, 0.0]; self._hold = [0.0, 0.0]; self._hold_t = [0.0, 0.0]
        self._mt = QTimer(self); self._mt.setInterval(33); self._mt.timeout.connect(self._meter_tick); self._mt.start()
    # ---- audio level meter ----
    def _meter_rect(self):
        w = int(UI["meter_w"]); h = int(self.height() * 0.6)
        return QRectF(self.width() - w - 10, self.height() - h - 14, w, h)
    def _meter_tick(self):
        now = time.monotonic(); live = bool(getattr(self.app, "playing", False)) and now - METER["t"] < 0.3
        tgt = (METER["l"], METER["r"]) if live else (0.0, 0.0); ch = False
        for i in (0, 1):
            old, oh = self._lv[i], self._hold[i]; v = tgt[i]
            nv = v if v >= old else (old * 0.86 if old > 0.002 else 0.0)
            self._lv[i] = nv
            if nv >= self._hold[i]: self._hold[i] = nv; self._hold_t[i] = now
            elif now - self._hold_t[i] > 0.9: self._hold[i] = max(nv, self._hold[i] * 0.92)
            if nv != old or self._hold[i] != oh: ch = True
        if ch and UI["meter_show"] and self.isVisible(): self.update(self._meter_rect().adjusted(-6, -6, 6, 6).toAlignedRect())
    def _paint_meter(self, p):
        if not UI["meter_show"] or self.height() < 80: return
        r = self._meter_rect(); bg = QColor(UI["meter_bg"]); bg.setAlpha(190)
        p.setPen(Qt.NoPen); p.setBrush(bg); p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 4, 4)
        bw = (r.width() - 2) / 2.0
        zones = [(0.0, 0.7, QColor(UI["meter_low"])), (0.7, 0.9, QColor(UI["meter_mid"])), (0.9, 1.0, QColor(UI["meter_high"]))]
        frac = lambda v: max(0.0, min(1.0, (20 * math.log10(max(v, 1e-5)) + 60) / 60.0))
        for i in (0, 1):
            x = r.left() + i * (bw + 2); f = frac(self._lv[i]) if self._lv[i] > 0.0005 else 0.0
            p.setBrush(QColor(255, 255, 255, 18)); p.drawRect(QRectF(x, r.top(), bw, r.height()))
            for z0, z1, col in zones:
                top = min(f, z1)
                if top > z0: p.setBrush(col); p.drawRect(QRectF(x, r.bottom() - top * r.height(), bw, (top - z0) * r.height()))
            hf = frac(self._hold[i]) if self._hold[i] > 0.0005 else 0.0
            if hf > 0: p.setBrush(QColor(255, 255, 255, 230)); p.drawRect(QRectF(x, r.bottom() - hf * r.height() - 1, bw, 2))
        p.setPen(QColor(255, 255, 255, 90))
        for db in (-6, -12, -24, -36, -48):
            yy = r.bottom() - (db + 60) / 60.0 * r.height(); p.drawLine(QPointF(r.left() - 3, yy), QPointF(r.left(), yy))
    # ---- multi selection helpers ----
    def _multi_ids(self):
        ids = set(getattr(self.app, "multi", set()) or ())
        if self.app.sel: ids.add(self.app.sel)
        return ids if len(ids) > 1 else set()
    def _multi_clips(self, ids):
        return [c for c in self.app.proj.clips if c["id"] in ids and self._active(c)]
    def _marquee_pick(self, rect):
        P = self.app.proj; ok = {t["id"] for t in P.tracks if t["kind"] == "video" and not t["hidden"] and not t["locked"]}
        rp = QPolygonF(rect); ids = set()
        for c in P.clips:
            if c["track"] in ok and self._active(c):
                pts = self._pts(c)
                if pts and not QPolygonF(pts).intersected(rp).isEmpty(): ids.add(c["id"])
        return ids
    def _begin_move(self, c, pos, mode="move"):
        app = self.app; tr = app.proj.track(c["track"])
        if tr and tr["locked"]: return
        lt = app.t - c["start"]; st = {k: prop_at(c, k, lt) for k in ("x", "y", "sx", "sy", "rot")}; grp = []
        if mode == "move":
            for o in self._multi_clips(self._multi_ids()):
                otr = app.proj.track(o["track"])
                if o is not c and not (otr and otr["locked"]):
                    ot = app.t - o["start"]; grp.append((o, ot, {k: prop_at(o, k, ot) for k in ("x", "y")}))
        self.drag = {"mode": mode, "clip": c, "st": st, "p0": self.pr(pos), "lt": lt, "before": app.begin(), "grp": grp,
                     "c": (app.proj.w / 2 + st["x"], app.proj.h / 2 + st["y"])}
    def set_frame(self, img): self.img = img; self.update()
    def tf(self):
        P = self.app.proj; s = min(self.width() / P.w, self.height() / P.h) * 0.94 * self.zoom
        return s, (self.width() - P.w * s) / 2 + self.pan.x(), (self.height() - P.h * s) / 2 + self.pan.y()
    def v(self, x, y): s, ox, oy = self.tf(); return QPointF(ox + x * s, oy + y * s)
    def pr(self, pt): s, ox, oy = self.tf(); return (pt.x() - ox) / s, (pt.y() - oy) / s
    def _active(self, c):
        return c and is_visual(c["kind"]) and c["start"] <= self.app.t < c["start"] + c["dur"]
    def _pts(self, c):
        g = self.app.renderer.geometry(self.app.proj, c, self.app.t)
        return [self.v(*q) for q in g] if g else None
    def handles(self, pts):
        tl, tr, br, bl = pts; mid = lambda a, b: (a + b) / 2
        h = {"tl": tl, "tr": tr, "br": br, "bl": bl, "t": mid(tl, tr), "r": mid(tr, br), "b": mid(br, bl), "l": mid(bl, tl)}
        c = (tl + br) / 2; d = h["t"] - c; L = math.hypot(d.x(), d.y()) or 1; h["rot"] = h["t"] + d / L * 28
        return h
    def pick(self, pos):
        P = self.app.proj
        for tr in [t for t in P.tracks if t["kind"] == "video" and not t["hidden"]]:
            for c in reversed(P.clips):
                if c["track"] == tr["id"] and self._active(c):
                    pts = self._pts(c)
                    if pts and QPolygonF(pts).containsPoint(pos, Qt.OddEvenFill): return c
        return None
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), QColor(UI["vp_bg"]))
        if not self.app.proj: return
        P = self.app.proj; s, ox, oy = self.tf(); r = QRectF(ox, oy, P.w * s, P.h * s)
        p.fillRect(r, QColor(P.bg))
        if self.img is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, self.app.settings["preview_interp"] != "fast"); p.drawImage(r, self.img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(UI["vp_guide"]), 1, Qt.DashLine))
        for kind, val in self.guides:
            if kind == "v": q = self.v(val, 0); p.drawLine(QPointF(q.x(), 0), QPointF(q.x(), self.height()))
            else: q = self.v(0, val); p.drawLine(QPointF(0, q.y()), QPointF(self.width(), q.y()))
        mids = self._multi_ids(); oc = QColor(UI["vp_outline"]); ow = float(UI["vp_outline_w"])
        if mids:
            p.setBrush(Qt.NoBrush)
            for o in self._multi_clips(mids):
                pts = self._pts(o)
                if pts: p.setPen(QPen(oc, ow, Qt.DashLine)); p.drawPolygon(QPolygonF(pts))
        else:
            c = self.app.sel_clip()
            if self._active(c):
                pts = self._pts(c)
                if pts:
                    p.setPen(QPen(oc, ow)); p.setBrush(Qt.NoBrush); p.drawPolygon(QPolygonF(pts))
                    hs = self.handles(pts); p.setPen(QPen(oc, 1)); p.drawLine(hs["t"], hs["rot"]); hr = float(UI["vp_handle_size"])
                    for n, q in hs.items():
                        p.setPen(QPen(QColor(UI["vp_handle"]), 1.5)); p.setBrush(oc)
                        if n == "rot": p.drawEllipse(q, hr + 1, hr + 1)
                        elif len(n) == 2: p.drawEllipse(q, hr, hr)
                        else: p.drawRoundedRect(QRectF(q.x() - hr + 1, q.y() - hr + 1, 2 * hr - 2, 2 * hr - 2), 2, 2)
        d = self.drag
        if d and d.get("mode") == "marquee" and d.get("moved"):
            mc = QColor(UI["marquee"]); fc = QColor(mc); fc.setAlpha(50)
            p.setPen(QPen(mc, 1)); p.setBrush(fc); p.drawRect(QRectF(d["p0"], d["p"]).normalized())
        self._paint_meter(p)
    def _hit(self, pos):
        c = self.app.sel_clip()
        if not self._active(c): return None, None
        pts = self._pts(c)
        if not pts: return None, None
        for n, q in self.handles(pts).items():
            if math.hypot(q.x() - pos.x(), q.y() - pos.y()) < 9: return c, n
        if QPolygonF(pts).containsPoint(pos, Qt.OddEvenFill): return c, "move"
        return None, None
    def mousePressEvent(self, e):
        pos = e.position(); app = self.app
        if not app.proj: return
        if e.button() == Qt.MiddleButton: self.drag = {"mode": "pan", "p": pos, "pan": QPointF(self.pan)}; return
        if e.button() != Qt.LeftButton: return
        mod = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)); ids = self._multi_ids()
        if ids and not mod:        # several clips selected: drag any of them to move all together
            hit = None
            for o in reversed(self._multi_clips(ids)):
                pts = self._pts(o)
                if pts and QPolygonF(pts).containsPoint(pos, Qt.OddEvenFill): hit = o; break
            if hit: self._begin_move(hit, pos); return
        c, mode = self._hit(pos) if not ids else (None, None)
        if not c:
            c = self.pick(pos)
            if mod and c:          # Ctrl / Shift + click toggles a clip in the selection
                base = set(ids) or ({app.sel} if app.sel else set()); g = with_groups(app, {c["id"]})
                if c["id"] in base: base -= g
                else: base |= g
                app.set_multi(base, c["id"] if c["id"] in base else None); return
            if not c:
                self.drag = {"mode": "marquee", "p0": pos, "p": pos, "base": set(ids) if mod else set(), "moved": False}; return
            app.select(c["id"]); app.multi = with_groups(app, {c["id"]}); mode = "move"
        self._begin_move(c, pos, mode)
    def _local(self, d, px, py):
        cx, cy = d["c"]; th = math.radians(d["st"]["rot"]); dx, dy = px - cx, py - cy
        return dx * math.cos(th) + dy * math.sin(th), -dx * math.sin(th) + dy * math.cos(th)
    @staticmethod
    def _snap1(center, offs, targets, thr):
        best = None
        for o in offs:
            for t in targets:
                d = t - (center + o)
                if abs(d) < thr and (best is None or abs(d) < abs(best[0])): best = (d, t)
        return (center + best[0], best[1]) if best else (center, None)
    def _move_core(self, e):
        pos = e.position(); app = self.app
        if not app.proj: return
        d = self.drag
        if not d:
            _, n = self._hit(pos)
            cur = {"move": Qt.SizeAllCursor, "rot": Qt.PointingHandCursor, "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
                   "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                   "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor}.get(n)
            self.setCursor(cur) if cur else self.unsetCursor(); return
        if d["mode"] == "pan": self.pan = d["pan"] + (pos - d["p"]); self.update(); return
        if d["mode"] == "marquee":
            d["p"] = pos
            if not d["moved"] and (pos - d["p0"]).manhattanLength() > 4: d["moved"] = True
            if d["moved"]: app.set_multi(with_groups(app, self._marquee_pick(QRectF(d["p0"], pos).normalized())) | d["base"])
            self.update(); return
        c = d["clip"]; P = app.proj; px, py = self.pr(pos); s, _, _ = self.tf(); thr = 8 / s
        st, lt, m = d["st"], d["lt"], d["mode"]; snap = app.snap_on and not (e.modifiers() & Qt.AltModifier)
        self.guides = []
        grp_ids = {g[0]["id"] for g in d.get("grp", ())}
        if m == "move":
            nx = st["x"] + px - d["p0"][0]; ny = st["y"] + py - d["p0"][1]
            if snap:
                g = app.renderer.geometry(P, c, app.t); ccx = P.w / 2 + prop_at(c, "x", lt); ccy = P.h / 2 + prop_at(c, "y", lt)
                xs = [q[0] - ccx for q in g]; ys = [q[1] - ccy for q in g]
                tx, ty = [0, P.w / 2, P.w], [0, P.h / 2, P.h]
                for o in P.clips:
                    if o is not c and o["id"] not in grp_ids and self._active(o):
                        og = app.renderer.geometry(P, o, app.t)
                        if og:
                            gx = [q[0] for q in og]; gy = [q[1] for q in og]
                            tx += [min(gx), max(gx), sum(gx) / 4]; ty += [min(gy), max(gy), sum(gy) / 4]
                cx, gx = self._snap1(P.w / 2 + nx, [min(xs), 0, max(xs)], tx, thr)
                cy, gy = self._snap1(P.h / 2 + ny, [min(ys), 0, max(ys)], ty, thr)
                nx, ny = cx - P.w / 2, cy - P.h / 2
                if gx is not None: self.guides.append(("v", gx))
                if gy is not None: self.guides.append(("h", gy))
            set_prop(c, "x", lt, round(nx, 2)); set_prop(c, "y", lt, round(ny, 2))
            for o, ot, ost in d.get("grp", ()):
                set_prop(o, "x", ot, round(ost["x"] + nx - st["x"], 2)); set_prop(o, "y", ot, round(ost["y"] + ny - st["y"], 2))
        elif m in ("tl", "tr", "br", "bl"):
            lx, ly = self._local(d, px, py); l0x, l0y = self._local(d, *d["p0"])
            r = math.hypot(lx, ly) / max(1e-6, math.hypot(l0x, l0y)); nsx, nsy = st["sx"] * r, st["sy"] * r
            if snap and abs(abs(nsx) - 100) < 2.5: f = 100 / abs(nsx); nsx *= f; nsy *= f
            set_prop(c, "sx", lt, round(nsx, 2)); set_prop(c, "sy", lt, round(nsy, 2))
        elif m in ("l", "r", "t", "b"):
            lx, ly = self._local(d, px, py); l0x, l0y = self._local(d, *d["p0"])
            if m in ("l", "r"):
                v = st["sx"] * (lx / l0x if abs(l0x) > 1e-6 else 1)
                if snap and abs(abs(v) - 100) < 2.5: v = math.copysign(100, v)
                set_prop(c, "sx", lt, round(v, 2))
            else:
                v = st["sy"] * (ly / l0y if abs(l0y) > 1e-6 else 1)
                if snap and abs(abs(v) - 100) < 2.5: v = math.copysign(100, v)
                set_prop(c, "sy", lt, round(v, 2))
        elif m == "rot":
            cx, cy = d["c"]
            nr = st["rot"] + math.degrees(math.atan2(py - cy, px - cx) - math.atan2(d["p0"][1] - cy, d["p0"][0] - cx))
            if e.modifiers() & Qt.ShiftModifier: nr = round(nr / 15) * 15
            elif snap and abs(nr - round(nr / 45) * 45) < 4: nr = round(nr / 45) * 45
            set_prop(c, "rot", lt, round(nr, 2))
        app.request_render(); self.update(); app.inspector.refresh()
    def mouseReleaseEvent(self, e):
        d = self.drag; self.drag = None; self.guides = []
        if d and d.get("mode") == "marquee":
            if not d["moved"] and not d["base"]: self.app.set_multi(set())
        elif d and d.get("clip"): self.app.commit(d["before"]); self.app.on_changed()
        self.update()
    def mouseDoubleClickEvent(self, e):
        if not self._hit(e.position())[0]: self.zoom = 1.0; self.pan = QPointF(); self.update()
    def wheelEvent(self, e):
        f = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12; old = self.zoom
        self.zoom = max(0.1, min(8.0, self.zoom * f)); pos = e.position()
        c = QPointF(self.width() / 2, self.height() / 2) + self.pan
        self.pan += (c - pos) * (self.zoom / old - 1); self.update()
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.setDropAction(Qt.CopyAction); e.accept()
    def dragMoveEvent(self, e): e.setDropAction(Qt.CopyAction); e.accept()
    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.app.add_files(paths, self.app.t, None); e.setDropAction(Qt.CopyAction); e.accept()
    def mouseMoveEvent(self, e):
        self._move_core(e)
        d = getattr(self, "drag", None)
        if not isinstance(d, dict) or "rot" not in str(d.get("mode", "")).lower(): return
        c = self.app.sel_clip()
        if not c: return
        kf = None
        try: kf = key_at(c, "rot", self.app.t - c["start"])
        except Exception: pass
        target = kf if isinstance(kf, dict) and "v" in kf else c["props"]["rot"]
        target["v"] = snap_angle(float(target["v"])); self.app.request_render(); self.update()

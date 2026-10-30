"""Timeline: tracks, clips, keyframes, box selection, snapping, context menu."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.theme import *
from ..shared.core import *
from ..shared.core import _group_ids
from ..shared.widgets import *
from ..render.media import proxy_pieces, proxy_sources, PROXY_CHUNK


class Timeline(QWidget):
    @property
    def HEAD(self): return int(UI["tl_head_w"])
    @property
    def RULER(self): return int(UI["tl_ruler_h"])
    def __init__(self, app):
        super().__init__(); self.app = app; self.pps = 80.0; self.xoff = 0; self.yoff = 0
        self.hbar = QScrollBar(Qt.Horizontal); self.vbar = QScrollBar(Qt.Vertical)
        self.hbar.valueChanged.connect(lambda v: (setattr(self, "xoff", v), self.update()))
        self.vbar.valueChanged.connect(lambda v: (setattr(self, "yoff", v), self.update()))
        self.drag = None; self.snap_line = None; self.drop_hint = None
        self.setMouseTracking(True); self.setAcceptDrops(True); self.setMinimumHeight(1); self.setFocusPolicy(Qt.ClickFocus)
    def track_h(self, tr): return int(UI["tl_video_h"]) if tr["kind"] == "video" else int(UI["tl_audio_h"])
    def lanes(self):
        y = self.RULER + 8 - self.yoff; out = []
        for tr in self.app.proj.tracks: h = self.track_h(tr); out.append((tr, y, h)); y += h + int(UI["tl_gap"])
        return out
    def content_h(self): return self.RULER + 8 + sum(self.track_h(t) + int(UI["tl_gap"]) for t in self.app.proj.tracks) + 50
    def t2x(self, t): return self.HEAD + t * self.pps - self.xoff
    def x2t(self, x): return (x - self.HEAD + self.xoff) / self.pps
    def update_scroll(self):
        if not self.app.proj: return
        vis = max(1, self.width() - self.HEAD); total = int((max(self.app.proj.duration(), 10) + 30) * self.pps)
        self.hbar.setRange(0, max(0, total - vis)); self.hbar.setPageStep(vis)
        ch = self.content_h(); self.vbar.setRange(0, max(0, ch - self.height())); self.vbar.setPageStep(max(1, self.height()))
        self.vbar.setVisible(ch > self.height())
    def resizeEvent(self, e): self.update_scroll()
    def set_zoom(self, pps, anchor=None):
        if anchor is None: anchor = (self.app.t, self.t2x(self.app.t))
        t, mx = anchor; self.pps = max(2.0, min(2000.0, pps)); self.update_scroll()
        self.hbar.setValue(int(t * self.pps - (mx - self.HEAD))); self.update()
        self.app.sync_zoom_slider()
    def zoom_fit(self):
        self.pps = max(2.0, (self.width() - self.HEAD - 60) / max(5.0, self.app.proj.duration()))
        self.update_scroll(); self.hbar.setValue(0); self.update(); self.app.sync_zoom_slider()
    def follow(self):
        x = self.t2x(self.app.t)
        if x > self.width() - 60 or x < self.HEAD: self.hbar.setValue(int(self.app.t * self.pps - (self.width() - self.HEAD) * 0.15))
    def chips(self, tr, y, h):
        keys = [("hidden", "H", "Hide"), ("muted", "M", "Mute"), ("locked", "L", "Lock")] if tr["kind"] == "video" else [("muted", "M", "Mute"), ("locked", "L", "Lock")]
        out = []; x = self.HEAD - 12 - 24 * len(keys)
        for k, lab, tip in keys: out.append((k, QRectF(x, y + h / 2 - 10, 20, 20), lab, tr[k])); x += 24
        return out
    # ---- painting ----
    def _paint_core(self, ev):
        if not self.app.proj: return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(UI["tl_bg"])); lanes = self.lanes(); lane_of = {tr["id"]: (y, h) for tr, y, h in lanes}
        p.setClipRect(QRect(self.HEAD, self.RULER, W - self.HEAD, H - self.RULER))
        for tr, y, h in lanes: p.fillRect(QRectF(self.HEAD, y, W, h), QColor(UI["tl_lane_video"] if tr["kind"] == "video" else UI["tl_lane_audio"]))
        for c in self.app.proj.clips:
            if c["track"] in lane_of: self.draw_clip(p, c, *lane_of[c["track"]], W)
        if self.drop_hint and lanes:
            y = lanes[0][1] - 4 if self.drop_hint == "top" else lanes[-1][1] + lanes[-1][2] + 2
            p.setPen(QPen(QColor(UI["tl_snap"]), 2)); p.drawLine(QPointF(self.HEAD, y), QPointF(W, y))
        if self.snap_line is not None:
            x = self.t2x(self.snap_line); p.setPen(QPen(QColor(UI["tl_snap"]), 1, Qt.DashLine)); p.drawLine(QPointF(x, self.RULER), QPointF(x, H))
        p.setClipping(False); p.setClipRect(QRect(0, self.RULER, self.HEAD, H))
        p.fillRect(QRect(0, self.RULER, self.HEAD, H), QColor(UI["tl_bg"]))
        for tr, y, h in lanes: self.draw_header(p, tr, y, h)
        p.setClipping(False); self.draw_ruler(p, W)
        x = self.t2x(self.app.t)
        if x >= self.HEAD:
            p.setPen(QPen(QColor(UI["tl_playhead"]), float(UI["tl_playhead_w"]))); p.drawLine(QPointF(x, self.RULER - 4), QPointF(x, H))
            p.setPen(Qt.NoPen); p.setBrush(QColor(UI["tl_playhead_head"]))
            p.drawPolygon(QPolygonF([QPointF(x - 6, 4), QPointF(x + 6, 4), QPointF(x + 6, 16), QPointF(x, 24), QPointF(x - 6, 16)]))
        d = self.drag
        if d and d.get("mode") == "marquee" and d.get("moved"):
            rr = QRectF(QPointF(d["x0"], d["y0"]), QPointF(d["x"], d["y"])).normalized()
            p.setClipRect(QRectF(self.HEAD, self.RULER, W - self.HEAD, H - self.RULER)); mc = QColor(UI["marquee"]); fc = QColor(mc); fc.setAlpha(50)
            p.setPen(QPen(mc, 1)); p.setBrush(fc); p.drawRect(rr)
    def draw_header(self, p, tr, y, h):
        r = QRectF(6, y + 2, self.HEAD - 12, h - 4); p.setPen(Qt.NoPen); p.setBrush(QColor(UI["tl_header_bg"])); p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("#9fb3d9")); fm = p.fontMetrics()
        p.drawText(r.adjusted(10, 0, -78, 0), Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(tr["name"], Qt.ElideRight, int(r.width() - 88)))
        for k, rc, lab, act in self.chips(tr, y, h):
            p.setPen(Qt.NoPen); p.setBrush(QColor("#2f6bff" if act else "#18233d")); p.drawRoundedRect(rc, 5, 5)
            p.setPen(QColor("#ffffff" if act else "#6b7a99")); p.drawText(rc, Qt.AlignCenter, lab)
    def draw_ruler(self, p, W):
        p.fillRect(QRect(0, 0, W, self.RULER), QColor(UI["tl_ruler_bg"]))
        steps = [1 / 30, .1, .25, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
        major = next((s for s in steps if s * self.pps >= 90), 600); minor = major / 5
        t1 = self.x2t(W); i = int(math.floor(max(0, self.x2t(self.HEAD)) / minor))
        while i * minor <= t1:
            t = i * minor; x = self.t2x(t)
            if x >= self.HEAD:
                mj = abs(t / major - round(t / major)) < 1e-6
                p.setPen(QColor("#4a5f8a" if mj else "#26324d")); p.drawLine(QPointF(x, self.RULER - (10 if mj else 5)), QPointF(x, self.RULER))
                if mj:
                    p.setPen(QColor("#7d8fb3"))
                    lab = f"{int(t // 60):02d}:{int(t % 60):02d}" + (f".{int(round((t % 1) * self.app.proj.fps)):02d}f" if major < 1 else "")
                    p.drawText(QPointF(x + 4, 13), lab)
            i += 1
        p.fillRect(QRect(0, 0, self.HEAD, self.RULER), QColor(UI["tl_ruler_bg"]))
        p.setPen(QColor("#5aa2ff")); p.drawText(QRect(10, 0, self.HEAD, self.RULER), Qt.AlignVCenter, fmt_time(self.app.t, self.app.proj.fps))
    def _draw_clip_core(self, p, c, y, h, W):
        x = self.t2x(c["start"]); w = c["dur"] * self.pps
        if x > W or x + w < self.HEAD: return
        r = QRectF(x, y + 2, max(w, 3), h - 4); col = QColor(CLIP_COLORS.get(c["kind"], "#1f4fbf"))
        sel = c["id"] == self.app.sel; path = QPainterPath(); path.addRoundedRect(r, UI["tl_radius"], UI["tl_radius"])
        p.save(); p.setClipPath(path, Qt.IntersectClip); p.fillRect(r, col.darker(140)); k = c["kind"]
        if k in ("video", "image", "gif"):
            th = int(r.height() - (16 if k == "video" else 0))
            if th > 8:
                first = self.app.thumbs.thumb(c["path"], k, c["inp"] if k == "video" else 0, th)
                tw = max(8.0, float(first.width()) if first else th * 16 / 9)
                x0 = max(r.left(), self.HEAD); i = int((x0 - r.left()) // tw); xx = r.left() + i * tw
                while xx < min(r.right(), W):
                    tt = 0.0
                    if k == "video": tt = min(c["inp"] + i * tw / self.pps, max(0, c["src_dur"] - 0.05))
                    img = self.app.thumbs.thumb(c["path"], k, tt, th)
                    if img: p.drawImage(QPointF(xx, r.top()), img)
                    xx += tw; i += 1
        if k in ("video", "audio"):
            band = QRectF(r.left(), r.bottom() - 16, r.width(), 16) if k == "video" else QRectF(r.left(), r.top() + 16, r.width(), r.height() - 16)
            p.fillRect(band, QColor(0, 0, 0, 90)); self.draw_wave(p, c, band, W)
        if k == "text":
            p.setPen(QColor("#e9ddff")); p.drawText(r.adjusted(8, 14, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, "T  " + c["text"].replace("\n", " "))
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 15), QColor(0, 0, 0, 120))
        p.setPen(QColor("#e6eeff")); fm = p.fontMetrics()
        p.drawText(r.adjusted(6, 0, -4, 0).toRect().adjusted(0, 0, 0, -int(r.height() - 15)), Qt.AlignVCenter,
                   fm.elidedText(f"{c['name']}  ·  {c['dur']:.2f}s", Qt.ElideRight, max(0, int(r.width() - 10))))
        p.restore()
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(UI["tl_select"]) if sel else col.lighter(130), 2 if sel else 1)); p.drawRoundedRect(r, UI["tl_radius"], UI["tl_radius"])
        if sel:
            hw = float(UI["tl_handle_w"]); p.setPen(Qt.NoPen); p.setBrush(QColor(UI["tl_select"]))
            p.drawRoundedRect(QRectF(r.left() + 1, r.center().y() - 9, hw, 18), 2, 2); p.drawRoundedRect(QRectF(r.right() - hw - 1, r.center().y() - 9, hw, 18), 2, 2)
        self.draw_keys(p, c, r, sel, W)
    @staticmethod
    def key_times(c): return sorted({round(kf["t"], 3) for pr in c.get("props", {}).values() for kf in pr["k"]})
    def draw_keys(self, p, c, r, sel, W):
        times = self.key_times(c)
        if not times: return
        ks = float(UI["key_size"]); cy = r.center().y()
        picked = self.app.sel_keys if (sel and getattr(self.app, "sel_keys_clip", None) == c["id"]) else ()
        base = QColor(UI["key_color_sel"] if sel else UI["key_color"]); pk = QColor(UI["key_picked"])
        p.save()
        for t in times:
            kx = r.left() + t * self.pps
            if kx < self.HEAD - ks or kx > W + ks: continue
            on = t in picked; sz = ks * (1.25 if on else 1.0)
            p.setPen(QPen(QColor(0, 0, 0, 215), 1.6)); p.setBrush(pk if on else base)
            p.drawPolygon(QPolygonF([QPointF(kx, cy - sz), QPointF(kx + sz, cy), QPointF(kx, cy + sz), QPointF(kx - sz, cy)]))
        p.restore()
    # ---- keyframe / box selection helpers ----
    def sel_lane(self):
        c = self.app.sel_clip()
        if not c or not c.get("props"): return None
        for tr, y, h in self.lanes():
            if tr["id"] == c["track"]: return c, y, h
        return None
    def key_hit(self, x, y):
        L = self.sel_lane()
        if not L: return None
        c, ty, h = L; ks = float(UI["key_size"]) + 2; cy = ty + h / 2
        if abs(y - cy) > ks + 2: return None
        cx0 = self.t2x(c["start"]); cx1 = cx0 + c["dur"] * self.pps; best = None
        for t in self.key_times(c):
            kx = cx0 + t * self.pps
            if kx - cx0 < 9 or cx1 - kx < 9: continue      # keys on the clip edge: leave the edge to the trim handle
            dd = abs(x - kx)
            if dd <= ks and (best is None or dd < best[0]): best = (dd, t)
        return (c, best[1]) if best else None
    def start_marquee(self, x, y, keys, add):
        app = self.app; base = set(); kbase = set()
        if add and not keys: base = set(getattr(app, "multi", set()) or ()) | ({app.sel} if app.sel else set())
        if add and keys: kbase = set(getattr(app, "sel_keys", set()))
        self.drag = {"mode": "marquee", "x0": x, "y0": y, "x": x, "y": y, "keys": keys, "base": base, "kbase": kbase, "moved": False}
    def start_keymove(self, kh, x, mods):
        app = self.app; c, t = kh; tr = app.proj.track(c["track"])
        cur = set(getattr(app, "sel_keys", set())) if getattr(app, "sel_keys_clip", None) == c["id"] else set()
        if mods & Qt.ShiftModifier:
            cur.discard(t) if t in cur else cur.add(t)
        elif t not in cur: cur = {t}
        app.sel_keys = cur; app.sel_keys_clip = c["id"]; app.multi = set(); self.update()
        if (tr and tr["locked"]) or not cur: return
        orig = [(kf, kf["t"]) for pr in c["props"].values() for kf in pr["k"] if round(kf["t"], 3) in cur]
        self.drag = {"mode": "keymove", "clip": c, "t0": self.x2t(x), "orig": orig, "before": app.begin(), "moved": False}
    def marquee_move(self, x, y):
        d = self.drag; app = self.app; d["x"], d["y"] = x, y
        if not d["moved"] and abs(x - d["x0"]) + abs(y - d["y0"]) > 4: d["moved"] = True
        if not d["moved"]: return
        rect = QRectF(QPointF(d["x0"], d["y0"]), QPointF(x, y)).normalized()
        if d["keys"]:
            L = self.sel_lane()
            if L:
                c, ly, lh = L; ks = float(UI["key_size"]); cx0 = self.t2x(c["start"])
                hit = {t for t in self.key_times(c) if rect.intersects(QRectF(cx0 + t * self.pps - ks, ly + lh / 2 - ks, 2 * ks, 2 * ks))}
                app.sel_keys = hit | d["kbase"]; app.sel_keys_clip = c["id"]
        else:
            ids = set()
            for tr, ty, h in self.lanes():
                if tr["locked"]: continue
                for c in app.proj.clips:
                    if c["track"] == tr["id"] and rect.intersects(QRectF(self.t2x(c["start"]), ty, c["dur"] * self.pps, h)): ids.add(c["id"])
            app.set_multi(with_groups(app, ids) | d["base"])
        self.update()
    def keymove(self, x):
        d = self.drag; c = d["clip"]; fps = self.app.proj.fps; dt = self.x2t(x) - d["t0"]
        if not d["moved"] and abs(dt) * self.pps < 3: return
        d["moved"] = True; dt = round(dt * fps) / fps; ts = [t for _, t in d["orig"]]
        if ts: dt = max(-min(ts), min(c["dur"] - max(ts), dt))
        for kf, t0 in d["orig"]: kf["t"] = t0 + dt
        for pr in c["props"].values(): pr["k"].sort(key=lambda k: k["t"])
        self.app.sel_keys = {round(t0 + dt, 3) for _, t0 in d["orig"]}
        self.app.request_render(); self.update()
    def draw_wave(self, p, c, band, W):
        peaks = self.app.thumbs.wave(c["path"])
        vk = c["props"]["volume"]["k"]; vconst = c["props"]["volume"]["v"] / 100
        x0, x1 = int(max(band.left(), self.HEAD)), int(min(band.right(), W))
        if peaks is not None and len(peaks):
            mid, amp = band.center().y(), band.height() / 2 - 1; lines = []
            for xi in range(x0, x1, 2):
                lt = (xi - band.left()) / self.pps; idx = int((c["inp"] + lt) * 100)
                if 0 <= idx < len(peaks):
                    a = min(1.0, peaks[idx] * (prop_at(c, "volume", lt) / 100 if vk else vconst)) * amp
                    lines.append(QLineF(xi, mid - a, xi, mid + a))
            p.setPen(QPen(QColor(UI["tl_wave"]), 1)); p.drawLines(lines)
        pts = []
        for xi in range(x0, x1 + 4, 4):
            v = prop_at(c, "volume", (xi - band.left()) / self.pps) if vk else vconst * 100
            pts.append(QPointF(xi, band.bottom() - min(v, 200) / 200 * band.height()))
        if len(pts) > 1: p.setPen(QPen(QColor(UI["tl_wave_vol"]), 1.2)); p.drawPolyline(QPolygonF(pts))
    # ---- interaction ----
    def hit_clip(self, x, y):
        lane = {tr["id"]: (ty, h) for tr, ty, h in self.lanes()}
        for c in reversed(self.app.proj.clips):
            if c["track"] not in lane: continue
            ty, h = lane[c["track"]]
            if not (ty <= y < ty + h): continue
            cx, cw = self.t2x(c["start"]), c["dur"] * self.pps
            if cx - 3 <= x <= cx + cw + 3:
                edge = None
                if cw >= 14: edge = "trim_l" if x - cx < 7 else "trim_r" if cx + cw - x < 7 else None
                return c, edge
        return None
    def snap_points(self, exclude):
        pts = [0.0, self.app.t]
        for c in self.app.proj.clips:
            if c["id"] != exclude: pts += [c["start"], c["start"] + c["dur"]]
        return pts
    def snap(self, t, pts):
        on = self.app.snap_on
        if QApplication.keyboardModifiers() & (Qt.ShiftModifier | Qt.ControlModifier): on = not on
        if not on: return t, None
        thr = 8 / self.pps; best = None
        for s in pts:
            d = abs(s - t)
            if d < thr and (best is None or d < best[0]): best = (d, s)
        return (best[1], best[1]) if best else (t, None)
    def _press_core(self, e):
        if not self.app.proj: return
        pos = e.position(); x, y = pos.x(), pos.y(); app = self.app
        if e.button() == Qt.MiddleButton: self.drag = {"mode": "pan", "x": x, "y": y, "h": self.hbar.value(), "v": self.vbar.value()}; return
        if e.button() != Qt.LeftButton: return
        if y < self.RULER and x >= self.HEAD: self.drag = {"mode": "scrub"}; app.seek(self.x2t(x)); return
        if x < self.HEAD:
            for tr, ty, h in self.lanes():
                for k, rc, lab, act in self.chips(tr, ty, h):
                    if rc.contains(pos):
                        b = app.begin(); tr[k] = not tr[k]; app.commit(b); app.on_changed(); return
            return
        mods = e.modifiers(); lane = self.sel_lane(); add = bool(mods & (Qt.ControlModifier | Qt.ShiftModifier))
        in_lane = bool(lane and lane[1] <= y < lane[1] + lane[2])
        if (mods & Qt.AltModifier) and in_lane: self.start_marquee(x, y, True, add); return
        kh = self.key_hit(x, y)
        if kh: self.start_keymove(kh, x, mods); return
        hit = self.hit_clip(x, y)
        if hit:
            c, edge = hit; app.select(c["id"]); tr = app.proj.track(c["track"])
            if tr and tr["locked"]: return
            self.drag = {"mode": edge or "move", "clip": c, "start": c["start"], "inp": c["inp"], "dur": c["dur"],
                         "keys": copy.deepcopy(c["props"]), "before": app.begin(), "off": self.x2t(x) - c["start"]}
        else:
            self.start_marquee(x, y, in_lane, add)
    def _move_core(self, e):
        if not self.app.proj: return
        pos = e.position(); x, y = pos.x(), pos.y(); d = self.drag; app = self.app
        if not d:
            hit = self.hit_clip(x, y) if x > self.HEAD and y > self.RULER else None
            kh = self.key_hit(x, y) if x > self.HEAD and y > self.RULER else None
            if kh: self.setCursor(Qt.PointingHandCursor)
            elif hit and hit[1]: self.setCursor(Qt.SizeHorCursor)
            else: self.unsetCursor()
            return
        m = d["mode"]
        if m == "pan": self.hbar.setValue(int(d["h"] - (x - d["x"]))); self.vbar.setValue(int(d["v"] - (y - d["y"]))); return
        if m == "scrub": app.seek(max(0, self.x2t(x))); return
        if m == "marquee": self.marquee_move(x, y); return
        if m == "keymove": self.keymove(x); return
        c = d["clip"]; fps = app.proj.fps
        if m == "move":
            ns = max(0, self.x2t(x) - d["off"]); pts = self.snap_points(c["id"])
            s1, l1 = self.snap(ns, pts); s2, l2 = self.snap(ns + c["dur"], pts)
            if l1 is not None and (l2 is None or abs(s1 - ns) <= abs(s2 - ns - c["dur"])): ns = s1; self.snap_line = l1
            elif l2 is not None: ns = s2 - c["dur"]; self.snap_line = l2
            else: self.snap_line = None
            c["start"] = max(0.0, ns)
            want = "audio" if c["kind"] == "audio" else "video"; lanes = self.lanes(); self.drop_hint = None
            over = next(((tr, ty, h) for tr, ty, h in lanes if ty <= y < ty + h), None)
            if over:
                if over[0]["kind"] == want and not over[0]["locked"]: c["track"] = over[0]["id"]
            elif lanes:
                if y < lanes[0][1]: self.drop_hint = "top"
                elif y > lanes[-1][1] + lanes[-1][2]: self.drop_hint = "bottom"
        elif m == "trim_l":
            end = d["start"] + d["dur"]; ns, self.snap_line = self.snap(self.x2t(x), self.snap_points(c["id"]))
            ns = max(0.0, min(ns, end - 1 / fps))
            if c["kind"] in ("video", "audio"): ns = max(ns, d["start"] - d["inp"])
            delta = ns - d["start"]; c["start"] = ns; c["dur"] = end - ns
            if c["kind"] not in ("image", "text"): c["inp"] = max(0.0, d["inp"] + delta)
            for name, pr in c["props"].items():
                for kf, k0 in zip(pr["k"], d["keys"][name]["k"]): kf["t"] = k0["t"] - delta
        elif m == "trim_r":
            ne, self.snap_line = self.snap(self.x2t(x), self.snap_points(c["id"])); ne = max(ne, c["start"] + 1 / fps)
            if c["kind"] in ("video", "audio") and c["src_dur"] > 0: ne = min(ne, c["start"] + c["src_dur"] - c["inp"])
            c["dur"] = ne - c["start"]
        app.request_render(); self.update()
    def mouseReleaseEvent(self, e):
        d = self.drag; self.drag = None; self.snap_line = None; app = self.app
        if d and d["mode"] == "keymove" and d["moved"]:
            moved = {id(kf) for kf, _ in d["orig"]}
            for pr in d["clip"]["props"].values():     # a moved key replaces any key it lands on
                mt = [k["t"] for k in pr["k"] if id(k) in moved]
                pr["k"] = [k for k in pr["k"] if id(k) in moved or all(abs(k["t"] - t) > 1e-4 for t in mt)]
                pr["k"].sort(key=lambda k: k["t"])
            app.commit(d["before"]); app.on_changed()
        elif d and d["mode"] == "marquee" and not d["moved"]:     # plain click on empty space
            if d["keys"] and getattr(app, "sel_keys", None): app.sel_keys = set()
            else: app.set_multi(set()); app.seek(self.x2t(d["x0"]))
        if d and d["mode"] in ("move", "trim_l", "trim_r"):
            c = d["clip"]; want = "audio" if c["kind"] == "audio" else "video"
            if d["mode"] == "move":
                hint = self.drop_hint; self.drop_hint = None
                if hint: c["track"] = app.proj.add_track(want, 0 if hint == "top" else len(app.proj.tracks))["id"]
                elif not app.track_free(c["track"], c["start"], c["start"] + c["dur"], c["id"]):
                    idx = app.proj.track_index(c["track"])
                    c["track"] = app.proj.add_track(want, idx if want == "video" else idx + 1)["id"]
            app.commit(d["before"]); app.on_changed()
        self.update()
    def wheelEvent(self, e):
        dy, dx = e.angleDelta().y(), e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            mx = e.position().x(); self.set_zoom(self.pps * (1.15 if dy > 0 else 1 / 1.15), (self.x2t(mx), mx))
        elif e.modifiers() & Qt.ShiftModifier or dx: self.hbar.setValue(self.hbar.value() - (dy or dx))
        elif self.vbar.isVisible(): self.vbar.setValue(self.vbar.value() - dy // 2)
        else: self.hbar.setValue(self.hbar.value() - dy)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.setDropAction(Qt.CopyAction); e.accept()
    def dragMoveEvent(self, e): e.setDropAction(Qt.CopyAction); e.accept()
    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]; pos = e.position()
        t, _ = self.snap(max(0.0, self.x2t(pos.x())), self.snap_points(None))
        over = next((tr["id"] for tr, ty, h in self.lanes() if ty <= pos.y() < ty + h), None)
        self.app.add_files(paths, t, over); e.setDropAction(Qt.CopyAction); e.accept()
    def _context_core(self, e):
        if not self.app.proj: return
        x, y = e.pos().x(), e.pos().y(); app = self.app; m = QMenu(self)
        if x < self.HEAD:
            lane = next(((tr, ty, h) for tr, ty, h in self.lanes() if ty <= y < ty + h), None)
            if lane:
                tr = lane[0]
                m.addAction("Rename track", lambda: app.rename_track(tr)); m.addAction("Delete track", lambda: app.delete_track(tr))
                m.addSeparator()
            m.addAction("Add video track", lambda: app.add_track("video")); m.addAction("Add audio track", lambda: app.add_track("audio"))
        else:
            hit = self.hit_clip(x, y)
            if not hit: return
            app.select(hit[0]["id"])
            m.addAction("Split at playhead", app.split); m.addAction("Duplicate", app.duplicate); m.addAction("Copy", app.copy_clip)
            m.addAction("Replace media…", app.replace_media)
            if hit[0].get("kind") == "video": m.addAction("Extract audio", app.extract_audio)
            m.addAction("Replace media…", app.replace_media) if False else None
            m.addAction("Add / remove keyframe", app.key_all); m.addSeparator(); m.addAction("Delete", app.delete_sel)
        m.exec(e.globalPos())
    def mousePressEvent(self, e):
        app = self.app
        if not app.proj: return
        if not hasattr(app, "multi"): app.multi = set()
        pos = e.position(); x, y = pos.x(), pos.y()
        if e.button() == Qt.LeftButton and x >= self.HEAD and (e.modifiers() & Qt.ControlModifier):
            hit = self.hit_clip(x, y)
            if hit:
                ids = _group_ids(app, hit[0])
                if hit[0]["id"] in app.multi: app.multi -= ids
                else:
                    if app.sel: app.multi |= _group_ids(app, app.sel_clip()) if app.sel_clip() else set()
                    app.multi |= ids
                app.sel = hit[0]["id"]; app.refresh_ui(); self.update(); return
        self._press_core(e)
        d = self.drag
        if app.sel is None: app.multi = set()
        if d and d.get("mode") == "move":
            c = d["clip"]
            if c["id"] not in app.multi: app.multi = _group_ids(app, c)
            d["grp"] = [(o, o["start"]) for o in app.proj.clips if o["id"] in app.multi and o["id"] != c["id"]]
    def mouseMoveEvent(self, e):
        self._move_core(e)
        d = self.drag
        if d and d.get("mode") == "move" and d.get("grp"):
            c = d["clip"]; delta = c["start"] - d["start"]; mn = min(s for _, s in d["grp"])
            if mn + delta < 0: delta = -mn; c["start"] = d["start"] + delta
            for o, s in d["grp"]: o["start"] = s + delta
            self.app.request_render(); self.update()
    def _proxy_states(self):
        """Finished proxy pieces per video file. Checked twice a second by a timer, never on every paint."""
        if not hasattr(self, "_pxy_timer"):
            self._pxy = {}; self._pxy_timer = QTimer(self); self._pxy_timer.setInterval(500)
            self._pxy_timer.timeout.connect(self._proxy_poll); self._pxy_timer.start()
        return self._pxy
    def _proxy_poll(self):
        P = self.app.proj
        if not P or not getattr(self.app.pool, "use_proxy", False):
            if self._pxy: self._pxy = {}; self.update()
            return
        self.app.pool.prepare(P.clips, self.app.t)
        new = {}
        for c, off in proxy_sources(P.clips):
            if c.get("kind") == "video" and c.get("path") and c["path"] not in new: new[c["path"]] = proxy_pieces(c["path"])
        if new != self._pxy: self._pxy = new; self.update()
    def _draw_proxy_bars(self):
        """Under the ruler, for every clip (also inside compound clips):
        video: grey = the whole clip, yellow = the part that already has a finished proxy piece;
        image / gif: cyan = no proxy needed (always ready). Text and audio have no bar."""
        self._proxy_states(); P = self.app.proj
        if not P: return
        use = getattr(self.app.pool, "use_proxy", False)
        p = QPainter(self); p.setPen(Qt.NoPen); W = self.width(); y = self.RULER - 5
        for c, off in proxy_sources(P.clips):
            k = c.get("kind")
            if k not in ("video", "image", "gif"): continue
            s = c["start"] + off; d = c["dur"]; inp = c.get("inp", 0.0)
            x0 = max(self.HEAD, self.t2x(s)); x1 = min(W, self.t2x(s + d))
            if x1 <= x0: continue
            if k != "video":
                p.setBrush(QColor("#2fb6ff")); p.drawRect(QRectF(x0, y, x1 - x0, 3)); continue
            if not use: continue
            p.setBrush(QColor("#3a3f4b")); p.drawRect(QRectF(x0, y, x1 - x0, 3))
            p.setBrush(QColor("#f2c94c"))
            for kk, (ks, ke) in (self._pxy.get(c.get("path")) or {}).items():
                a = max(ks, inp); b = min(ke, inp + d)
                if b <= a: continue
                px0 = max(self.HEAD, self.t2x(s + (a - inp))); px1 = min(W, self.t2x(s + (b - inp)))
                if px1 > px0: p.drawRect(QRectF(px0, y, px1 - px0, 3))
        p.end()
    def paintEvent(self, e):
        self._paint_core(e)
        app = self.app
        if not app.proj: return
        self._draw_proxy_bars()
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setClipRect(QRectF(self.HEAD, self.RULER, self.width() - self.HEAD, self.height() - self.RULER))
        lane = {tr["id"]: (ty, h) for tr, ty, h in self.lanes()}; multi = getattr(app, "multi", set())
        for c in app.proj.clips:
            if c["track"] not in lane: continue
            ty, h = lane[c["track"]]; r = QRectF(self.t2x(c["start"]), ty, c["dur"] * self.pps, h).adjusted(1, 1, -1, -1)
            if c.get("group"): p.fillRect(QRectF(r.left() + 3, r.bottom() - 4, max(0, r.width() - 6), 3), QColor("#f5a524"))
            if c["id"] in multi and len(multi) > 1:
                p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(r, 6, 6)
        p.end()
    def draw_clip(self, p, c, y, h, W):
        if c.get("kind") != "compound": return self._draw_clip_core(p, c, y, h, W)
        r = QRectF(self.t2x(c["start"]), y, max(2, c["dur"] * self.pps), h)
        if r.right() < self.HEAD or r.left() > W: return
        path = QPainterPath(); path.addRoundedRect(r.adjusted(.5, .5, -.5, -.5), 6, 6); p.fillPath(path, QColor("#1d4a52"))
        p.save(); p.setClipPath(path)
        subs = c.get("subtracks", []); n = max(1, len(subs)); off = c["start"] - c["inp"]
        for ch in c.get("children", []):
            i = next((k for k, st in enumerate(subs) if st["id"] == ch["track"]), 0)
            cx = self.t2x(ch["start"] + off); bh = (h - 20) / n
            p.fillRect(QRectF(cx, y + 18 + i * bh, ch["dur"] * self.pps, max(2, bh - 2)),
                       QColor("#2f7f8a") if ch["kind"] != "audio" else QColor("#2f6b4f"))
        p.restore()
        p.setPen(QColor("#e8fbff")); f = QFont("Segoe UI"); f.setPixelSize(11); f.setBold(True); p.setFont(f)
        p.drawText(r.adjusted(8, 2, -4, 0), Qt.AlignLeft | Qt.AlignTop, c.get("name", "Compound clip"))
        if self.app.sel == c["id"]: p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(Qt.NoBrush); p.drawPath(path)
    def contextMenuEvent(self, e):
        if not self.app.proj: return
        x, y = e.pos().x(), e.pos().y()
        if x < self.HEAD: return self._context_core(e)
        hit = self.hit_clip(x, y)
        if not hit: return
        app = self.app; c = hit[0]
        if c["id"] not in getattr(app, "multi", set()): app.multi = _group_ids(app, c)
        app.sel = c["id"]; app.refresh_ui(); self.update()
        m = QMenu(self)
        def add(text, fn, sc=None, icon=None, enabled=True):
            a = m.addAction(text)
            if icon: a.setIcon(app_icon(icon))
            if sc: a.setShortcut(QKeySequence(sc)); a.setShortcutVisibleInContextMenu(True)
            a.setEnabled(bool(enabled and fn))
            if fn: a.triggered.connect(fn)
        A = lambda n: getattr(app, n, None)
        multi = len(app.multi) > 1
        add("Copy", A("copy_clip"), "Ctrl+C", "duplicate")
        add("Cut", (lambda: (app.copy_clip(), app.delete_sel())) if A("copy_clip") else None, "Ctrl+X", "cut")
        add("Delete", app.delete_sel, "Del", "delete"); m.addSeparator()
        add("Split", app.split, "Ctrl+B", "split")
        add("Delete left of playhead", app.trim_left, "Q", "trim_left")
        add("Delete right of playhead", app.trim_right, "W", "trim_right")
        add("Duplicate", app.duplicate, "Ctrl+D"); m.addSeparator()
        add("Create compound clip", app.make_compound, "Alt+G", "compound", multi)
        add("Uncompound clip", app.uncompound, "Alt+Shift+G", None, c.get("kind") == "compound")
        add("Group", app.group_sel, "Ctrl+G", "group", multi)
        add("Ungroup", app.ungroup_sel, "Ctrl+Shift+G", None, bool(c.get("group"))); m.addSeparator()
        add("Extract audio", A("extract_audio"), None, "extract", c["kind"] == "video")
        add("Replace media…", A("replace_media"), None, "replace", c["kind"] in ("video", "image", "gif", "audio"))
        add("Add / remove keyframe", A("key_all"), None, "keyframe")
        m.exec(e.globalPos())


class TimelinePanel(QFrame):
    def __init__(self, app):
        super().__init__(); self.setObjectName("Panel"); self.setMinimumSize(1, 1)
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 6, 8, 6); lay.setSpacing(4)
        bar = QHBoxLayout(); bar.setSpacing(2)
        A = lambda n: getattr(app, n, None)   # a missing method just disables its button
        for txt, tip, cb in [("@undo", "Undo (Ctrl+Z)", app.do_undo), ("@redo", "Redo", app.do_redo), (None, None, None),
                             ("@split", "Split (Ctrl+B)", app.split), ("@trim_left", "Delete left of playhead (Q)", A("trim_left")),
                             ("@trim_right", "Delete right of playhead (W)", A("trim_right")),
                             ("@duplicate", "Duplicate", app.duplicate), ("@delete", "Delete", app.delete_sel), (None, None, None),
                             ("@text", "Add text", app.add_text), ("@keyframe", "Keyframe", app.key_all), (None, None, None),
                             ("@group", "Group (Ctrl+G)", A("group_sel")), ("@compound", "Compound clip (Alt+G)", A("make_compound")), (None, None, None),
                             ("@extract", "Extract audio", A("extract_audio")), ("@replace", "Replace media", A("replace_media")), (None, None, None),
                             ("+V", "Add video track", lambda: app.add_track("video")), ("+A", "Add audio track", lambda: app.add_track("audio"))]:
            if txt is None:
                s = QFrame(); s.setFixedSize(1, 18); s.setStyleSheet("background:#22314f;"); bar.addSpacing(4); bar.addWidget(s); bar.addSpacing(4)
            else:
                w = tool("" if txt.startswith("@") else txt, tip, cb, icon=txt[1:] if txt.startswith("@") else None)
                if cb is None: w.setEnabled(False)
                bar.addWidget(w)
        bar.addStretch()
        self.snap_btn = tool("Snap", "Auto snap (timeline + viewport)", app.toggle_snap, True, icon="magnet"); self.snap_btn.setChecked(app.snap_on)
        bar.addWidget(self.snap_btn)
        bar.addWidget(tool("", "Zoom out", lambda: app.timeline.set_zoom(app.timeline.pps / 1.25), icon="zoom_out"))
        self.zoom = QSlider(Qt.Horizontal); self.zoom.setRange(0, 1000); self.zoom.setFixedWidth(120)
        self.zoom.valueChanged.connect(lambda v: app.timeline.set_zoom(2 * (1000 ** (v / 1000))) if not getattr(self, "_lock", False) else None)
        bar.addWidget(self.zoom); bar.addWidget(tool("", "Zoom in", lambda: app.timeline.set_zoom(app.timeline.pps * 1.25), icon="zoom_in"))
        bar.addWidget(tool("", "Zoom to fit", lambda: app.timeline.zoom_fit(), icon="zoom_fit"))
        lay.addLayout(bar)
        app.timeline = Timeline(app); g = QGridLayout(); g.setSpacing(0)
        g.addWidget(app.timeline, 0, 0); g.addWidget(app.timeline.vbar, 0, 1); g.addWidget(app.timeline.hbar, 1, 0)
        lay.addLayout(g, 1)

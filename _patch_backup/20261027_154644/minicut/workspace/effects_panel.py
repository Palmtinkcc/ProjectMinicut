"""Effects tab of the inspector: "+ Effect" menu and one card per effect layer (enable, reorder, delete, parameters)."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.theme import *
from ..shared.core import *
from ..shared.widgets import *
from ..shared.ui import *
from .preview_widgets import EffectPicker, fx_preview, sample_frame
from ..render.effects import FX, FX_CATS, new_effect, fx_defaults, param_viz


def _fmt(v, kind, lo, hi):
    if kind == "int": return str(int(v))
    return ("%.0f" % v) if (hi - lo) >= 60 else ("%.1f" % v).rstrip("0").rstrip(".")


class EffectsPanel(QWidget):
    def __init__(self, app, area_panel):
        super().__init__(); self.app = app; self.area = area_panel; self.sig = None; self.cards = {}; self.loading = False
        self._area_id = None; self._before = None
        self._ct = QTimer(self); self._ct.setSingleShot(True); self._ct.setInterval(450); self._ct.timeout.connect(self._commit)
        self.setStyleSheet("QFrame#FxCard{background:#202024; border:1px solid #2c2c33; border-radius:12px;}"); self._base = None
        self._pt = QTimer(self); self._pt.setSingleShot(True); self._pt.setInterval(140); self._pt.timeout.connect(self._update_thumbs); self._dirty = set()
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        top = QHBoxLayout(); top.addStretch(); self.add_btn = Btn("Add effect", "plus", "accent", "Pick an effect from the gallery (with a preview of each)", self.open_picker); top.addWidget(self.add_btn); v.addLayout(top)
        self.host = QWidget(); self.lay = QVBoxLayout(self.host); self.lay.setContentsMargins(0, 0, 0, 0); self.lay.setSpacing(8); v.addWidget(self.host)
        self.empty = QLabel("No effects yet\nPress “Add effect” to see them with a preview"); self.empty.setObjectName("Dim"); self.empty.setAlignment(Qt.AlignCenter); self.empty.setMinimumHeight(90)
        v.addWidget(self.empty)
        self.area_box = QFrame(); self.area_box.setObjectName("FxCard"); ab = QVBoxLayout(self.area_box); ab.setContentsMargins(8, 8, 8, 8)
        ab.setContentsMargins(6, 6, 6, 6); self.area.layout().setContentsMargins(0, 0, 0, 0)
        self.area_title = QLabel("Area"); ab.addWidget(self.area_title); self.area.setMinimumHeight(520); ab.addWidget(self.area); self.area_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); self.area_box.hide(); v.addWidget(self.area_box)   # never widen the side panel
        v.addStretch(1)
    # ---- model helpers ----
    def area_holder(self, c):
        return next((e["p"] for e in c.get("effects", []) if e["id"] == self._area_id), None) if c else None
    def _find(self, c, eid): return next((e for e in c.get("effects", []) if e["id"] == eid), None) if c else None
    def _commit(self):
        if self._before is not None: self.app.commit(self._before); self._before = None
        self.app.request_render()   # the final, full-quality frame after the slider stops
    def _edit(self, eid, key, val):
        """Live parameter change (one undo step per burst of edits)."""
        if self.loading: return
        c = self.app.sel_clip(); e = self._find(c, eid)
        if e is None: return
        if self._before is None: self._before = self.app.begin()
        e["p"][key] = val; self._ct.start(); self.app.preview_fast_for(0.2); self.app.request_render(); self._dirty.add(eid); self._pt.start()
    def _structural(self, fn, rebuild=True):
        c = self.app.sel_clip()
        if c is None: return
        self._commit(); self.app.checkpoint(); fn(c); self.app.on_changed(insp=False)
        if rebuild: QTimer.singleShot(0, lambda: self._rebuild(self.app.sel_clip()))
    def open_picker(self):
        if self.app.sel_clip() is None: return
        pk = EffectPicker(self.app, self.window()); pk.picked.connect(self.add_effect); g = self.add_btn.mapToGlobal(QPoint(self.add_btn.width() - pk.width(), self.add_btn.height() + 4))
        scr = self.screen().availableGeometry(); pk.move(max(scr.left() + 4, g.x()), min(g.y(), scr.bottom() - pk.height() - 4)); pk.show()
    def _update_thumbs(self):
        c = self.app.sel_clip()
        if c is None: return
        for eid in list(self._dirty):
            e = self._find(c, eid); info = self.cards.get(eid)
            if e is None or not info or "thumb" not in info: continue
            solo = copy.deepcopy(e); solo["on"] = True; info["thumb"].setPixmap(self._thumb_pm(solo))
        self._dirty.clear()
    def _thumb_pm(self, e):
        if self._base is None: self._base = sample_frame(self.app, 160)
        return fx_preview(self.app, [e], self._base).scaled(72, 41, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    def add_effect(self, typ):
        def go(c):
            c.setdefault("effects", []).append(new_effect(typ))
        self._structural(go)
    def _move(self, eid, d):
        def go(c):
            fx = c["effects"]; i = next((i for i, e in enumerate(fx) if e["id"] == eid), None)
            if i is not None and 0 <= i + d < len(fx): fx[i], fx[i + d] = fx[i + d], fx[i]
        self._structural(go)
    def _delete(self, eid):
        def go(c):
            c["effects"] = [e for e in c.get("effects", []) if e["id"] != eid]
            if self._area_id == eid: self._area_id = None
        self._structural(go)
    def _set_spill(self, eid, on):
        if self.loading: return
        def go(c):
            e = self._find(c, eid)
            if e: e["spill"] = bool(on)
        self._structural(go, rebuild=False)
    @staticmethod
    def _track_of(viz, p):
        """The track of a slider: a fixed gradient, or a fade towards the colour that the effect uses (it follows that colour)."""
        ck = viz.get("color_key")
        if ck:
            col = QColor(p.get(ck, "#ffffff")); a = QColor(col); a.setAlpha(0)
            return {"stops": [(0.0, a), (1.0, col)], "alpha": True}
        return {"stops": viz["stops"], "alpha": viz.get("alpha", False)}
    def _color_changed(self, info, key, col):
        for sl, viz in info.get("viz", ()):
            if viz.get("color_key") == key: sl.setTrack(self._track_of(viz, {key: col}))
    def _toggle(self, eid, on):
        if self.loading: return
        def go(c):
            e = self._find(c, eid)
            if e: e["on"] = bool(on)
        self._structural(go, rebuild=False)
    def _edit_area(self, eid, on):
        self._area_id = eid if on else None
        c = self.app.sel_clip(); self._show_area(c, force=True)
        for k, card in self.cards.items():
            b = card.get("area_btn")
            if b is not None and k != eid: b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
    def _show_area(self, c, force=False):
        e = self._find(c, self._area_id) if self._area_id else None
        self.area_box.setVisible(e is not None)
        if e is not None:
            self.area_title.setText("Area of: %s" % FX[e["type"]]["title"]); self.area.load(c, force=force)
    # ---- building the cards ----
    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0); w = it.widget()
            if w is not None: w.hide(); w.deleteLater()
        self.cards = {}
    def _rebuild(self, c):
        self.loading = True
        try:
            self._clear(); self._base = None
            fx = (c or {}).get("effects", []) if c else []
            self.empty.setVisible(not fx)
            for i, e in enumerate(fx):
                if e.get("type") in FX: self.lay.addWidget(self._card(e, i, len(fx)))
            if self._area_id and not any(e["id"] == self._area_id for e in fx): self._area_id = None
            self._show_area(c, force=True)
        finally: self.loading = False
    def _card(self, e, idx, n):
        spec = FX[e["type"]]; eid = e["id"]; card = QFrame(); card.setObjectName("FxCard"); v = QVBoxLayout(card); v.setContentsMargins(10, 10, 10, 12); v.setSpacing(8)
        info = {"set": {}}; self.cards[eid] = info
        h = QHBoxLayout(); h.setSpacing(10); th = QLabel(); th.setFixedSize(72, 41); th.setStyleSheet("background:#111;border-radius:6px;"); th.setPixmap(self._thumb_pm(dict(copy.deepcopy(e), on=True))); info["thumb"] = th; h.addWidget(th)
        col = QVBoxLayout(); col.setSpacing(4); t = QLabel(spec["title"]); t.setStyleSheet("color:#ececf1;font-weight:700;font-size:13px;background:transparent;border:none;"); col.addWidget(t)
        cb = Toggle("On", bool(e.get("on", True))); cb.toggled.connect(lambda on, eid=eid: self._toggle(eid, on)); col.addWidget(cb); h.addLayout(col, 1)
        bt = QVBoxLayout(); bt.setSpacing(2)
        up = tool("", "Move up (applied earlier)", lambda eid=eid: self._move(eid, -1), icon="angle-up", isize=16); up.setEnabled(idx > 0)
        dn = tool("", "Move down (applied later)", lambda eid=eid: self._move(eid, 1), icon="angle-down", isize=16); dn.setEnabled(idx < n - 1)
        rm = tool("", "Remove this effect", lambda eid=eid: self._delete(eid), icon="delete", isize=16)
        r2 = QHBoxLayout(); r2.setSpacing(0)
        for b in (up, dn, rm): r2.addWidget(b)
        h.addLayout(r2); v.addLayout(h); info["enable"] = cb
        sp = Toggle("Spill outside the media", bool(e.get("spill", False)), "Off: the effect stays inside the edges of the media (cropped). On: it may go beyond the edges (glow, blur, shadows ...).")
        sp.toggled.connect(lambda on, eid=eid: self._set_spill(eid, on)); v.addWidget(sp); info["spill"] = sp
        for key, label_, kind, dflt, lo, hi in spec["params"]:
            cur = e["p"].get(key, dflt)
            if kind == "curve": self._curve_row(v, e, key, info); continue
            row = QHBoxLayout(); row.setSpacing(8); lab = label(label_, True, 12); lab.setFixedWidth(64); lab.setWordWrap(True); row.addWidget(lab)
            if kind in ("float", "int"):
                dec = 0 if kind == "int" or (hi - lo) >= 60 else (2 if (hi - lo) <= 2 else 1)
                sl = Slider(lo, hi, float(cur), float(dflt), dec); nf = NumberField(float(cur), lo, hi, dec, "", "", scrub=max(0.01, (hi - lo) / 300.0), width=62)
                sl.changed.connect(lambda x, eid=eid, key=key, nf=nf: (nf.setValue(x), self._edit(eid, key, int(x) if kind == "int" else x)))
                nf.changed.connect(lambda x, eid=eid, key=key, sl=sl: (sl.setValue(x), self._edit(eid, key, int(x) if kind == "int" else x)))
                row.addWidget(sl, 1); row.addWidget(nf)
                viz = param_viz(e["type"], key, label_, lo, hi)          # the track shows what the slider does (hue colours, fade of opacity ...)
                if viz: sl.setTrack(self._track_of(viz, e["p"])); info.setdefault("viz", []).append((sl, viz))
                def setter(x, sl=sl, nf=nf):
                    if sl._drag or nf._press is not None or nf.ed.isVisible(): return
                    sl.setValue(float(x)); nf.setValue(float(x))
            elif kind == "color":
                btn = ColorButton(cur); btn.changed.connect(lambda col, eid=eid, key=key: self._edit(eid, key, col)); row.addStretch(); row.addWidget(btn)
                btn.changed.connect(lambda col, key=key, info=info: self._color_changed(info, key, col))
                def setter(x, btn=btn, key=key, info=info): btn.set(x); self._color_changed(info, key, x)
            elif kind == "choice":
                combo = Dropdown([(lab_, val_) for val_, lab_ in lo]); combo.setCurrentData(cur); combo.changed.connect(lambda i, eid=eid, key=key, combo=combo: self._edit(eid, key, combo.currentData())); row.addWidget(combo, 1)
                def setter(x, combo=combo): combo.setCurrentData(x)
            else:
                chk = Toggle("", bool(cur)); chk.toggled.connect(lambda on, eid=eid, key=key: self._edit(eid, key, bool(on))); row.addStretch(); row.addWidget(chk)
                def setter(x, chk=chk): chk.setChecked(bool(x))
            v.addLayout(row); info["set"][key] = (setter, dflt)
        if spec["area"]:
            ab = Btn("Choose the area", "vignette", "soft", "Choose the blurred area: a shape, or draw your own with the Custom shape", None, True); ab.setChecked(self._area_id == eid)
            ab.toggled.connect(lambda on, eid=eid: self._edit_area(eid, on)); v.addWidget(ab); info["area_btn"] = ab
        return card
    def _curve_row(self, v, e, key, info):
        eid = e["id"]; ce = CurveEditor(); ce.curves = copy.deepcopy(e["p"].get(key) or DEFAULT_CURVE); ce.setMinimumHeight(190)
        seg = Segmented([("All", "m"), ("R", "r"), ("G", "g"), ("B", "b")], "m"); r = QHBoxLayout(); r.setSpacing(8); r.addWidget(seg, 1)
        rb = Btn("Reset", "reset", "soft", "Straight line again", None, h=28); r.addWidget(rb); v.addLayout(r); v.addWidget(ce)
        seg.changed.connect(lambda ch: (setattr(ce, "ch", ch), ce.update()))
        ce.changed.connect(lambda: self._edit(eid, key, copy.deepcopy(ce.curves)))
        def reset():
            ce.curves[ce.ch] = [[0, 0], [1, 1]]; ce.update(); self._edit(eid, key, copy.deepcopy(ce.curves))
        rb.clicked.connect(reset)
        hint = label("Click = add a point · drag = move · right-click = delete", True, 11); hint.setWordWrap(True); v.addWidget(hint)
        def setter(x, ce=ce):
            if ce.drag is None: ce.curves = copy.deepcopy(x or DEFAULT_CURVE); ce.update()
        info["set"][key] = (setter, DEFAULT_CURVE)
    # ---- inspector hook ----
    def load(self, c, force=False):
        self.loading = True
        try:
            if c is None: self.sig = None; self._clear(); self.empty.setVisible(True); self.area_box.hide(); return
            c.setdefault("effects", [])
            sig = (c["id"], tuple((e["id"], e["type"]) for e in c["effects"]))
            if sig != self.sig:
                if self.sig is None or self.sig[0] != c["id"]: self._area_id = None
                self.sig = sig; self._rebuild(c)
            else:
                for e in c["effects"]:
                    info = self.cards.get(e["id"])
                    if not info: continue
                    info["enable"].setChecked(bool(e.get("on", True)))
                    if "spill" in info: info["spill"].setChecked(bool(e.get("spill", False)))
                    for key, (setter, dflt) in info["set"].items(): setter(e["p"].get(key, dflt))
                if self._area_id: self._show_area(c, force=force)
        finally: self.loading = False

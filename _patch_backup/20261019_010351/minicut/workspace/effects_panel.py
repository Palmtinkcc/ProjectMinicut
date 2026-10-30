"""Effects tab of the inspector: "+ Effect" menu and one card per effect layer (enable, reorder, delete, parameters)."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.theme import *
from ..shared.core import *
from ..shared.widgets import *
from ..render.effects import FX, FX_CATS, new_effect, fx_defaults


def _fmt(v, kind, lo, hi):
    if kind == "int": return str(int(v))
    return ("%.0f" % v) if (hi - lo) >= 60 else ("%.1f" % v).rstrip("0").rstrip(".")


class EffectsPanel(QWidget):
    def __init__(self, app, area_panel):
        super().__init__(); self.app = app; self.area = area_panel; self.sig = None; self.cards = {}; self.loading = False
        self._area_id = None; self._before = None
        self._ct = QTimer(self); self._ct.setSingleShot(True); self._ct.setInterval(450); self._ct.timeout.connect(self._commit)
        self.setStyleSheet("QFrame#FxCard{background:%s; border:1px solid %s; border-radius:8px;}" % (UI["ui_button"], UI["ui_input"]))
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        top = QHBoxLayout(); t = QLabel("Effects"); t.setObjectName("Dim"); top.addWidget(t); top.addStretch()
        self.add_btn = QToolButton(); self.add_btn.setText("+ Effect"); self.add_btn.setToolTip("Add an effect layer"); self.add_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.add_btn)
        for cat in FX_CATS:
            sub = menu.addMenu(cat)
            for typ, sp in FX.items():
                if sp["cat"] == cat: sub.addAction(sp["title"], lambda typ=typ: self.add_effect(typ))
        self.add_btn.setMenu(menu); top.addWidget(self.add_btn); v.addLayout(top)
        self.host = QWidget(); self.lay = QVBoxLayout(self.host); self.lay.setContentsMargins(0, 0, 0, 0); self.lay.setSpacing(8); v.addWidget(self.host)
        self.empty = QLabel("No effects yet.\nPress + Effect to add color, blur, color split, area blur and more.\nEffects are applied from top to bottom."); self.empty.setObjectName("Dim"); self.empty.setWordWrap(True)
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
    def _edit(self, eid, key, val):
        """Live parameter change (one undo step per burst of edits)."""
        if self.loading: return
        c = self.app.sel_clip(); e = self._find(c, eid)
        if e is None: return
        if self._before is None: self._before = self.app.begin()
        e["p"][key] = val; self._ct.start(); self.app.request_render()
    def _structural(self, fn, rebuild=True):
        c = self.app.sel_clip()
        if c is None: return
        self._commit(); self.app.checkpoint(); fn(c); self.app.on_changed(insp=False)
        if rebuild: QTimer.singleShot(0, lambda: self._rebuild(self.app.sel_clip()))
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
            self._clear()
            fx = (c or {}).get("effects", []) if c else []
            self.empty.setVisible(not fx)
            for i, e in enumerate(fx):
                if e.get("type") in FX: self.lay.addWidget(self._card(e, i, len(fx)))
            if self._area_id and not any(e["id"] == self._area_id for e in fx): self._area_id = None
            self._show_area(c, force=True)
        finally: self.loading = False
    def _card(self, e, idx, n):
        spec = FX[e["type"]]; eid = e["id"]; card = QFrame(); card.setObjectName("FxCard"); v = QVBoxLayout(card); v.setContentsMargins(8, 6, 8, 8); v.setSpacing(4)
        info = {"set": {}}; self.cards[eid] = info
        h = QHBoxLayout(); cb = QCheckBox(spec["title"]); cb.setChecked(bool(e.get("on", True))); cb.toggled.connect(lambda on, eid=eid: self._toggle(eid, on)); cb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); cb.setMinimumWidth(40); h.addWidget(cb, 1)
        up = tool("", "Move up (applied earlier)", lambda eid=eid: self._move(eid, -1), icon=svg_icon("angle-up"), isize=14); up.setEnabled(idx > 0)
        dn = tool("", "Move down (applied later)", lambda eid=eid: self._move(eid, 1), icon=svg_icon("angle-down"), isize=14); dn.setEnabled(idx < n - 1)
        rm = tool("", "Remove effect", lambda eid=eid: self._delete(eid), icon=app_icon("delete"), isize=14)
        for b in (up, dn, rm): h.addWidget(b)
        v.addLayout(h); info["enable"] = cb
        g = QGridLayout(); g.setHorizontalSpacing(8); g.setVerticalSpacing(4); r = 0
        for key, label, kind, dflt, lo, hi in spec["params"]:
            cur = e["p"].get(key, dflt)
            if kind == "curve": self._curve_row(v, e, key, info); continue
            lab = QLabel(label); lab.setObjectName("Dim"); lab.setFixedWidth(84); g.addWidget(lab, r, 0)
            if kind in ("float", "int"):
                sl = QSlider(Qt.Horizontal); val = QLabel(""); val.setFixedWidth(40); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                steps = int(hi - lo) if kind == "int" else 1000
                to_s = (lambda x, lo=lo, hi=hi, kind=kind, steps=steps: int(round((x - lo) / (hi - lo) * steps)) if kind == "float" else int(round(x)) - int(lo))
                from_s = (lambda s, lo=lo, hi=hi, kind=kind, steps=steps: (lo + (hi - lo) * s / steps) if kind == "float" else int(lo) + s)
                sl.setRange(0, steps); sl.setValue(max(0, min(steps, to_s(float(cur))))); val.setText(_fmt(float(cur), kind, lo, hi))
                sl.valueChanged.connect(lambda s, eid=eid, key=key, kind=kind, lo=lo, hi=hi, f=from_s, val=val: (val.setText(_fmt(f(s), kind, lo, hi)), self._edit(eid, key, f(s))))
                g.addWidget(sl, r, 1); g.addWidget(val, r, 2)
                def setter(x, sl=sl, val=val, to_s=to_s, kind=kind, lo=lo, hi=hi):
                    if sl.isSliderDown(): return
                    sl.blockSignals(True); sl.setValue(max(sl.minimum(), min(sl.maximum(), to_s(float(x))))); sl.blockSignals(False); val.setText(_fmt(float(x), kind, lo, hi))
            elif kind == "color":
                btn = ColorButton(cur); btn.changed.connect(lambda col, eid=eid, key=key: self._edit(eid, key, col)); g.addWidget(btn, r, 1)
                def setter(x, btn=btn): btn.set(x)
            elif kind == "choice":
                combo = QComboBox()
                for val_, lab_ in lo: combo.addItem(lab_, val_)
                combo.setCurrentIndex(max(0, combo.findData(cur))); combo.currentIndexChanged.connect(lambda i, eid=eid, key=key, combo=combo: self._edit(eid, key, combo.itemData(i)))
                g.addWidget(combo, r, 1, 1, 2)
                def setter(x, combo=combo): combo.blockSignals(True); combo.setCurrentIndex(max(0, combo.findData(x))); combo.blockSignals(False)
            else:
                chk = QCheckBox(); chk.setChecked(bool(cur)); chk.toggled.connect(lambda on, eid=eid, key=key: self._edit(eid, key, bool(on))); g.addWidget(chk, r, 1)
                def setter(x, chk=chk): chk.blockSignals(True); chk.setChecked(bool(x)); chk.blockSignals(False)
            info["set"][key] = (setter, dflt); r += 1
        v.addLayout(g)
        if spec["area"]:
            ab = QPushButton("Edit area…"); ab.setCheckable(True); ab.setChecked(self._area_id == eid); ab.setToolTip("Choose the blurred area: a shape, or draw your own with the Custom shape")
            ab.toggled.connect(lambda on, eid=eid: self._edit_area(eid, on)); v.addWidget(ab); info["area_btn"] = ab
        return card
    def _curve_row(self, v, e, key, info):
        eid = e["id"]; r = QHBoxLayout(); l = QLabel("Curves"); l.setObjectName("Dim"); r.addWidget(l); r.addStretch()
        ch = QComboBox(); [ch.addItem(n, k) for n, k in (("Master", "m"), ("Red", "r"), ("Green", "g"), ("Blue", "b"))]
        rb = QPushButton("Reset"); r.addWidget(ch); r.addWidget(rb); v.addLayout(r)
        ce = CurveEditor(); ce.curves = copy.deepcopy(e["p"].get(key) or DEFAULT_CURVE); ce.setMinimumHeight(180); v.addWidget(ce)
        ch.currentIndexChanged.connect(lambda *_: (setattr(ce, "ch", ch.currentData()), ce.update()))
        ce.changed.connect(lambda: self._edit(eid, key, copy.deepcopy(ce.curves)))
        def reset():
            ce.curves[ce.ch] = [[0, 0], [1, 1]]; ce.update(); self._edit(eid, key, copy.deepcopy(ce.curves))
        rb.clicked.connect(reset)
        hint = QLabel("Click: add point · Drag: move · Right-click: delete"); hint.setObjectName("Dim"); hint.setWordWrap(True); v.addWidget(hint)
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
                    info["enable"].blockSignals(True); info["enable"].setChecked(bool(e.get("on", True))); info["enable"].blockSignals(False)
                    for key, (setter, dflt) in info["set"].items(): setter(e["p"].get(key, dflt))
                if self._area_id: self._show_area(c, force=force)
        finally: self.loading = False

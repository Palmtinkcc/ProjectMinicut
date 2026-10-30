"""Audio effects list in the Audio tab of the inspector: add, switch on/off, remove and set the values."""
from ..shared.deps import *
from ..shared.core import *
from ..render.afx import AFX_FX, afx_defaults


class AudioFxPanel(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self._sig = None; self._before = None
        v = QVBoxLayout(self); v.setContentsMargins(0, 6, 0, 0); v.setSpacing(6)
        head = QHBoxLayout(); lab = QLabel("Audio effects"); lab.setObjectName("H2"); head.addWidget(lab); head.addStretch()
        self.add_box = QComboBox()
        for k, spec in AFX_FX.items(): self.add_box.addItem(spec["title"], k)
        add = QPushButton("+ Add"); add.clicked.connect(self.add_effect)
        head.addWidget(self.add_box); head.addWidget(add); v.addLayout(head)
        self.cards = QVBoxLayout(); self.cards.setSpacing(6); v.addLayout(self.cards)
        self.empty = QLabel("No audio effects yet. Choose one above and press Add."); self.empty.setObjectName("Dim"); v.addWidget(self.empty)
        self._done_t = QTimer(self); self._done_t.setSingleShot(True); self._done_t.setInterval(400); self._done_t.timeout.connect(self._finish)

    def load(self, c, force=False):
        sig = (c["id"] if c else None, json.dumps(c.get("afx", []) if c else [], sort_keys=True))
        if sig == self._sig and not force: return
        self._sig = sig; self._rebuild(c)

    def _rebuild(self, c):
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w: w.deleteLater()
        ch = (c.get("afx") or []) if c else []
        self.empty.setVisible(not ch and c is not None and c.get("kind") in ("video", "audio"))
        for idx, e in enumerate(ch): self.cards.addWidget(self._card(e, idx))

    def _card(self, e, idx):
        spec = AFX_FX.get(e["type"], {"title": e["type"], "params": []})
        box = QFrame(); box.setFrameShape(QFrame.StyledPanel); v = QVBoxLayout(box); v.setContentsMargins(8, 6, 8, 6); v.setSpacing(4)
        top = QHBoxLayout(); on = QCheckBox(spec["title"]); on.setChecked(bool(e.get("on", True)))
        on.toggled.connect(lambda val, idx=idx: self._structural(lambda ch: ch[idx].__setitem__("on", bool(val))))
        rm = QToolButton(); rm.setText("✕"); rm.setToolTip("Remove this effect")
        rm.clicked.connect(lambda *_, idx=idx: self._structural(lambda ch: ch.pop(idx)))
        top.addWidget(on); top.addStretch(); top.addWidget(rm); v.addLayout(top)
        for key, label, lo, hi, dflt, step in spec["params"]:
            r = QHBoxLayout(); l = QLabel(label); l.setMinimumWidth(120); r.addWidget(l)
            sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setSingleStep(step); sp.setDecimals(0 if step >= 1 else 1)
            sp.setValue(float(e.get("p", {}).get(key, dflt)))
            sp.valueChanged.connect(lambda val, idx=idx, key=key: self._edit(idx, key, val))
            r.addWidget(sp, 1); v.addLayout(r)
        return box

    def _chain(self):
        c = self.app.sel_clip()
        return None if c is None else c.setdefault("afx", [])

    def add_effect(self):
        c = self.app.sel_clip()
        if c is None: return
        k = self.add_box.currentData()
        self.app.checkpoint(); c.setdefault("afx", []).append({"id": new_id(), "type": k, "on": True, "p": afx_defaults(k)})
        self.app.on_changed(insp=False); self.load(c, force=True)

    def _structural(self, fn):
        c = self.app.sel_clip()
        if c is None: return
        self.app.checkpoint(); fn(c.setdefault("afx", [])); self.app.on_changed(insp=False); self.load(c, force=True)

    def _edit(self, idx, key, val):
        c = self.app.sel_clip()
        if c is None or idx >= len(c.get("afx") or []): return
        if self._before is None: self._before = self.app.begin()
        c["afx"][idx].setdefault("p", {})[key] = float(val); self._done_t.start()

    def _finish(self):
        if self._before is not None:
            self.app.commit(self._before); self._before = None
        self.app.on_changed(insp=False)

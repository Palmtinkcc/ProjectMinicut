"""Audio effects list in the Audio tab of the inspector: add, switch on/off, remove and set the values."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.ui import *
from ..shared.widgets import tool
from ..render.afx import AFX_FX, afx_defaults


class AudioFxPanel(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self._sig = None; self._before = None
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        head = QHBoxLayout(); lab = label("Sound effects", False, 13); lab.setStyleSheet(lab.styleSheet() + "font-weight:700;"); head.addWidget(lab); head.addStretch()
        self.add_btn = Btn("Add effect", "plus", "accent", "Add a sound effect", self.pick); head.addWidget(self.add_btn); v.addLayout(head)
        self.cards = QVBoxLayout(); self.cards.setSpacing(8); v.addLayout(self.cards)
        self.empty = label("No sound effects yet", True, 12); self.empty.setAlignment(Qt.AlignCenter); self.empty.setMinimumHeight(60); v.addWidget(self.empty)
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

    def pick(self):
        """A list of the effects with a short explanation of each; the chosen one is added."""
        menu = QFrame(self.window(), Qt.Popup | Qt.FramelessWindowHint); menu.setAttribute(Qt.WA_DeleteOnClose); c = pal()
        menu.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:12px;}" % (c["card"], c["line"])); v = QVBoxLayout(menu); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(1)
        for k, spec in AFX_FX.items():
            b = QPushButton(spec["title"]); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("QPushButton{background:transparent;color:%s;border:none;border-radius:7px;text-align:left;padding:8px 14px;font-size:13px;}QPushButton:hover{background:%s;}" % (c["text"], c["field_h"]))
            b.clicked.connect(lambda _=False, k=k, m=menu: (self.add_effect(k), m.close())); v.addWidget(b)
        menu.adjustSize(); g = self.add_btn.mapToGlobal(QPoint(self.add_btn.width() - menu.width(), self.add_btn.height() + 4)); menu.move(g); menu.show()
    def _card(self, e, idx):
        spec = AFX_FX.get(e["type"], {"title": e["type"], "params": []})
        box = QFrame(); box.setObjectName("AfxCard"); box.setStyleSheet("QFrame#AfxCard{background:#202024;border:1px solid #2c2c33;border-radius:12px;}"); v = QVBoxLayout(box); v.setContentsMargins(12, 10, 12, 12); v.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(8); top.addWidget(icon_label("graphic_eq", "#22d3ee", 18)); t = QLabel(spec["title"]); t.setStyleSheet("color:#ececf1;font-weight:700;font-size:13px;background:transparent;border:none;"); top.addWidget(t); top.addStretch()
        on = Toggle("On", bool(e.get("on", True))); on.toggled.connect(lambda val, idx=idx: self._structural(lambda ch: ch[idx].__setitem__("on", bool(val))))
        rm = tool("", "Remove this effect", lambda idx=idx: self._structural(lambda ch: ch.pop(idx)), icon="delete", isize=16); top.addWidget(on); top.addWidget(rm); v.addLayout(top)
        for key, label_, lo, hi, dflt, step in spec["params"]:
            r = QHBoxLayout(); r.setSpacing(8); l = label(label_, True, 12); l.setFixedWidth(92); l.setWordWrap(True); r.addWidget(l); dec = 0 if step >= 1 else 1; cur = float(e.get("p", {}).get(key, dflt))
            sl = Slider(lo, hi, cur, dflt, dec); nf = NumberField(cur, lo, hi, dec, "", "", scrub=max(0.01, (hi - lo) / 300.0), width=62)
            sl.changed.connect(lambda x, idx=idx, key=key, nf=nf: (nf.setValue(x), self._edit(idx, key, x))); nf.changed.connect(lambda x, idx=idx, key=key, sl=sl: (sl.setValue(x), self._edit(idx, key, x)))
            r.addWidget(sl, 1); r.addWidget(nf); v.addLayout(r)
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

"""Sound filter list in the Audio tab of the inspector: add, switch on/off, remove and set the values. Every filter says
what it does and how to use it. The noise filters have an Auto adjust window, and when a filter makes the sound last
longer than the clip (echo, reverb) a button fits the clip to the filtered sound so its end is not cut off."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.ui import *
from ..shared.widgets import tool
from ..render.afx import AFX_FX, AFX_AUTO, afx_defaults, tail_info, active_chain
from .noise_dialog import NoiseDialog


class AudioFxPanel(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self._sig = None; self._before = None; self._tries = 0
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        head = QHBoxLayout(); lab = label("Sound filter", False, 13); lab.setStyleSheet(lab.styleSheet() + "font-weight:700;"); head.addWidget(lab); head.addStretch()
        self.add_btn = Btn("Add filter", "plus", "accent", "Add a sound filter", self.pick); head.addWidget(self.add_btn); v.addLayout(head)
        self.cards = QVBoxLayout(); self.cards.setSpacing(8); v.addLayout(self.cards)
        self.empty = label("No sound filters yet", True, 12); self.empty.setAlignment(Qt.AlignCenter); self.empty.setMinimumHeight(60); v.addWidget(self.empty)
        self.fit_box = QFrame(); self.fit_box.setObjectName("AfxFit"); self.fit_box.setStyleSheet("QFrame#AfxFit{background:#2a2418;border:1px solid #5a4a1c;border-radius:10px;}")
        fb = QVBoxLayout(self.fit_box); fb.setContentsMargins(12, 10, 12, 10); fb.setSpacing(8)
        self.fit_lab = QLabel(""); self.fit_lab.setWordWrap(True); self.fit_lab.setStyleSheet("color:#f1deb0;font-size:12px;background:transparent;border:none;"); fb.addWidget(self.fit_lab)
        self.fit_btn = Btn("Fit length to filter", None, "accent", "Make the clip as long as the filtered sound, so the end of the echo / reverb is not cut", self.fit_length); fb.addWidget(self.fit_btn)
        self.fit_box.hide(); v.addWidget(self.fit_box)
        self._done_t = QTimer(self); self._done_t.setSingleShot(True); self._done_t.setInterval(400); self._done_t.timeout.connect(self._finish)
        self._tail_t = QTimer(self); self._tail_t.setInterval(600); self._tail_t.timeout.connect(self._poll_tail)

    def load(self, c, force=False):
        sig = (c["id"] if c else None, json.dumps(c.get("afx", []) if c else [], sort_keys=True))
        if sig == self._sig and not force: return
        self._sig = sig; self._rebuild(c); self.refresh_tail()

    def _rebuild(self, c):
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w: w.deleteLater()
        ch = (c.get("afx") or []) if c else []
        self.empty.setVisible(not ch and c is not None and c.get("kind") in ("video", "audio"))
        for idx, e in enumerate(ch): self.cards.addWidget(self._card(e, idx))

    def pick(self):
        """A list of the filters with a short explanation of each; the chosen one is added."""
        menu = QFrame(self.window(), Qt.Popup | Qt.FramelessWindowHint); menu.setAttribute(Qt.WA_DeleteOnClose); c = pal()
        menu.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:12px;}" % (c["card"], c["line"])); v = QVBoxLayout(menu); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(1)
        for k, spec in AFX_FX.items():
            first = spec.get("help", "").split(". ")[0].rstrip(".") + "."
            b = QPushButton(spec["title"] + "\n" + first); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setToolTip(spec.get("help", ""))
            b.setStyleSheet("QPushButton{background:transparent;color:%s;border:none;border-radius:7px;text-align:left;padding:7px 14px;font-size:12px;}QPushButton:hover{background:%s;}" % (c["text"], c["field_h"]))
            b.clicked.connect(lambda _=False, k=k, m=menu: (self.add_effect(k), m.close())); v.addWidget(b)
        menu.setFixedWidth(380); menu.adjustSize(); g = self.add_btn.mapToGlobal(QPoint(self.add_btn.width() - menu.width(), self.add_btn.height() + 4)); menu.move(g); menu.show()

    def _card(self, e, idx):
        spec = AFX_FX.get(e["type"], {"title": e["type"], "params": []})
        box = QFrame(); box.setObjectName("AfxCard"); box.setStyleSheet("QFrame#AfxCard{background:#202024;border:1px solid #2c2c33;border-radius:12px;}"); v = QVBoxLayout(box); v.setContentsMargins(12, 10, 12, 12); v.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(8); top.addWidget(icon_label("graphic_eq", "#22d3ee", 18)); t = QLabel(spec["title"]); t.setStyleSheet("color:#ececf1;font-weight:700;font-size:13px;background:transparent;border:none;"); top.addWidget(t); top.addStretch()
        on = Toggle("On", bool(e.get("on", True))); on.toggled.connect(lambda val, idx=idx: self._structural(lambda ch: ch[idx].__setitem__("on", bool(val))))
        rm = tool("", "Remove this filter", lambda idx=idx: self._structural(lambda ch: ch.pop(idx)), icon="delete", isize=16); top.addWidget(on); top.addWidget(rm); v.addLayout(top)
        if spec.get("help"):
            h = QLabel(spec["help"]); h.setWordWrap(True); h.setStyleSheet("color:#8d8d99;font-size:11px;background:transparent;border:none;"); v.addWidget(h)
        if e["type"] in AFX_AUTO:
            ab = Btn("Auto adjust\u2026", None, "soft", "Pick on a graph how loud the noise is: the filter is set for you", lambda idx=idx, typ=e["type"]: self.auto_adjust(idx, typ)); v.addWidget(ab)
        for key, label_, lo, hi, dflt, step in spec["params"]:
            r = QHBoxLayout(); r.setSpacing(8); l = label(label_, True, 12); l.setFixedWidth(92); l.setWordWrap(True); r.addWidget(l); dec = 0 if step >= 1 else 1; cur = float(e.get("p", {}).get(key, dflt))
            sl = Slider(lo, hi, cur, dflt, dec); nf = NumberField(cur, lo, hi, dec, "", "", scrub=max(0.01, (hi - lo) / 300.0), width=62)
            sl.changed.connect(lambda x, idx=idx, key=key, nf=nf: (nf.setValue(x), self._edit(idx, key, x))); nf.changed.connect(lambda x, idx=idx, key=key, sl=sl: (sl.setValue(x), self._edit(idx, key, x)))
            r.addWidget(sl, 1); r.addWidget(nf); v.addLayout(r)
        return box


    def add_effect(self, k):
        c = self.app.sel_clip()
        if c is None: return
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
        self.app.on_changed(insp=False); self.refresh_tail()

    # ---- Auto adjust (noise filters) ----
    def auto_adjust(self, idx, typ):
        c = self.app.sel_clip()
        if c is None or idx >= len(c.get("afx") or []): return
        self.window().setCursor(Qt.WaitCursor)
        try: dlg = NoiseDialog(self.window(), c, typ)
        finally: self.window().unsetCursor()
        if dlg.exec() == QDialog.Accepted and dlg.params:
            self.app.checkpoint(); c["afx"][idx].setdefault("p", {}).update(dlg.params); self.app.on_changed(insp=False); self.load(c, force=True)

    # ---- fit the clip to the filtered sound ----
    def refresh_tail(self):
        self._tries = 0; self.fit_box.hide(); self._tail_t.start(); self._poll_tail()

    def _need(self, c, tail):
        """Where the clip must end to hold the filtered sound."""
        return c["start"] + local_of_src(c, c.get("src_dur", 0) + tail - c["inp"])

    def _poll_tail(self):
        c = self.app.sel_clip(); self._tries += 1
        if c is not None and c.get("kind") == "audio" and not active_chain(c): c["afx_tail"] = 0.0       # no filter: no tail
        if c is None or c.get("kind") != "audio" or not active_chain(c) or self._tries > 120: self.fit_box.hide(); self._tail_t.stop(); return
        tail = tail_info(c)
        if tail is None: return                       # the filtered sound is still being made
        self._tail_t.stop(); c["afx_tail"] = tail
        short = self._need(c, tail) - (c["start"] + c["dur"])
        if tail > 0.05 and short > 0.03:
            self.fit_lab.setText("The filtered sound lasts %.1f s longer than this clip, so its end is cut off." % short); self.fit_box.show()
        else: self.fit_box.hide()

    def fit_length(self):
        c = self.app.sel_clip()
        if c is None or c.get("kind") != "audio": return
        tail = tail_info(c)
        if not tail: return
        self.app.checkpoint(); c["afx_tail"] = tail; c["dur"] = max(c["dur"], self._need(c, tail) - c["start"]); self.app.place_free(c)
        self.app.on_changed(insp=False); self.fit_box.hide()

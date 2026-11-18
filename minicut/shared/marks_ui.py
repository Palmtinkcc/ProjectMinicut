"""Marks UI shared by the main timeline and Bone2D: the Auto mark dialog, the mark context menu and the drawing helpers."""
from .deps import *
from .core import *
from .ui import *
from .widgets import *
from . import marks as MK


# ───────────────────────── drawing ─────────────────────────
def draw_mark_flag(p, x, top, bottom, color, name="", line_to=None, selected=False):
    """A mark on a ruler: a flag with the mark's colour, its name, and (line_to) a thin line down through the lanes."""
    col = QColor(color)
    if line_to is not None and line_to > bottom:
        lc = QColor(col); lc.setAlpha(110); p.setPen(QPen(lc, 1, Qt.DashLine)); p.drawLine(QPointF(x, bottom), QPointF(x, line_to))
    p.setPen(QPen(QColor("#ffffff"), 1.4) if selected else Qt.NoPen); p.setBrush(col); pg = QPainterPath()
    pg.moveTo(x - 5, bottom - 12); pg.lineTo(x + 5, bottom - 12); pg.lineTo(x + 5, bottom - 5); pg.lineTo(x, bottom); pg.lineTo(x - 5, bottom - 5); pg.closeSubpath(); p.drawPath(pg)
    if name: p.setPen(col); p.drawText(QPointF(x + 8, bottom - 5), name)


def draw_beat_ticks(p, grid, t0, t1, t2x, bottom, x_min, x_max, color="#5b6b94"):
    """Thin beat ticks on a ruler (nothing when they would be closer than 5 px)."""
    ts = MK.grid_times(grid, t0, t1)
    if len(ts) < 2 or abs(t2x(ts[1]) - t2x(ts[0])) < 5: return
    c = QColor(color); c.setAlpha(150); p.setPen(QPen(c, 1))
    for t in ts:
        x = t2x(t)
        if x_min <= x <= x_max: p.drawLine(QPointF(x, bottom - 8), QPointF(x, bottom))


def color_icon(hexcol, size=14):
    pm = QPixmap(size, size); pm.fill(Qt.transparent); q = QPainter(pm); q.setRenderHint(QPainter.Antialiasing); q.setPen(Qt.NoPen); q.setBrush(QColor(hexcol)); q.drawEllipse(1, 1, size - 2, size - 2); q.end(); return QIcon(pm)


# ───────────────────────── context menu ─────────────────────────
def build_mark_menu(menu, m, t_click, px_per_sec, hooks):
    """Fill `menu` with the mark actions for the mark set m. hooks: checkpoint(), changed(), add(), rename(t), auto(), grid_toggle(), seek(t), key_all() (optional).
    Both the main timeline and Bone2D call this, so marks behave the same in both."""
    near = min(m.markers, key=lambda v: abs(v - t_click)) if m.markers else None; on = near is not None and abs(near - t_click) * px_per_sec < 10
    menu.addAction("Add / remove mark at the playhead   (M)", hooks["add"])
    menu.addAction("Auto mark from the sound...", hooks["auto"])
    g = m.beat_grid; a = menu.addAction("Lock to beat (new marks and moved marks snap to the beat)"); a.setCheckable(True); a.setChecked(g["on"]); a.triggered.connect(lambda _=False: hooks["grid_toggle"]())
    a = menu.addAction("Show beat lines"); a.setCheckable(True); a.setChecked(g["show"])
    def tg():
        hooks["checkpoint"](); m.beat_grid = dict(m.beat_grid, show=not m.beat_grid["show"]); hooks["changed"]()
    a.triggered.connect(lambda _=False: tg())
    if on:
        menu.addSeparator(); sub = menu.addMenu("Colour of this mark")
        for nm, hx in MK.PALETTE:
            act = sub.addAction(color_icon(hx), nm)
            def setc(_=False, hx=hx, near=near): hooks["checkpoint"](); MK.set_color(m, near, hx); hooks["changed"]()
            act.triggered.connect(setc)
        menu.addAction("Rename this mark...", lambda: hooks["rename"](near)); menu.addAction("Delete this mark", lambda: (hooks["checkpoint"](), MK.remove_mark(m, near), hooks["changed"]()))
    if m.markers:
        menu.addSeparator()
        if hooks.get("key_all"): menu.addAction("Keyframe at every mark", hooks["key_all"])
        menu.addAction("Delete all marks", lambda: (hooks["checkpoint"](), MK.clear_marks(m), hooks["changed"]()))


# ───────────────────────── the Auto mark dialog ─────────────────────────
class AutoMarkDialog(AnimatedDialog):
    """Pick a sound, a kind of hit and how sensitive to be; marks appear coloured by the sound and can lock to the beat.
    sources: [(label, fn)] where fn() -> (samples, sample rate, start time in seconds). After exec() the choices are in .result_found / .result_grid / .replace."""
    def __init__(self, parent, m, sources, fps=30, t_range=None):
        super().__init__(parent, "Auto mark", 480); self.m = m; self.sources = sources; self.fps = fps; self.t_range = t_range; self._cache = {}; self.a = None
        self.result_found = []; self.result_grid = None; self.replace = False; self._busy = False
        def row(txt, w, sec):
            r = QHBoxLayout(); r.setSpacing(8); l = label(txt, True, 12); l.setFixedWidth(112); r.addWidget(l); r.addWidget(w, 1); sec.body.addLayout(r)
        sec = Section("Sound", "sound"); self.src = Dropdown([(s[0], i) for i, s in enumerate(sources)]); self.src.changed.connect(self._source); row("Take sound from", self.src, sec)
        self.mode = Dropdown([(n, v) for n, v in MK.MODES]); self.mode.changed.connect(self._refresh); row("Mark", self.mode, sec)
        self.sens = Slider(0, 100, 55, 55, 0); self.sens.changed.connect(lambda v: self._refresh()); row("Sensitivity", self.sens, sec)
        self.gap = NumberField(0.12, 0.03, 5.0, 2, " s", "", 0.01); self.gap.changed.connect(lambda v: self._refresh()); row("Closest marks", self.gap, sec); self.body.addWidget(sec)
        sec = Section("Beat", "timeline"); self.bpm = NumberField(120.0, 30, 300, 2, " BPM", "", 0.2); self.off = NumberField(0.0, -60, 600, 3, " s", "", 0.01)
        self.div = Dropdown([(n, v) for n, v in MK.DIVS]); self.div.setCurrentIndex(0)
        for w in (self.bpm, self.off): w.changed.connect(lambda v: self._refresh())
        self.div.changed.connect(self._refresh); row("Tempo", self.bpm, sec); row("First beat at", self.off, sec); row("Marks per beat", self.div, sec)
        self.lock = Toggle("Lock to beat: marks snap to the beat (and new marks too)", False, "Every mark lands exactly on a beat line. Also keeps 'Lock to beat' on afterwards."); self.lock.toggled.connect(lambda v: self._refresh()); sec.body.addWidget(self.lock)
        self.tempo_lbl = label("", True, 11); sec.body.addWidget(self.tempo_lbl); self.body.addWidget(sec)
        sec = Section("Colour", "tune"); self.by_sound = Toggle("Colour by the sound (bass = red, voice = green, high = blue; loud = vivid)", True); self.by_sound.toggled.connect(lambda v: self._refresh()); sec.body.addWidget(self.by_sound)
        self.fixed = Dropdown([(n, v) for n, v in MK.PALETTE]); self.fixed.changed.connect(self._refresh); row("Single colour", self.fixed, sec); self.body.addWidget(sec)
        self.replace_tg = Toggle("Replace the marks that are already there", False); self.body.addWidget(self.replace_tg)
        self.info = label("", True, 12); self.body.addWidget(self.info)
        r = QHBoxLayout(); r.addStretch(); c = QPushButton("Cancel"); c.clicked.connect(self.reject); self.ok = QPushButton("Add marks"); self.ok.setObjectName("Accent"); self.ok.clicked.connect(self._accept); r.addWidget(c); r.addWidget(self.ok); self.body.addLayout(r)
        g = m.beat_grid; self.lock.on = bool(g["on"]); self.lock.update(); self.bpm.setValue(g["bpm"]); self.off.setValue(g["offset"]); self.div.setCurrentIndex(max(0, self.div.findData(float(g["div"]))))
        QTimer.singleShot(30, self._source)
    # -- analysis
    def _source(self, *_):
        i = self.src.currentData() if self.src.count() else 0
        if i is None or i < 0 or i >= len(self.sources): return
        if i not in self._cache:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                snd, sr, t0 = self.sources[i][1](); self._cache[i] = MK.analyze(snd, sr, t0) if snd is not None and len(snd) > 2048 else None
            except Exception as ex:
                print("auto mark:", ex); self._cache[i] = None
            finally: QApplication.restoreOverrideCursor()
        self.a = self._cache[i]
        if self.a is not None and self.a.tempo:                                  # the detected tempo fills the beat fields unless the project already has a locked grid
            bpm, off, conf = self.a.tempo
            if not self.m.beat_grid["on"]: self._busy = True; self.bpm.setValue(bpm); self.off.setValue(off); self._busy = False
            self.tempo_lbl.setText("Detected tempo: %.1f BPM · first beat %.2f s · confidence %d%%   (change the numbers above to fix it)" % (bpm, off, conf * 100))
        else: self.tempo_lbl.setText("No sound found here: pick another source.")
        self._refresh()
    def _grid(self): return {"on": bool(self.lock.on), "show": True, "bpm": float(self.bpm.value()), "offset": float(self.off.value()), "div": float(self.div.currentData() or 1.0)}
    def _found(self):
        if self.a is None: return []
        g = self._grid(); lo, hi = (self.t_range if self.t_range else (None, None))
        return MK.find_marks(self.a, self.mode.currentData(), self.sens.value(), self.gap.value(), lock=g["on"], grid=g, div=g["div"], by_sound=self.by_sound.on, fixed_color=self.fixed.currentData() or MK.MARK_DEFAULT, t_from=lo, t_to=hi)
    def _refresh(self, *_):
        if self._busy: return
        f = self._found(); self._found_now = f; self.ok.setEnabled(bool(f))
        self.info.setText("%d marks will be added." % len(f) if f else "Nothing to mark: raise the sensitivity or pick another sound.")
        self.fixed.setEnabled(not self.by_sound.on)
    def _accept(self):
        self.result_found = list(getattr(self, "_found_now", [])); self.result_grid = self._grid(); self.replace = bool(self.replace_tg.on); self.accept()

"""Settings window (Patch 37): side list (Graphic / Storage / Export / Theme), search, hardware cards, 'Optimize for me'."""
from .deps import *
from .theme import *
from .core import *
from .appearance import *
from .widgets import *
from .hwaccel import *
from .ui import *
from .settings_widgets import *
from . import sysinfo
from .optimize import EXPORT_PRESETS, EXPORT_SPACE, X264_PRESET, export_crf, recommend
QSpinBox = SpinBox; QDoubleSpinBox = DoubleSpinBox; QComboBox = ComboBox; QCheckBox = CheckBox

PG_GRAPHIC, PG_STORAGE, PG_EXPORT, PG_THEME = 0, 1, 2, 3

# Theme presets: only the colours that differ from the default (the default is THEME_DEFS itself).
THEME_PRESETS = OrderedDict([
    ("Default (cyan)", {}),
    ("Midnight blue", {"ui_window": "#070b14", "ui_panel": "#0d1424", "ui_button": "#16213a", "ui_input": "#111a2e", "tl_bg": "#0a0f1c", "vp_bg": "#05080f"}),
    ("Graphite", {"ui_window": "#151515", "ui_panel": "#232323", "ui_button": "#303030", "ui_input": "#2b2b2b", "tl_bg": "#1a1a1a", "tl_lane_video": "#222222",
                  "tl_lane_audio": "#202020", "tl_header_bg": "#2a2a2a", "tl_ruler_bg": "#1d1d1d", "vp_bg": "#0b0b0b", "ui_text_dim": "#a8a8a8"}),
    ("Violet", {"ui_accent": "#a78bfa", "ui_accent2": "#7c3aed", "tl_playhead_head": "#7c3aed", "marquee": "#7c3aed", "vp_handle": "#7c3aed"}),
])


class SettingsDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "Setting", 900); s = app.settings; self.app = app; self._snap = dict(UI); self._applied = False
        self._rows = []; self._cards = []; self._extra = {}; self._rec = None; self._sync = False; self.card.setMinimumHeight(580)

        self.hw = sysinfo.Hardware(); self.hw.start()
        self.search = TextField("", "Search"); self.search.textChanged.connect(self._filter); self.body.addWidget(self.search)
        main = QHBoxLayout(); main.setSpacing(6)
        self.nav = SideNav(["Graphic", "Storage", "Export", "Theme"], gap_before=(3,)); main.addWidget(self.nav)
        line = QFrame(); line.setFixedWidth(2); line.setStyleSheet("background:rgba(255,255,255,70);border:none;"); main.addWidget(line)
        self.stack = QStackedWidget(); main.addWidget(self.stack, 1); self.body.addLayout(main, 1)
        self._pages = []
        for _ in range(4):
            sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
            host = QWidget(); host.setObjectName("SPG"); host.setStyleSheet("QWidget#SPG{background:transparent;}")
            vl = QVBoxLayout(host); vl.setContentsMargins(8, 4, 6, 6); vl.setSpacing(10); sc.setWidget(host); self.stack.addWidget(sc); self._pages.append(vl)
        self.nav.changed.connect(self._page)

        self._build_widgets(s)
        self._build_graphic(s); self._build_storage(s); self._build_export(s); self._build_theme(s)
        for vl in self._pages: vl.addStretch(1)

        row_btns = QHBoxLayout()
        self.reset_btn = QPushButton("Reset appearance"); self.reset_btn.setToolTip("Restore all sizes and colors to defaults"); self.reset_btn.clicked.connect(self.reset_theme)
        row_btns.addWidget(self.reset_btn); row_btns.addStretch()
        a = QPushButton("Apply"); a.clicked.connect(self.apply_theme)
        c_btn = QPushButton("Cancel"); c_btn.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)
        for b in (a, c_btn, ok): row_btns.addWidget(b)
        self.body.addLayout(row_btns); self.reset_btn.setVisible(False)
        self._timer = QTimer(self); self._timer.setInterval(1000); self._timer.timeout.connect(self._tick); self._timer.start(); self._tick()

    # ───────────────────────── helpers ─────────────────────────
    def sec(self, page, title, icon=None):
        card = Section(title, icon); frm = QFormLayout(); frm.setSpacing(6); frm.setLabelAlignment(Qt.AlignLeft); card.body.addLayout(frm)
        self._pages[page].addWidget(card); self._cards.append((page, card, title.lower())); return card, frm
    def row(self, page, card, frm, label, widget, tip=""):
        frm.addRow(label, widget); t = widget.text if isinstance(getattr(widget, "text", None), str) else ""
        self._rows.append((page, card, frm, widget, (label + " " + t + " " + tip).lower()))
    def _page(self, i):
        self.stack.setCurrentIndex(i); self.reset_btn.setVisible(i == PG_THEME)
        if i == PG_STORAGE: self.refresh_storage()
    def _filter(self, q):
        q = (q or "").strip().lower(); shown = {}
        for page, card, frm, w, text in self._rows:
            vis = (not q) or q in text
            try: frm.setRowVisible(w, vis)
            except Exception: w.setVisible(vis)
            if vis: shown[card] = True
        has = [False] * 4
        for page, card, title in self._cards:
            fixed = card not in {r[1] for r in self._rows}
            vis = (not q) or bool(shown.get(card)) or q in title or (fixed and not q)
            card.setVisible(vis); has[page] = has[page] or vis
        for i in range(4): self.nav.dim(i, bool(q) and not has[i])
        if q and not has[self.stack.currentIndex()]:
            i = next((k for k in range(4) if has[k]), None)
            if i is not None: self.nav.select(i, True)

    # ───────────────────────── widgets (the controls themselves, placed by the _build_* methods) ─────────────────────────
    def _build_widgets(self, s):
        self.asset = PathEdit(s["asset_folder"]); self.projf = PathEdit(s["project_folder"]); self.expf = PathEdit(s["export_folder"])
        self.q = QComboBox(); [self.q.addItem(l, v) for l, v in QUALITIES]; self.q.setCurrentIndex(max(0, self.q.findData(s["preview_quality"])))
        self.interp = QComboBox(); self.interp.addItems(["Smooth (bilinear)", "Fast (nearest)"]); self.interp.setCurrentIndex(1 if s["preview_interp"] == "fast" else 0)
        self.fps = QComboBox(); [self.fps.addItem("%d fps" % v, v) for v in (24, 30, 60)]; self.fps.setCurrentIndex(max(0, self.fps.findData(int(s["preview_fps"]))))
        self.cache = QSpinBox(); self.cache.setRange(4, 600); self.cache.setValue(s["frame_cache"]); self.cache.setSuffix(" frames / video")
        self.wave_gain = QDoubleSpinBox(); self.wave_gain.setRange(1.0, 8.0); self.wave_gain.setSingleStep(0.5); self.wave_gain.setDecimals(1); self.wave_gain.setSuffix(" ×"); self.wave_gain.setValue(float(s["waveform_gain"]))
        self.reduce = QCheckBox("Halve resolution while playing"); self.reduce.setChecked(s["play_reduce"])
        self.fit_cb = QCheckBox("Draw at display size (saves GPU)"); self.fit_cb.setChecked(bool(s["fit_viewport"]))
        self.adapt = QCheckBox("Auto-lower detail when slow"); self.adapt.setChecked(bool(s["adaptive_preview"]))
        self.hwdec = QCheckBox("GPU video decode (each file is checked against the CPU decoder; falls back to CPU)"); self.hwdec.setChecked(bool(s["hw_decode"]))
        self.showfps = QCheckBox("Show Frame build Preview"); self.showfps.setChecked(bool(s["show_fps"]))
        self.showfps.setToolTip("Shows the FPS and how many milliseconds each frame takes to build, in the top-left corner of the preview.")
        self.bake_cb = QCheckBox("Adaptive proxy: bake heavy segments in the background (experimental)"); self.bake_cb.setChecked(bool(s["bake"]))
        self.bake_cb.setToolTip("When you stop editing, the heavy parts of the timeline (ALL layers combined, with their effects) are rendered once into small files and played from them.")
        self.fxadapt = QCheckBox("Slow effects use fewer pixels while playing (full quality when stopped)"); self.fxadapt.setChecked(bool(s["fx_adapt"]))
        self.fxadapt.setToolTip("Keeps the preview smooth when an effect is heavy. Export is never reduced. Switch off to always see effects in full while playing.")
        self.bake_gb = QComboBox()
        for g_ in (1, 2, 4, 8, 16): self.bake_gb.addItem("Baked proxy cache: up to %d GB" % g_, g_)
        self.bake_gb.setCurrentIndex(max(0, self.bake_gb.findData(int(s["bake_max_gb"]))))
        self.enc = QComboBox(); [self.enc.addItem(l, v) for l, v in ENCODE_CHOICES]; self.enc.setCurrentIndex(max(0, self.enc.findData(s["encode_hw"])))
        self.thr_box = QComboBox(); self.thr_box.addItem("Auto (leave 2 free)", 0)
        for n in (1, 2, 3, 4, 6, 8): self.thr_box.addItem(str(n), n)
        self.thr_box.setCurrentIndex(max(0, self.thr_box.findData(int(s["render_threads"]))))
        self.ram_box = QComboBox()
        for mb in (128, 256, 512, 1024, 2048): self.ram_box.addItem("%d MB" % mb, mb)
        self.ram_box.setCurrentIndex(max(0, self.ram_box.findData(int(s["preview_ram_mb"]))))
        self.prio_cb = QCheckBox("Keep render thread below window priority"); self.prio_cb.setChecked(bool(s["low_priority"]))
        self.proxy_cb = QCheckBox("Enable proxy (background down-scaled copies)"); self.proxy_cb.setChecked(bool(s["proxy_preview"]))
        self.p_h = QComboBox(); [self.p_h.addItem("%dp" % v, v) for v in (360, 540, 720)]; self.p_h.setCurrentIndex(max(0, self.p_h.findData(int(s["proxy_height"]))))
        self.p_q = QComboBox(); [self.p_q.addItem(l, v) for l, v in (("High quality", 18), ("Normal", 23), ("Small files", 28))]; self.p_q.setCurrentIndex(max(0, self.p_q.findData(int(s["proxy_quality"]))))
        self.p_budget = QSpinBox(); self.p_budget.setRange(25, 50); self.p_budget.setSuffix(" GB"); self.p_budget.setValue(int(s["proxy_budget_gb"]))
        self.phw_box = QComboBox()
        for lab, val in (("Auto (GPU when available)", "auto"), ("CPU only", "cpu")): self.phw_box.addItem(lab, val)
        self.phw_box.setCurrentIndex(max(0, self.phw_box.findData(s["proxy_hw"])))
        self.audio_gb = QSpinBox(); self.audio_gb.setRange(1, 50); self.audio_gb.setSuffix(" GB"); self.audio_gb.setValue(int(s["audio_cache_gb"]))
        from ..render.recorder import list_audio_inputs
        self.mic = QComboBox(); self.mic.addItem("System default", "")
        for _n, _id in list_audio_inputs(): self.mic.addItem(_n, _id)
        _cur = s["audio_input"]; _ix = self.mic.findData(_cur)
        if _ix < 0 and _cur: self.mic.addItem("Unplugged microphone (will use the default)", _cur); _ix = self.mic.count() - 1
        self.mic.setCurrentIndex(max(0, _ix))
        self.autosave = QCheckBox("Save the project automatically"); self.autosave.setChecked(bool(s["autosave"]))
        self.autosave_min = QSpinBox(); self.autosave_min.setRange(1, 60); self.autosave_min.setSuffix(" min"); self.autosave_min.setValue(int(s["autosave_min"]))
        # Export page
        self.mt = QCheckBox("multi thread rendering"); self.mt.setChecked(int(s["render_threads"]) != 1)
        self.mt.setToolTip("Off = one render thread. On = Auto (or the number chosen under Graphic > Render threads).")
        self.mt.toggled.connect(self._mt_changed); self.thr_box.currentIndexChanged.connect(self._thr_changed)
        self.preset_list = OptionList([l for _k, l in EXPORT_PRESETS]); self.space_list = OptionList([l for l, _c in EXPORT_SPACE])
        keys = [k for k, _l in EXPORT_PRESETS]; self.preset_list.set(keys.index(s["export_preset"]) if s["export_preset"] in keys else 2)
        self.space_list.set(int(s["export_space"])); self.preset_list.changed.connect(self._export_hint); self.space_list.changed.connect(self._export_hint)
        self.exp_hint = QLabel(""); self.exp_hint.setObjectName("Dim"); self.exp_hint.setWordWrap(True)
        self.enc_lbl = QLabel("Not checked yet."); self.enc_lbl.setObjectName("Dim"); self.enc_lbl.setWordWrap(True)
        self.gpu_lbl = QLabel("Not checked yet."); self.gpu_lbl.setObjectName("Dim"); self.gpu_lbl.setWordWrap(True)
        try:
            from ..render.gpu import GPU
            self.gpu_lbl.setText(GPU.status)
        except Exception: pass
        # API
        self.api_box = QComboBox(); self.api_box.addItem("OpenGL (GPU)", "gl"); self.api_box.addItem("CPU only", "cpu"); self.api_box.setCurrentIndex(1 if s["gpu_compose"] == "off" else 0)
        self.force_cb = QCheckBox("Force API use"); self.force_cb.setChecked(s["gpu_compose"] == "on")
        self.force_cb.setToolTip("Always use the chosen API, even when its self-test failed before.")
        self._export_hint()

    def _mt_changed(self, on):
        if self._sync: return
        self._sync = True
        try:
            if not on: self.thr_box.setCurrentIndex(max(0, self.thr_box.findData(1)))
            elif self.thr_box.currentData() == 1: self.thr_box.setCurrentIndex(0)
        finally: self._sync = False
    def _thr_changed(self, *_):
        if self._sync: return
        self._sync = True
        try: self.mt.setChecked(self.thr_box.currentData() != 1)
        finally: self._sync = False
    def _export_hint(self, *_):
        key = EXPORT_PRESETS[self.preset_list.index()][0]; sp = EXPORT_SPACE[self.space_list.index()]
        self.exp_hint.setText("Encoder speed: %s \u00b7 file size: %s (CRF %d). Used as the default of the Export window." % (X264_PRESET[key], sp[0], sp[1]))
    def api_mode(self): return "off" if self.api_box.currentData() == "cpu" else ("on" if self.force_cb.isChecked() else "auto")

    # ───────────────────────── pages ─────────────────────────
    def _build_graphic(self, s):
        P = PG_GRAPHIC; vl = self._pages[P]
        top = QWidget(); th = QHBoxLayout(top); th.setContentsMargins(0, 0, 0, 0); th.setSpacing(10)
        self.gpu_card = HwCard("gpu", "Reading ..."); self.cpu_card = HwCard("cpu", "Reading ..."); th.addWidget(self.gpu_card, 1); th.addWidget(self.cpu_card, 1); vl.addWidget(top)
        c, f = self.sec(P, "Rendering API", "effects")
        self.row(P, c, f, "API", self.api_box); self.row(P, c, f, "", self.force_cb)
        tb = QPushButton("Test API compatibility"); tb.clicked.connect(self.test_gpu); ub = QPushButton("Use this API"); ub.setObjectName("Accent"); ub.clicked.connect(self.use_api)
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.addWidget(tb); h.addStretch(1); h.addWidget(ub); self.row(P, c, f, "", w, "test api compatibility use this api")
        self.row(P, c, f, "Status", self.gpu_lbl)
        c, f = self.sec(P, "Optimize for this computer", "adjust")
        self.sum_lbl = QLabel(""); self.sum_lbl.setStyleSheet("background:#242424;border-radius:10px;padding:10px;color:#e6e6e6;"); self.sum_lbl.setTextFormat(Qt.RichText); c.body.addWidget(self.sum_lbl)
        self._show_summary(self._current_lines(), "Current settings")
        self.opt_note = QLabel(""); self.opt_note.setObjectName("Dim"); self.opt_note.setWordWrap(True); c.body.addWidget(self.opt_note)
        ob = QPushButton("Optimize for me"); ob.clicked.connect(self.optimize); self.use_btn = QPushButton("Use this Setting"); self.use_btn.setObjectName("Accent"); self.use_btn.setEnabled(False); self.use_btn.clicked.connect(self.use_recommended)
        h = QHBoxLayout(); h.addWidget(ob); h.addStretch(1); h.addWidget(self.use_btn); c.body.addLayout(h)
        c, f = self.sec(P, "Viewport & Preview", "image")
        for lab, wd in (("Quality", self.q), ("Filter", self.interp), ("Preview FPS", self.fps), ("Frame cache", self.cache), ("Waveform height", self.wave_gain), ("", self.reduce), ("", self.fit_cb), ("", self.adapt)): self.row(P, c, f, lab, wd)
        c, f = self.sec(P, "GPU & Rendering", "effects")
        bake_clear = QPushButton("Clear baked proxies"); bake_clear.clicked.connect(self.clear_bake)
        for lab, wd in (("", self.hwdec), ("", self.bake_cb), ("", self.bake_gb), ("", bake_clear), ("", self.fxadapt), ("Render threads", self.thr_box), ("RAM cache", self.ram_box), ("", self.prio_cb)): self.row(P, c, f, lab, wd)
        c, f = self.sec(P, "Recording", "mic"); self.row(P, c, f, "Microphone", self.mic)

    def _build_storage(self, s):
        P = PG_STORAGE; vl = self._pages[P]
        c, f = self.sec(P, "Storage information", "folder"); c.body.removeItem(f)
        top = QHBoxLayout(); top.setSpacing(14); self.disk_ring = Ring(86, "#ff3b30", 10); top.addWidget(self.disk_ring)
        self.disk_lbl = QLabel(""); self.disk_lbl.setWordWrap(True); top.addWidget(self.disk_lbl, 1); c.body.addLayout(top)
        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setColumnStretch(0, 1); self._stor = []
        from ..render import bake as _bk
        try: bake_dir = _bk._cache_root()
        except Exception: bake_dir = os.path.join(APP_DIR, "bake")
        items = (("Proxy cache", os.path.join(APP_DIR, "proxies"), self.clear_proxies), ("Baked proxies", bake_dir, self.clear_bake),
                 ("Extracted audio", os.path.join(APP_DIR, "extracted_audio"), self.clear_extracted))
        for i, (name, path, fn) in enumerate(items):
            n = QLabel(name); sz = QLabel("..."); sz.setObjectName("Dim"); b = QPushButton("Delete"); b.clicked.connect(lambda _=False, fn=fn: self._confirm_delete(fn))
            grid.addWidget(n, i, 0); grid.addWidget(sz, i, 1); grid.addWidget(b, i, 2); self._stor.append((path, sz))
            for wd in (n, sz, b): self._rows.append((P, c, grid, wd, name.lower() + " delete"))
        c.body.addLayout(grid)
        c, f = self.sec(P, "Proxy (smooth preview)", "video")
        self.p_size = QLabel(""); self.p_size.setObjectName("Dim")
        for lab, wd in (("", self.proxy_cb), ("Proxy size", self.p_h), ("Proxy quality", self.p_q), ("Disk budget", self.p_budget), ("Cache used", self.p_size), ("Proxy encoder", self.phw_box), ("Audio cache", self.audio_gb)): self.row(P, c, f, lab, wd)
        c, f = self.sec(P, "Folders", "folder")
        for lab, wd in (("Assets", self.asset), ("Projects", self.projf), ("Export", self.expf)): self.row(P, c, f, lab, wd)
        c, f = self.sec(P, "Auto save", "save"); self.row(P, c, f, "", self.autosave); self.row(P, c, f, "Every", self.autosave_min)
        self.refresh_storage()

    def _build_export(self, s):
        P = PG_EXPORT; vl = self._pages[P]
        c, f = self.sec(P, "Export", "export"); c.body.removeItem(f)
        two = QHBoxLayout(); two.setSpacing(16)
        l = QVBoxLayout(); lt = QLabel("Preset"); lt.setStyleSheet("font-weight:700;"); l.addWidget(lt); l.addWidget(self.preset_list); l.addStretch(1)
        r = QVBoxLayout(); rt = QLabel("Storage"); rt.setStyleSheet("font-weight:700;"); r.addWidget(rt); r.addWidget(self.space_list); r.addStretch(1)
        two.addLayout(l, 3); two.addLayout(r, 2); c.body.addLayout(two); c.body.addWidget(self.exp_hint)
        self._rows.append((P, c, None, self.preset_list, "preset quality balance fast ultra fast just don't waste my time full space space save storage 80% 50% 40%"))
        c, f = self.sec(P, "Rendering", "effects")
        self.row(P, c, f, "", self.showfps); self.row(P, c, f, "", self.mt)
        gb = QPushButton("Check GPU encoders"); gb.clicked.connect(self.check_gpu)
        self.row(P, c, f, "Export encoder", self.enc); self.row(P, c, f, "", gb); self.row(P, c, f, "GPU encoders", self.enc_lbl)

    def _build_theme(self, s):
        P = PG_THEME; vl = self._pages[P]
        c, f = self.sec(P, "Colors", "adjust"); c.body.removeItem(f)
        self.th_w = {}
        self.map = ThemeMap(); self.map.picked.connect(self._map_pick); c.body.addWidget(self.map)
        h = QHBoxLayout(); self.pick_lbl = QLabel("Timeline"); h.addWidget(self.pick_lbl); h.addStretch(1); self.pick_btn = ColorButton(UI["tl_bg"]); self.pick_btn.changed.connect(self._map_color); h.addWidget(self.pick_btn); c.body.addLayout(h)
        self.preset_box = QComboBox(); [self.preset_box.addItem(k, k) for k in THEME_PRESETS]
        self.preset_box.setCurrentIndex(0); h2 = QHBoxLayout(); h2.addWidget(QLabel("Theme preset")); h2.addStretch(1); h2.addWidget(self.preset_box); c.body.addLayout(h2)
        self.preset_box.currentIndexChanged.connect(self._preset_changed); self._rows.append((P, c, None, self.preset_box, "theme preset"))
        grp = None; card = None; frm = None
        for k, (g, lab, kind, dflt, lo, hi) in THEME_DEFS.items():
            if g != grp: grp = g; card, frm = self.sec(P, g)
            if kind == "int": w = QSpinBox(); w.setRange(lo, hi)
            elif kind == "float": w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(1); w.setSingleStep(0.5)
            elif kind == "bool": w = QCheckBox()
            else: w = ColorButton(UI[k]); w.changed.connect(lambda _c, _k=k: self._color_changed(_k))
            self.th_w[k] = w; self._set(k, UI[k]); self.row(P, card, frm, lab, w)
        self.map.color_of = lambda k: self.th_w[k].c if k in self.th_w else UI[k]; self.map.update()
    def _map_pick(self, key):
        self.pick_lbl.setText(THEME_DEFS[key][1] + "  (" + {"ui_window": "Background", "ui_panel": "Pool", "vp_bg": "Viewport", "ui_input": "Properties", "tl_bg": "Timeline"}.get(key, "") + ")")
        self.pick_btn.set(self.th_w[key].c)
    def _map_color(self, c):
        key = self.map.cur
        if key in self.th_w: self.th_w[key].set(c); self.map.update()
    def _color_changed(self, key):
        self.map.update()
        if key == self.map.cur: self.pick_btn.set(self.th_w[key].c)
    def _preset_changed(self, _i=None):
        name = self.preset_box.currentData(); ch = THEME_PRESETS.get(name, {})
        for k, v in THEME_DEFS.items():
            if v[2] == "color": self._set(k, ch.get(k, v[3]))
        self.map.update(); self.pick_btn.set(self.th_w[self.map.cur].c); self.apply_theme()

    # ───────────────────────── live info ─────────────────────────
    def _tick(self):
        h = self.hw
        if h.ready:
            self.gpu_card.set(h.gpu_short, ("%s" % ("Discrete" if sysinfo.is_discrete(h.gpu) else "Integrated")) if h.gpu else "", h.gpu_load)
            self.cpu_card.set(h.cpu_short, "%d threads \u00b7 %s RAM" % (h.cores, ("%.0f GB" % h.ram) if h.ram else "? GB"), h.cpu_load)
    def refresh_storage(self):
        for path, lbl in self._stor: lbl.setText(sysinfo.fmt_bytes(sysinfo.dir_size(path)))
        d = sysinfo.disk(APP_DIR); mine = sum(sysinfo.dir_size(p) for p, _l in self._stor)
        if d: self.disk_ring.set(100.0 * d[0] / max(1, d[1])); self.disk_lbl.setText("<b>Storage information</b><br>Drive: %s used of %s<br>MiniCut caches: %s" % (sysinfo.fmt_bytes(d[0]), sysinfo.fmt_bytes(d[1]), sysinfo.fmt_bytes(mine)))
        else: self.disk_ring.set(None); self.disk_lbl.setText("<b>Storage information</b><br>MiniCut caches: %s" % sysinfo.fmt_bytes(mine))
        self.refresh_proxy_size()
    def _confirm_delete(self, fn):
        if QMessageBox.question(self, "Delete", "Delete these files? They are copies that MiniCut can build again (extracted audio is only used by clips that point to it).", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            fn(); self.refresh_storage()

    # ───────────────────────── Optimize for me ─────────────────────────
    def _show_summary(self, lines, title):
        rows = "".join("<tr><td style='color:#9a9aa2;padding-right:14px'>%s</td><td><b>%s</b></td></tr>" % (a, b) for a, b in lines)
        self.sum_lbl.setText("<div style='color:#9a9aa2;margin-bottom:4px'>%s</div><table>%s</table>" % (title, rows))
    def _current_lines(self):
        s = self.app.settings
        return [("API", "CPU" if self.api_mode() == "off" else "OpenGL"), ("Quality", "%d" % round(float(self.q.currentData()) * 100)),
                ("Export", "%s \u00b7 CRF %d" % (EXPORT_PRESETS[self.preset_list.index()][1], export_crf(self.space_list.index()))),
                ("Proxy", ("on \u00b7 %dp" % self.p_h.currentData()) if self.proxy_cb.isChecked() else "off"), ("Adaptive Proxy", "on" if self.bake_cb.isChecked() else "off")]
    def optimize(self):
        from ..render.gpu import GPU
        if not self.hw.ready: self.opt_note.setText("Still reading the hardware ... try again in a moment."); return
        try: hz = QApplication.primaryScreen().refreshRate()
        except Exception: hz = 60
        d = sysinfo.disk(APP_DIR); free = ((d[1] - d[0]) / 1073741824.0) if d else None
        vals, lines = recommend(self.hw, hz, GPU.status, free); self._rec = vals
        self._show_summary(lines, "Recommended for %s \u00b7 %s" % (self.hw.gpu_short, self.hw.cpu_short))
        self.opt_note.setText("Nothing is changed yet. Press \u201cUse this Setting\u201d to put these values in this window, then Save."); self.use_btn.setEnabled(True)
    def use_recommended(self):
        v = self._rec
        if not v: return
        def pick(box, val):
            i = box.findData(val)
            if i >= 0: box.setCurrentIndex(i)
        api = v["gpu_compose"]; self.api_box.setCurrentIndex(1 if api == "off" else 0); self.force_cb.setChecked(api == "on")
        pick(self.q, v["preview_quality"]); pick(self.fps, v["preview_fps"]); self.cache.setValue(v["frame_cache"]); pick(self.ram_box, v["preview_ram_mb"]); pick(self.thr_box, v["render_threads"])
        self.proxy_cb.setChecked(v["proxy_preview"]); pick(self.p_h, v["proxy_height"]); pick(self.p_q, v["proxy_quality"]); self.reduce.setChecked(v["play_reduce"]); self.bake_cb.setChecked(v["bake"])
        self.adapt.setChecked(v["adaptive_preview"]); self.fxadapt.setChecked(v["fx_adapt"]); self.fit_cb.setChecked(v["fit_viewport"]); self.prio_cb.setChecked(v["low_priority"])
        self.hwdec.setChecked(v["hw_decode"]); pick(self.enc, v["encode_hw"])
        if "proxy_budget_gb" in v: self.p_budget.setValue(v["proxy_budget_gb"])
        keys = [k for k, _l in EXPORT_PRESETS]; self.preset_list.set(keys.index(v["export_preset"])); self.space_list.set(v["export_space"]); self._export_hint()
        self._extra["export_parallel"] = v["export_parallel"]
        self._show_summary(self._current_lines(), "Applied in this window"); self.opt_note.setText("Applied. Press Save to keep it."); self.use_btn.setEnabled(False)

    # ───────────────────────── actions (same as before) ─────────────────────────
    def _set(self, k, v):
        w = self.th_w[k]; kind = THEME_DEFS[k][2]
        if kind in ("int", "float"): w.setValue(v)
        elif kind == "bool": w.setChecked(bool(v))
        else: w.set(v)
    def _collect(self):
        for k, w in self.th_w.items():
            kind = THEME_DEFS[k][2]
            UI[k] = (w.value() if kind in ("int", "float") else w.isChecked() if kind == "bool" else w.c)
    def reset_theme(self):
        for k, v in THEME_DEFS.items(): self._set(k, v[3])
        self.map.update()
    def apply_theme(self):
        self._collect()
        try:
            from ..render.nodegraph import refresh_node_cats; refresh_node_cats()
        except Exception: pass
        apply_ui(self.app); self._applied = True
    def done(self, r):
        try: self.hw.stop(); self._timer.stop()
        except Exception: pass
        super().done(r)
    def reject(self):
        if self._applied: UI.update(self._snap); apply_ui(self.app)
        super().reject()
    def refresh_proxy_size(self):
        d = os.path.join(APP_DIR, "proxies"); total = 0; n = 0
        if os.path.isdir(d):
            for root_, dirs, files in os.walk(d):
                for f in files:
                    try: total += os.path.getsize(os.path.join(root_, f)); n += 1
                    except OSError: pass
        self.p_size.setText("%d file(s), %.1f MB" % (n, total / 1048576.0))
    def clear_bake(self):
        try:
            from ..render.bake import clear_cache
            n, mb = clear_cache(getattr(getattr(self.app, "renderer", None), "bake", None))
            self.app.renderer.clear_preview_cache()
            QMessageBox.information(self, "Baked proxies", "Removed %d file(s), %.0f MB." % (n, mb))
        except Exception as ex: QMessageBox.warning(self, "Baked proxies", "Could not clear them: %s" % ex)
        self.refresh_storage()
    def clear_proxies(self):
        import shutil
        d = os.path.join(APP_DIR, "proxies")
        with self.app.renderer._src_lock: self.app.pool.reset()
        self.app.renderer.clear_preview_cache()
        failed = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                p = os.path.join(d, f)
                try: shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                except OSError: failed += 1
        self.refresh_proxy_size()
        if failed and getattr(self.app, "toast", None):
            self.app.toast.show_msg("%d proxy file(s) are still in use and could not be deleted. Close MiniCut and delete: %s" % (failed, d))
    def clear_extracted(self):
        d = os.path.join(APP_DIR, "extracted_audio")
        if os.path.isdir(d):
            for f in os.listdir(d):
                try: os.remove(os.path.join(d, f))
                except OSError: pass
    def test_gpu(self):
        from ..render.gpu import GPU
        mode = self.api_mode(); GPU.set_mode(mode)
        if mode == "off":
            self.gpu_lbl.setText("off (CPU only) \u2014 GPU compositing is disabled by selection."); self.app.request_render(); return
        GPU.retry(); self.gpu_lbl.setText("Testing ..."); self.app.request_render(); self._poll_gpu(8)
    def use_api(self):
        self.test_gpu()
        try: self.app.toast.show_msg("API: " + ("CPU" if self.api_mode() == "off" else "OpenGL") + " \u2014 press Save to keep it", 2200)
        except Exception: pass
    def _poll_gpu(self, n):
        from ..render.gpu import GPU
        self.gpu_lbl.setText(GPU.status)
        if n > 0 and GPU.status.startswith("testing"): QTimer.singleShot(600, lambda: self._poll_gpu(n - 1))
    def check_gpu(self):
        self.enc_lbl.setText("Testing ..."); QApplication.processEvents()
        from ..render.media import reset_bad_hw; reset_bad_hw()
        found = detect_gpu_encoders()
        self.enc_lbl.setText("GPU encoders that work: " + ", ".join(found) if found else "No GPU encoder works with this FFmpeg / driver. The CPU encoder will be used.")
    def save(self):
        s = self.app.settings
        s["asset_folder"] = self.asset.text(); s["project_folder"] = self.projf.text() or s["project_folder"]; s["export_folder"] = self.expf.text()
        s["preview_quality"] = self.q.currentData(); s["preview_interp"] = "fast" if self.interp.currentIndex() == 1 else "smooth"
        s["waveform_gain"] = float(self.wave_gain.value()); s["play_reduce"] = self.reduce.isChecked(); s["frame_cache"] = self.cache.value(); CFG["frame_cache"] = self.cache.value()
        s["preview_fps"] = int(self.fps.currentData()); s["adaptive_preview"] = self.adapt.isChecked(); s["hw_decode"] = self.hwdec.isChecked(); s["show_fps"] = self.showfps.isChecked()
        s["bake"] = self.bake_cb.isChecked(); s["fx_adapt"] = self.fxadapt.isChecked(); s["bake_max_gb"] = int(self.bake_gb.currentData()); s["encode_hw"] = self.enc.currentData()
        s["proxy_preview"] = self.proxy_cb.isChecked(); s["proxy_height"] = int(self.p_h.currentData()); s["proxy_quality"] = int(self.p_q.currentData())
        CFG["proxy_height"] = s["proxy_height"]; CFG["proxy_quality"] = s["proxy_quality"]; s["proxy_budget_gb"] = int(self.p_budget.value()); CFG["proxy_budget_gb"] = s["proxy_budget_gb"]
        s["fit_viewport"] = self.fit_cb.isChecked(); s["gpu_compose"] = self.api_mode(); s["render_threads"] = int(self.thr_box.currentData())
        s["preview_ram_mb"] = int(self.ram_box.currentData()); s["low_priority"] = self.prio_cb.isChecked(); s["proxy_hw"] = self.phw_box.currentData(); s["audio_cache_gb"] = int(self.audio_gb.value())
        s["export_preset"] = EXPORT_PRESETS[self.preset_list.index()][0]; s["export_space"] = int(self.space_list.index()); CFG["export_preset"] = s["export_preset"]
        if "export_parallel" in self._extra:
            s["export_parallel"] = int(self._extra["export_parallel"])
            try:
                from ..render.export import EXPORTS; EXPORTS.max_parallel = s["export_parallel"]
            except Exception: pass
        CFG["hw_decode"] = s["hw_decode"]; CFG["bake"] = s["bake"]; CFG["fx_adapt"] = s["fx_adapt"]; CFG["bake_max_gb"] = s["bake_max_gb"]; CFG["encode_hw"] = s["encode_hw"]; clear_gpu_cache()
        from ..render.gpu import GPU
        GPU.set_mode(s["gpu_compose"])
        s["audio_input"] = self.mic.currentData() or ""; s["autosave"] = self.autosave.isChecked(); s["autosave_min"] = self.autosave_min.value()
        os.makedirs(s["project_folder"], exist_ok=True); self._collect()
        try:
            from ..render.nodegraph import refresh_node_cats; refresh_node_cats()
        except Exception: pass
        s.save(); apply_ui(self.app); self._applied = False; self.accept()

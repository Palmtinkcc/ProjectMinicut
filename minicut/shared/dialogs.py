"""Settings and Shortcuts dialogs."""
from .deps import *
from .theme import *
from .core import *
from .appearance import *
from .widgets import *
from .hwaccel import *
from .ui import *
QSpinBox = SpinBox; QDoubleSpinBox = DoubleSpinBox; QComboBox = ComboBox; QCheckBox = CheckBox


class SettingsDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "Settings", 560); s = app.settings; self.app = app; self._snap = dict(UI); self._applied = False

        # ── helper ────────────────────────────────────────────────────────────
        def sec(title, icon=None):
            """Titled card section with a QFormLayout inside."""
            card = Section(title, icon); frm = QFormLayout(); frm.setSpacing(6)
            frm.setLabelAlignment(Qt.AlignLeft); card.body.addLayout(frm); return card, frm

        def row(frm, label, widget): frm.addRow(label, widget)

        # ── scroll area that holds all cards ─────────────────────────────────
        tabs = TabHost(); self.body.addWidget(tabs)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        gen_host = QWidget(); gen_host.setObjectName("SH"); gen_host.setStyleSheet("QWidget#SH{background:transparent;}")
        vl = QVBoxLayout(gen_host); vl.setContentsMargins(4, 6, 4, 6); vl.setSpacing(10)

        # ── 1. Folders ───────────────────────────────────────────────────────
        c1, f1 = sec("Folders", "folder")
        self.asset = PathEdit(s["asset_folder"]); self.projf = PathEdit(s["project_folder"]); self.expf = PathEdit(s["export_folder"])
        row(f1, "Assets", self.asset); row(f1, "Projects", self.projf); row(f1, "Export", self.expf)
        vl.addWidget(c1)

        # ── 2. Viewport / Preview ────────────────────────────────────────────
        c2, f2 = sec("Viewport & Preview", "image")
        self.q = QComboBox(); [self.q.addItem(l, v) for l, v in QUALITIES]; self.q.setCurrentIndex(max(0, self.q.findData(s["preview_quality"])))
        self.interp = QComboBox(); self.interp.addItems(["Smooth (bilinear)", "Fast (nearest)"]); self.interp.setCurrentIndex(1 if s["preview_interp"] == "fast" else 0)
        self.fps = QComboBox(); [self.fps.addItem("%d fps" % v, v) for v in (24, 30, 60)]; self.fps.setCurrentIndex(max(0, self.fps.findData(int(s["preview_fps"]))))
        self.cache = QSpinBox(); self.cache.setRange(4, 600); self.cache.setValue(s["frame_cache"]); self.cache.setSuffix(" frames / video")
        self.wave_gain = QDoubleSpinBox(); self.wave_gain.setRange(1.0, 8.0); self.wave_gain.setSingleStep(0.5); self.wave_gain.setDecimals(1); self.wave_gain.setSuffix(" ×"); self.wave_gain.setValue(float(s["waveform_gain"]))
        self.reduce = QCheckBox("Halve resolution while playing"); self.reduce.setChecked(s["play_reduce"])
        self.fit_cb = QCheckBox("Draw at display size (saves GPU)"); self.fit_cb.setChecked(bool(s["fit_viewport"]))
        self.adapt = QCheckBox("Auto-lower detail when slow"); self.adapt.setChecked(bool(s["adaptive_preview"]))
        row(f2, "Quality", self.q); row(f2, "Filter", self.interp); row(f2, "Preview FPS", self.fps)
        row(f2, "Frame cache", self.cache); row(f2, "Waveform height", self.wave_gain)
        row(f2, "", self.reduce); row(f2, "", self.fit_cb); row(f2, "", self.adapt)
        vl.addWidget(c2)

        # ── 3. GPU & Rendering ───────────────────────────────────────────────
        c3, f3 = sec("GPU & Rendering", "effects")
        self.hwdec = QCheckBox("GPU video decode (each file is checked against the CPU decoder; falls back to CPU)"); self.hwdec.setChecked(bool(s["hw_decode"]))
        self.showfps = QCheckBox("Show FPS on the preview (top-left corner)"); self.showfps.setChecked(bool(s["show_fps"]))
        self.bake_cb = QCheckBox("Adaptive proxy: bake heavy segments in the background (experimental)"); self.bake_cb.setChecked(bool(s["bake"]))
        self.bake_cb.setToolTip("When you stop editing, the heavy parts of the timeline (ALL layers combined, with their effects) are rendered once into small files and played from them.\nParts that play too slowly are found by measuring. Only used for the preview, never for export. Safe to switch off at any time.")
        self.fxadapt = QCheckBox("Slow effects use fewer pixels while playing (full quality when stopped)"); self.fxadapt.setChecked(bool(s["fx_adapt"]))
        self.fxadapt.setToolTip("Keeps the preview smooth when an effect is heavy. Export is never reduced. Switch off to always see effects in full while playing.")
        self.bake_gb = QComboBox()
        for g_ in (1, 2, 4, 8, 16): self.bake_gb.addItem("Baked proxy cache: up to %d GB" % g_, g_)
        self.bake_gb.setCurrentIndex(max(0, self.bake_gb.findData(int(s["bake_max_gb"]))))
        self.bake_clear = QPushButton("Clear baked proxies"); self.bake_clear.clicked.connect(self.clear_bake)
        self.enc = QComboBox(); [self.enc.addItem(l, v) for l, v in ENCODE_CHOICES]; self.enc.setCurrentIndex(max(0, self.enc.findData(s["encode_hw"])))
        gb = QPushButton("Check GPU encoders"); gb.clicked.connect(self.check_gpu)
        self.gpu_lbl = QLabel("Not checked yet."); self.gpu_lbl.setObjectName("Dim"); self.gpu_lbl.setWordWrap(True)
        self.gpu_box = QComboBox()
        for lab, val in (("Auto (GPU when self-test passes)", "auto"), ("CPU only", "off"), ("Always GPU", "on")): self.gpu_box.addItem(lab, val)
        self.gpu_box.setCurrentIndex(max(0, self.gpu_box.findData(s["gpu_compose"])))
        gpu_btn = QPushButton("Test GPU"); gpu_btn.clicked.connect(self.test_gpu)
        self.thr_box = QComboBox(); self.thr_box.addItem("Auto (leave 2 free)", 0)
        for n in (1, 2, 3, 4, 6, 8): self.thr_box.addItem(str(n), n)
        self.thr_box.setCurrentIndex(max(0, self.thr_box.findData(int(s["render_threads"]))))
        self.ram_box = QComboBox()
        for mb in (128, 256, 512, 1024, 2048): self.ram_box.addItem("%d MB" % mb, mb)
        self.ram_box.setCurrentIndex(max(0, self.ram_box.findData(int(s["preview_ram_mb"]))))
        self.prio_cb = QCheckBox("Keep render thread below window priority"); self.prio_cb.setChecked(bool(s["low_priority"]))
        row(f3, "", self.hwdec); row(f3, "", self.showfps); row(f3, "", self.bake_cb); row(f3, "", self.bake_gb); row(f3, "", self.bake_clear); row(f3, "", self.fxadapt); row(f3, "Export encoder", self.enc); row(f3, "", gb); row(f3, "GPU info", self.gpu_lbl)
        row(f3, "Compositing", self.gpu_box); row(f3, "", gpu_btn)
        row(f3, "Render threads", self.thr_box); row(f3, "RAM cache", self.ram_box); row(f3, "", self.prio_cb)
        try:
            from ..render.gpu import GPU
            self.gpu_lbl.setText(GPU.status)
        except Exception: pass
        vl.addWidget(c3)

        # ── 4. Proxy ─────────────────────────────────────────────────────────
        c4, f4 = sec("Proxy (smooth preview)", "video")
        self.proxy_cb = QCheckBox("Enable proxy (background down-scaled copies)"); self.proxy_cb.setChecked(bool(s["proxy_preview"]))
        self.p_h = QComboBox(); [self.p_h.addItem("%dp" % v, v) for v in (360, 540, 720)]; self.p_h.setCurrentIndex(max(0, self.p_h.findData(int(s["proxy_height"]))))
        self.p_q = QComboBox(); [self.p_q.addItem(l, v) for l, v in (("High quality", 18), ("Normal", 23), ("Small files", 28))]; self.p_q.setCurrentIndex(max(0, self.p_q.findData(int(s["proxy_quality"]))))
        self.p_budget = QSpinBox(); self.p_budget.setRange(25, 50); self.p_budget.setSuffix(" GB"); self.p_budget.setValue(int(s["proxy_budget_gb"]))
        self.p_size = QLabel(""); self.p_size.setObjectName("Dim")
        pb = QPushButton("Clear proxy cache"); pb.clicked.connect(self.clear_proxies)
        self.phw_box = QComboBox()
        for lab, val in (("Auto (GPU when available)", "auto"), ("CPU only", "cpu")): self.phw_box.addItem(lab, val)
        self.phw_box.setCurrentIndex(max(0, self.phw_box.findData(s["proxy_hw"])))
        self.audio_gb = QSpinBox(); self.audio_gb.setRange(1, 50); self.audio_gb.setSuffix(" GB"); self.audio_gb.setValue(int(s["audio_cache_gb"]))
        row(f4, "", self.proxy_cb); row(f4, "Proxy size", self.p_h); row(f4, "Proxy quality", self.p_q)
        row(f4, "Disk budget", self.p_budget); row(f4, "Cache used", self.p_size); row(f4, "", pb)
        row(f4, "Proxy encoder", self.phw_box); row(f4, "Audio cache", self.audio_gb)
        self.refresh_proxy_size()
        vl.addWidget(c4)

        # ── 5. Recording ─────────────────────────────────────────────────────
        c5, f5 = sec("Recording", "mic")
        from ..render.recorder import list_audio_inputs
        self.mic = QComboBox(); self.mic.addItem("System default", "")
        for _n, _id in list_audio_inputs(): self.mic.addItem(_n, _id)
        _cur = s["audio_input"]; _ix = self.mic.findData(_cur)
        if _ix < 0 and _cur: self.mic.addItem("Unplugged microphone (will use the default)", _cur); _ix = self.mic.count() - 1
        self.mic.setCurrentIndex(max(0, _ix))
        row(f5, "Microphone", self.mic)
        vl.addWidget(c5)

        # ── 6. Auto save ─────────────────────────────────────────────────────
        c6, f6 = sec("Auto save", "save")
        self.autosave = QCheckBox("Save the project automatically"); self.autosave.setChecked(bool(s["autosave"])); row(f6, "", self.autosave)
        self.autosave_min = QSpinBox(); self.autosave_min.setRange(1, 60); self.autosave_min.setSuffix(" min"); self.autosave_min.setValue(int(s["autosave_min"])); row(f6, "Every", self.autosave_min)
        vl.addWidget(c6)

        vl.addStretch(); scroll.setWidget(gen_host); tabs.addTab(scroll, "General")

        # ── Appearance tab ────────────────────────────────────────────────────
        app_scroll = QScrollArea(); app_scroll.setWidgetResizable(True); app_scroll.setFrameShape(QFrame.NoFrame)
        app_host = QWidget(); app_host.setObjectName("AppH"); app_host.setStyleSheet("QWidget#AppH{background:transparent;}")
        avl = QVBoxLayout(app_host); avl.setContentsMargins(4, 6, 4, 6); avl.setSpacing(10)
        self.th_w = {}; grp = None; cur_card = None; cur_frm = None
        for k, (g, lab, kind, dflt, lo, hi) in THEME_DEFS.items():
            if g != grp:
                grp = g; cur_card, cur_frm = sec(g)
                avl.addWidget(cur_card)
            if kind == "int": w = QSpinBox(); w.setRange(lo, hi)
            elif kind == "float": w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(1); w.setSingleStep(0.5)
            elif kind == "bool": w = QCheckBox()
            else: w = ColorButton(UI[k])
            self.th_w[k] = w; self._set(k, UI[k]); cur_frm.addRow(lab, w)
        avl.addStretch(); app_scroll.setWidget(app_host); tabs.addTab(app_scroll, "Appearance")

        # ── bottom buttons ────────────────────────────────────────────────────
        row_btns = QHBoxLayout()
        r = QPushButton("Reset appearance"); r.setToolTip("Restore all sizes and colors to defaults"); r.clicked.connect(self.reset_theme); row_btns.addWidget(r); row_btns.addStretch()
        a = QPushButton("Apply"); a.clicked.connect(self.apply_theme)
        c_btn = QPushButton("Cancel"); c_btn.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)
        for b in (a, c_btn, ok): row_btns.addWidget(b)
        self.body.addLayout(row_btns)
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
    def apply_theme(self):
        self._collect()
        try:
            from ..render.nodegraph import refresh_node_cats; refresh_node_cats()
        except Exception: pass
        apply_ui(self.app); self._applied = True
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
        """Delete the baked segment proxies (Adaptive Proxy). The source-media proxies are cleared by the button below."""
        try:
            from ..render.bake import clear_cache
            n, mb = clear_cache(getattr(getattr(self.app, "renderer", None), "bake", None))
            self.app.renderer.clear_preview_cache()
            QMessageBox.information(self, "Baked proxies", "Removed %d file(s), %.0f MB." % (n, mb))
        except Exception as ex: QMessageBox.warning(self, "Baked proxies", "Could not clear them: %s" % ex)
    def clear_proxies(self):
        import shutil
        d = os.path.join(APP_DIR, "proxies")
        with self.app.renderer._src_lock: self.app.pool.reset()   # cancels jobs and closes the open proxy files
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
    def test_gpu(self):
        from ..render.gpu import GPU
        mode = self.gpu_box.currentData()
        GPU.set_mode(mode)
        if mode == "off":
            self.gpu_lbl.setText("off (CPU only) — GPU compositing is disabled by selection.")
            self.app.request_render()
            return
        GPU.retry(); self.gpu_lbl.setText("Testing ...")
        self.app.request_render(); self._poll_gpu(8)
    def _poll_gpu(self, n):
        from ..render.gpu import GPU
        self.gpu_lbl.setText(GPU.status)
        if n > 0 and GPU.status.startswith("testing"): QTimer.singleShot(600, lambda: self._poll_gpu(n - 1))
    def check_gpu(self):
        self.gpu_lbl.setText("Testing ..."); QApplication.processEvents()
        from ..render.media import reset_bad_hw; reset_bad_hw()      # give the GPU proxy encoder another chance too
        found = detect_gpu_encoders()
        self.gpu_lbl.setText("GPU encoders that work: " + ", ".join(found) if found else "No GPU encoder works with this FFmpeg / driver. The CPU encoder will be used.")
    def save(self):
        s = self.app.settings
        s["asset_folder"] = self.asset.text(); s["project_folder"] = self.projf.text() or s["project_folder"]; s["export_folder"] = self.expf.text()
        s["preview_quality"] = self.q.currentData(); s["preview_interp"] = "fast" if self.interp.currentIndex() == 1 else "smooth"
        s["waveform_gain"] = float(self.wave_gain.value()); s["play_reduce"] = self.reduce.isChecked(); s["frame_cache"] = self.cache.value(); CFG["frame_cache"] = self.cache.value()
        s["preview_fps"] = int(self.fps.currentData()); s["adaptive_preview"] = self.adapt.isChecked(); s["hw_decode"] = self.hwdec.isChecked(); s["show_fps"] = self.showfps.isChecked(); s["bake"] = self.bake_cb.isChecked(); s["fx_adapt"] = self.fxadapt.isChecked(); s["bake_max_gb"] = int(self.bake_gb.currentData()); s["encode_hw"] = self.enc.currentData(); s["proxy_preview"] = self.proxy_cb.isChecked(); s["proxy_height"] = int(self.p_h.currentData()); s["proxy_quality"] = int(self.p_q.currentData()); CFG["proxy_height"] = s["proxy_height"]; CFG["proxy_quality"] = s["proxy_quality"]; s["proxy_budget_gb"] = int(self.p_budget.value()); CFG["proxy_budget_gb"] = s["proxy_budget_gb"]
        s["fit_viewport"] = self.fit_cb.isChecked(); s["gpu_compose"] = self.gpu_box.currentData(); s["render_threads"] = int(self.thr_box.currentData())
        s["preview_ram_mb"] = int(self.ram_box.currentData()); s["low_priority"] = self.prio_cb.isChecked(); s["proxy_hw"] = self.phw_box.currentData(); s["audio_cache_gb"] = int(self.audio_gb.value())
        CFG["hw_decode"] = s["hw_decode"]; CFG["bake"] = s["bake"]; CFG["fx_adapt"] = s["fx_adapt"]; CFG["bake_max_gb"] = s["bake_max_gb"]; CFG["encode_hw"] = s["encode_hw"]; clear_gpu_cache()
        # The dropdown is a live setting; do not require pressing "Test GPU" for it to take effect.
        from ..render.gpu import GPU
        GPU.set_mode(s["gpu_compose"])
        s["audio_input"] = self.mic.currentData() or ""; s["autosave"] = self.autosave.isChecked(); s["autosave_min"] = self.autosave_min.value()
        os.makedirs(s["project_folder"], exist_ok=True); self._collect()
        try:
            from ..render.nodegraph import refresh_node_cats; refresh_node_cats()
        except Exception: pass
        s.save(); apply_ui(self.app); self._applied = False; self.accept()


class ShortcutDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "Keyboard shortcuts", 520); self.app = app; sc = app.settings["shortcuts"]
        self.table = QTableWidget(len(DEFAULT_SHORTCUTS), 2); self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220); self.table.setMinimumHeight(420); self.edits = {}
        for i, k in enumerate(DEFAULT_SHORTCUTS):
            it = QTableWidgetItem(ACTION_LABELS[k]); it.setFlags(Qt.ItemIsEnabled); self.table.setItem(i, 0, it)
            e = QKeySequenceEdit(QKeySequence(sc.get(k, ""))); self.edits[k] = e; self.table.setCellWidget(i, 1, e)
        self.body.addWidget(self.table)
        row = QHBoxLayout(); r = QPushButton("Reset defaults"); r.clicked.connect(self.reset); row.addWidget(r); row.addStretch()
        c = QPushButton("Cancel"); c.clicked.connect(self.reject); ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)
        row.addWidget(c); row.addWidget(ok); self.body.addLayout(row)
    def reset(self):
        for k, e in self.edits.items(): e.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[k]))
    def save(self):
        seqs = {k: e.keySequence().toString(QKeySequence.PortableText) for k, e in self.edits.items()}
        used = [v for v in seqs.values() if v]
        dup = {v for v in used if used.count(v) > 1}
        if dup: ask(self, "Duplicate shortcut", "These shortcuts are used more than once: " + ", ".join(dup), ("OK",)); return
        self.app.settings["shortcuts"].update(seqs); self.app.settings.save(); self.app.apply_shortcuts(); self.accept()

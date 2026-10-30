"""Settings and Shortcuts dialogs."""
from .deps import *
from .theme import *
from .core import *
from .appearance import *
from .widgets import *
from .hwaccel import *


class SettingsDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "Settings", 700); s = app.settings; self.app = app; self._snap = dict(UI); self._applied = False
        tabs = QTabWidget(); self.body.addWidget(tabs)
        gen = QWidget(); form = QFormLayout(gen)
        self.asset = PathEdit(s["asset_folder"]); self.projf = PathEdit(s["project_folder"]); self.expf = PathEdit(s["export_folder"])
        self.q = QComboBox(); [self.q.addItem(l, v) for l, v in QUALITIES]; self.q.setCurrentIndex(max(0, self.q.findData(s["preview_quality"])))
        self.interp = QComboBox(); self.interp.addItems(["Smooth (bilinear)", "Fast (nearest)"]); self.interp.setCurrentIndex(1 if s["preview_interp"] == "fast" else 0)
        self.reduce = QCheckBox("Halve preview resolution while playing"); self.reduce.setChecked(s["play_reduce"])
        self.cache = QSpinBox(); self.cache.setRange(4, 600); self.cache.setValue(s["frame_cache"]); self.cache.setSuffix(" frames / video")
        for lab, w in (("Asset folder", self.asset), ("Project folder", self.projf), ("Export folder", self.expf), ("Viewport quality", self.q),
                       ("Viewport filter", self.interp), ("", self.reduce), ("Frame cache", self.cache)): form.addRow(lab, w)
        self.fps = QComboBox(); [self.fps.addItem("%d fps" % v, v) for v in (24, 30, 60)]; self.fps.setCurrentIndex(max(0, self.fps.findData(int(s["preview_fps"]))))
        self.adapt = QCheckBox("Lower preview detail automatically when playback cannot keep up"); self.adapt.setChecked(bool(s["adaptive_preview"]))
        self.hwdec = QCheckBox("Decode video on the GPU (disabled: it causes a pink band in the preview)"); self.hwdec.setChecked(bool(s["hw_decode"]))
        self.enc = QComboBox(); [self.enc.addItem(l, v) for l, v in ENCODE_CHOICES]; self.enc.setCurrentIndex(max(0, self.enc.findData(s["encode_hw"])))
        self.gpu_lbl = QLabel("Not checked yet. Press the button to test which GPU encoders work on this PC."); self.gpu_lbl.setObjectName("Dim"); self.gpu_lbl.setWordWrap(True)
        gb = QPushButton("Check GPU encoders"); gb.clicked.connect(self.check_gpu)
        form.addRow("Preview FPS", self.fps); form.addRow("", self.adapt); form.addRow("", self.hwdec)
        self.proxy_cb = QCheckBox("Smooth preview: use small background proxy copies (export always uses the original)"); self.proxy_cb.setChecked(bool(s["proxy_preview"]))
        self.p_h = QComboBox(); [self.p_h.addItem("%dp" % v, v) for v in (360, 540, 720)]; self.p_h.setCurrentIndex(max(0, self.p_h.findData(int(s["proxy_height"]))))
        self.p_q = QComboBox(); [self.p_q.addItem(l, v) for l, v in (("High quality (bigger files)", 18), ("Normal", 23), ("Small files", 28))]; self.p_q.setCurrentIndex(max(0, self.p_q.findData(int(s["proxy_quality"]))))
        self.p_size = QLabel(""); self.p_size.setObjectName("Dim"); self.p_size.setWordWrap(True)
        pb = QPushButton("Clear proxy cache"); pb.setToolTip("Delete all proxy files. They are rebuilt when needed."); pb.clicked.connect(self.clear_proxies)
        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl); form.addRow("", self.proxy_cb)
        form.addRow("Proxy size", self.p_h); form.addRow("Proxy quality", self.p_q); form.addRow("Proxy cache", self.p_size); form.addRow("", pb)
        self.refresh_proxy_size()
        tabs.addTab(gen, "General")
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setMinimumHeight(400)
        host = QWidget(); host.setObjectName("SettingsHost"); host.setStyleSheet("QWidget#SettingsHost{background:transparent;}")
        vl = QVBoxLayout(host); vl.setContentsMargins(4, 6, 12, 6); vl.setSpacing(6)
        self.th_w = {}; grp = None; f2 = None
        for k, (g, lab, kind, dflt, lo, hi) in THEME_DEFS.items():
            if g != grp:
                grp = g; h = QLabel(g); h.setObjectName("H2"); vl.addSpacing(6); vl.addWidget(h)
                f2 = QFormLayout(); f2.setLabelAlignment(Qt.AlignLeft); vl.addLayout(f2)
            if kind == "int": w = QSpinBox(); w.setRange(lo, hi)
            elif kind == "float": w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(1); w.setSingleStep(0.5)
            elif kind == "bool": w = QCheckBox()
            else: w = ColorButton(UI[k])
            self.th_w[k] = w; self._set(k, UI[k]); f2.addRow(lab, w)
        vl.addStretch(); sc.setWidget(host); tabs.addTab(sc, "Appearance")
        row = QHBoxLayout(); r = QPushButton("Reset appearance"); r.setToolTip("Put every size and color back to its default"); r.clicked.connect(self.reset_theme); row.addWidget(r); row.addStretch()
        a = QPushButton("Apply"); a.clicked.connect(self.apply_theme); c = QPushButton("Cancel"); c.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)
        for b in (a, c, ok): row.addWidget(b)
        self.body.addLayout(row)
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
        self._collect(); apply_ui(self.app); self._applied = True
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
    def check_gpu(self):
        self.gpu_lbl.setText("Testing ..."); QApplication.processEvents()
        found = detect_gpu_encoders()
        self.gpu_lbl.setText("GPU encoders that work: " + ", ".join(found) if found else "No GPU encoder works with this FFmpeg / driver. The CPU encoder will be used.")
    def save(self):
        s = self.app.settings
        s["asset_folder"] = self.asset.text(); s["project_folder"] = self.projf.text() or s["project_folder"]; s["export_folder"] = self.expf.text()
        s["preview_quality"] = self.q.currentData(); s["preview_interp"] = "fast" if self.interp.currentIndex() == 1 else "smooth"
        s["play_reduce"] = self.reduce.isChecked(); s["frame_cache"] = self.cache.value(); CFG["frame_cache"] = self.cache.value()
        s["preview_fps"] = int(self.fps.currentData()); s["adaptive_preview"] = self.adapt.isChecked(); s["hw_decode"] = self.hwdec.isChecked(); s["encode_hw"] = self.enc.currentData(); s["proxy_preview"] = self.proxy_cb.isChecked(); s["proxy_height"] = int(self.p_h.currentData()); s["proxy_quality"] = int(self.p_q.currentData()); CFG["proxy_height"] = s["proxy_height"]; CFG["proxy_quality"] = s["proxy_quality"]
        CFG["hw_decode"] = s["hw_decode"]; CFG["encode_hw"] = s["encode_hw"]; clear_gpu_cache()
        os.makedirs(s["project_folder"], exist_ok=True); self._collect(); s.save(); apply_ui(self.app); self._applied = False; self.accept()


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

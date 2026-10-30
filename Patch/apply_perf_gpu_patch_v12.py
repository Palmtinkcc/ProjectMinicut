#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 12: CURVE PANEL, DENOISE, VOICE RECORDING
==============================================================
Install AFTER apply_perf_gpu_patch_v12.py.

  * Keyframes tab, rebuilt: the curve editor is on top, then the properties the curve applies to (toggle buttons;
    only the ones the clip has), the actions (Apply to all, All segments, Clear, Clear all), and the curve presets
    as small pictures. "More…" shows all presets; "Save curve" keeps the curve you made as a preset of your own.
  * Audio effect "Denoise" (amount, floor): removes steady background noise such as hiss or fan noise. It finds
    the noise in the quietest parts of the clip, so no noise sample is needed.
  * "● Rec" in the Media panel: records your voice from the microphone into the project. The take is saved in the
    asset folder (Recordings/) and placed as an audio clip where the recording started. "■ Stop" finishes it.

New files: minicut/render/recorder.py, minicut/workspace/curve_panel.py
Changed files: minicut/render/afx.py, minicut/shared/core.py, minicut/app.py, minicut/workspace/panels.py
(originals are backed up first)

    python apply_perf_gpu_patch_v12.py            install the update
    python apply_perf_gpu_patch_v12.py --check    only show what would change
    python apply_perf_gpu_patch_v12.py --revert   undo the last install
    python apply_perf_gpu_patch_v12.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': '2bc21f3c670a2d3c61b9d4a6635486a23f2f4b4a7f1c5d3a87bcb58d0af0e4f6',
                    'crlf': False,
                    'edits': [('from .render.export import *\n', 'from .render.export import *\nfrom .render.recorder import *\n'),
                              ('    def closeEvent(self,e):\n',
                               '    def toggle_record(self):\n'
                               '        """Record your voice (like CapCut): the take becomes an audio clip where the recording started."""\n'
                               '        if not self.proj: return\n'
                               '        if getattr(self, "recorder", None) is None: self.recorder = VoiceRecorder()\n'
                               '        rec = self.recorder; btn = getattr(getattr(self, "media", None), "rec_btn", None)\n'
                               '        if not rec.active():\n'
                               '            try:\n'
                               '                rec.start(self.settings["asset_folder"]); self._rec_start = self.t\n'
                               '                if btn is not None: btn.setText("■ Stop")\n'
                               '            except Exception as ex: QMessageBox.warning(self, "MiniCut", "Could not start recording:\\n%s" % ex)\n'
                               '            return\n'
                               '        path = rec.stop()\n'
                               '        if btn is not None: btn.setText("● Rec")\n'
                               '        if path: self.add_files([path], self._rec_start)\n'
                               '    def closeEvent(self,e):\n')],
                    'new': '445bf216e1bf02a670aaed47f239a7a33929df0106309a1825dd7cc23b606a9b'},
 'minicut/render/afx.py': {'base': '7ed831b5ad07fc4bfcb2bf8a808f268639e45182b4b5b05b2c3650b0c0f61d2d',
                           'crlf': False,
                           'edits': [('    ("pan", {"title": "Pan", "params": [("pan", "Pan  (L ← 0 → R)", -100, 100, 0, 1)]}),\n',
                                      '    ("denoise", {"title": "Denoise", "params": [("amount", "Amount %", 0, 100, 60, 1), ("floor", "Floor %", 0, 50, 5, '
                                      '1)]}),\n'
                                      '    ("pan", {"title": "Pan", "params": [("pan", "Pan  (L ← 0 → R)", -100, 100, 0, 1)]}),\n'),
                                     ('AFX_FN = {',
                                      'def fx_denoise(x, p, sr=SR):\n'
                                      '    """Spectral noise reduction: the noise is the quietest 10 % of the frames of each frequency. That part is\n'
                                      '    taken away from every frame (a floor keeps it from sounding hollow)."""\n'
                                      '    amount = float(p["amount"]) / 100; floor = float(p["floor"]) / 100\n'
                                      '    if amount <= 0 or len(x) < 4096: return x\n'
                                      '    n = 2048; hop = 512; win = np.hanning(n).astype(np.float32)\n'
                                      '    N = len(x); pad = np.zeros((N + 2 * n, 2), np.float32); pad[n:n + N] = x\n'
                                      '    nf = 1 + (len(pad) - n) // hop\n'
                                      '    idx = np.arange(n)[None, :] + hop * np.arange(nf)[:, None]\n'
                                      '    sub = idx[::4]\n'
                                      '    noise = np.percentile(np.abs(np.fft.rfft(pad[sub] * win[None, :, None], axis=1)), 10, axis=0)   # (bins, 2)\n'
                                      '    out = np.zeros_like(pad); wsum = np.zeros((len(pad), 1), np.float32); wsq = (win ** 2)[:, None]\n'
                                      '    for s in range(0, nf, 2000):\n'
                                      '        ii = idx[s:s + 2000]\n'
                                      '        X = np.fft.rfft(pad[ii] * win[None, :, None], axis=1); m = np.abs(X)\n'
                                      '        g = np.maximum(m - amount * 1.5 * noise[None], floor * m) / np.maximum(m, 1e-9)\n'
                                      '        Y = (np.fft.irfft(X * g, n, axis=1) * win[None, :, None]).astype(np.float32)\n'
                                      '        for r in range(n // hop):          # frames r, r+4, ... never overlap each other: one fancy add per group\n'
                                      '            sel = np.arange(r, len(ii), n // hop)\n'
                                      '            if not len(sel): continue\n'
                                      '            rows = ii[sel]\n'
                                      '            out[rows] += Y[sel]; wsum[rows] += wsq[None, :, :]\n'
                                      '    res = out / np.maximum(wsum, 1e-6)\n'
                                      '    return np.clip(res[n:n + N], -1.0, 1.0).astype(np.float32)\n'
                                      '\n'
                                      '\n'
                                      'AFX_FN = {"denoise": fx_denoise, ')],
                           'new': 'ace4ca9e4becac9d544b4bac98f729d2865d23136ea295e020e5fcc78c23f480'},
 'minicut/shared/core.py': {'base': '82b88c5298aa5314a290864ea62e7671a66a4aed3f1653a9ec08ac32ae503e2f',
                            'crlf': False,
                            'edits': [('"layout": None,', '"layout": None, "curve_presets": {},')],
                            'new': 'd3a9d8ab2a49eaef9072f3e8c61cc2403c4fc359311852415e3e17cd96629cda'},
 'minicut/workspace/panels.py': {'base': '7227d6d61539c001c7057ec77f8568420102b87329d8e37b3a039441f136ceec',
                                 'crlf': False,
                                 'edits': [('from .afx_panel import AudioFxPanel\n',
                                            'from .afx_panel import AudioFxPanel\nfrom .curve_panel import PresetTile, all_presets\n'),
                                           ('        text_btn = tool("", "Add text", app.add_text); text_btn.setIcon(app_icon("text")); '
                                            'self.head.addWidget(text_btn)\n',
                                            '        text_btn = tool("", "Add text", app.add_text); text_btn.setIcon(app_icon("text")); '
                                            'self.head.addWidget(text_btn)\n'
                                            '        self.rec_btn = tool("● Rec", "Record your voice into the project (click to start, click again to stop)", '
                                            'app.toggle_record); self.head.addWidget(self.rec_btn)\n'),
                                           ('        name = self.kprop.currentData(); ks = c["props"][name]["k"]; self._seg = None\n',
                                            '        self._sync_toggles(c)\n'
                                            '        name = self.kprop.currentData(); ks = c["props"][name]["k"]; self._seg = None\n'),
                                           ('    def toggle_key(self, name, only_remove=False):\n',
                                            '    # ---- keyframe tab helpers: curve toggles, presets, apply / clear ----\n'
                                            '    def _curve_props(self, c):\n'
                                            '        if c is None: return []\n'
                                            '        return [k for k, _ in KEY_PROPS if (k == "volume") == (c["kind"] == "audio") and k in c["props"]]\n'
                                            '    def _sync_toggles(self, c):\n'
                                            '        cid = c["id"] if c else None\n'
                                            '        if getattr(self, "_toggle_cid", None) != cid: self._toggle_cid = cid; self.checked = set(); '
                                            'self._presets_key = None\n'
                                            '        avail = self._curve_props(c)\n'
                                            '        for k, b in self.toggles.items():\n'
                                            '            b.setVisible(k in avail); b.blockSignals(True); b.setChecked(k in self.checked); '
                                            'b.blockSignals(False)\n'
                                            '        key = (cid, len(self.app.settings["curve_presets"] or {}), self._more)\n'
                                            '        if self._presets_key != key: self._rebuild_presets()\n'
                                            '    def on_toggle(self, k, on):\n'
                                            '        if on: self.checked.add(k); self.kprop.setCurrentIndex(self.kprop.findData(k))\n'
                                            '        else: self.checked.discard(k)\n'
                                            '    def apply_checked(self):\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if not c: return\n'
                                            '        curve = self._curve_to_copy(); names = list(self.checked) or [self.kprop.currentData()]\n'
                                            '        targets = [kf for n in names for kf in c["props"].get(n, {}).get("k", [])[:-1]]\n'
                                            '        if not targets:\n'
                                            '            if hasattr(self.app, "toast"): self.app.toast.show_msg("Add at least 2 keyframes to the checked '
                                            'properties first")\n'
                                            '            return\n'
                                            '        self.app.checkpoint()\n'
                                            '        for kf in targets: kf["e"] = list(curve)\n'
                                            '        self.app.on_changed(insp=False); self.refresh()\n'
                                            '    def clear_all_keys(self):\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if not c: return\n'
                                            '        self.app.checkpoint(); t = self.app.t - c["start"]\n'
                                            '        for n in self._curve_props(c): c["props"][n]["v"] = prop_at(c, n, t); c["props"][n]["k"] = []\n'
                                            '        self.app.on_changed(insp=False); self.refresh()\n'
                                            '    def apply_curve(self, curve):\n'
                                            '        self.ease.set_e(curve)\n'
                                            '        if self._seg is not None: self.on_ease(curve)\n'
                                            '    def _toggle_more(self):\n'
                                            '        self._more = not self._more; self._rebuild_presets()\n'
                                            '    def _save_preset(self):\n'
                                            '        name, ok = QInputDialog.getText(self, "Save curve", "Name for this curve:")\n'
                                            '        name = (name or "").strip()\n'
                                            '        if not ok or not name: return\n'
                                            '        if not isinstance(self.app.settings["curve_presets"], dict): self.app.settings["curve_presets"] = {}\n'
                                            '        self.app.settings["curve_presets"][name] = [float(v) for v in self.ease.e]; self.app.settings.save(); '
                                            'self._rebuild_presets()\n'
                                            '    def _rebuild_presets(self):\n'
                                            '        c = self.app.sel_clip(); cid = c["id"] if c else None\n'
                                            '        self._presets_key = (cid, len(self.app.settings["curve_presets"] or {}), self._more)\n'
                                            '        while self.preset_grid.count():\n'
                                            '            w = self.preset_grid.takeAt(0).widget()\n'
                                            '            if w: w.deleteLater()\n'
                                            '        items = list(all_presets(self.app.settings).items())\n'
                                            '        shown = items if self._more else items[:6]\n'
                                            '        for i, (name, curve) in enumerate(shown):\n'
                                            '            tile = PresetTile(name, curve, selected=[round(v, 3) for v in curve] == [round(float(v), 3) for v in '
                                            'self.ease.e])\n'
                                            '            tile.clicked.connect(self.apply_curve); self.preset_grid.addWidget(tile, i // 3, i % 3)\n'
                                            '        self.more_btn.setText("Less" if self._more else "More…")\n'
                                            '        self.more_btn.setVisible(len(items) > 6)\n'
                                            '    def toggle_key(self, name, only_remove=False):\n'),
                                           ('        # Keyframes\n'
                                            '        sa, f = page(); r = QHBoxLayout(); self.kprop = QComboBox(); [self.kprop.addItem(lab, k) for k, lab in '
                                            'KEY_PROPS]\n'
                                            '        self.kprop.currentIndexChanged.connect(lambda *_: self.refresh()); r.addWidget(self.kprop, 1)\n'
                                            '        r.addWidget(tool("", "Previous keyframe", lambda: self.jump(-1), icon=svg_combo_icon(("angle_left", '
                                            '"keyframe")), isize=26)); r.addWidget(tool("", "Next keyframe", lambda: self.jump(1), '
                                            'icon=svg_combo_icon(("keyframe", "angle_right")), isize=26)); f.addLayout(r)\n'
                                            '        self.kinfo = QLabel(); self.kinfo.setObjectName("Dim"); self.kinfo.setWordWrap(True); '
                                            'f.addWidget(self.kinfo)\n'
                                            '        r = QHBoxLayout(); self.preset = QComboBox(); self.preset.addItems(list(EASE_PRESETS) + ["Custom"])\n'
                                            '        self.preset.activated.connect(self.on_preset); r.addWidget(QLabel("Curve")); r.addWidget(self.preset, 1)\n'
                                            '        ab = QPushButton("Apply curve to all segments"); ab.setToolTip("Copy the current curve to every segment '
                                            'of this property"); ab.clicked.connect(self.apply_all); r.addWidget(ab); f.addLayout(r)\n'
                                            '        self.apply_transform_btn = QPushButton("Apply this curve to all Transform")\n'
                                            '        self.apply_transform_btn.setIcon(app_icon("check"))\n'
                                            '        self.apply_transform_btn.setMinimumHeight(30)\n'
                                            '        self.apply_transform_btn.setToolTip("Apply the curve shown below to Position, Scale, Rotation and Opacity '
                                            'keyframe segments on this clip")\n'
                                            '        self.apply_transform_btn.clicked.connect(self.apply_transform_all); '
                                            'f.addWidget(self.apply_transform_btn)\n'
                                            '        self.ease = EaseEditor(); self.ease.changed.connect(self.on_ease); f.addWidget(self.ease)\n'
                                            '        r = QHBoxLayout(); b1 = QPushButton("Delete key"); b1.clicked.connect(lambda: '
                                            'self.toggle_key(self.kprop.currentData(), only_remove=True))\n'
                                            '        b2 = QPushButton("Clear all"); b2.clicked.connect(self.clear_keys); r.addWidget(b1); r.addWidget(b2); '
                                            'f.addLayout(r); f.addStretch()\n'
                                            '        self.tabs.addTab(sa, "Keyframes")\n',
                                            '        # Keyframes: the curve on top, then what it applies to, the actions and the curve presets\n'
                                            '        sa, f = page(); self.checked = set(); self._toggle_cid = None; self._more = False; self._presets_key = '
                                            'None\n'
                                            '        self.kprop = QComboBox(); [self.kprop.addItem(lab, k) for k, lab in KEY_PROPS]; self.kprop.hide()\n'
                                            '        self.kprop.currentIndexChanged.connect(lambda *_: self.refresh())\n'
                                            '        self.preset = QComboBox(); self.preset.addItems(list(EASE_PRESETS) + ["Custom"]); self.preset.hide()\n'
                                            '        self.ease = EaseEditor(); self.ease.changed.connect(self.on_ease); self.ease.setMinimumHeight(200); '
                                            'f.addWidget(self.ease)\n'
                                            '        self.kinfo = QLabel(); self.kinfo.setObjectName("Dim"); self.kinfo.setWordWrap(True); '
                                            'f.addWidget(self.kinfo)\n'
                                            '        lab = QLabel("Applies to"); lab.setObjectName("H2"); f.addWidget(lab)\n'
                                            '        self.toggle_row = QGridLayout(); self.toggle_row.setSpacing(4); f.addLayout(self.toggle_row)\n'
                                            '        self.toggles = {}\n'
                                            '        for i, (k, name) in enumerate(KEY_PROPS):\n'
                                            '            b = QToolButton(); b.setText(name); b.setCheckable(True); '
                                            'b.setToolButtonStyle(Qt.ToolButtonTextOnly); b.setMinimumHeight(26)\n'
                                            '            b.toggled.connect(lambda v, k=k: self.on_toggle(k, v)); self.toggles[k] = b; '
                                            'self.toggle_row.addWidget(b, i // 3, i % 3)\n'
                                            '        acts = QGridLayout(); acts.setSpacing(4)\n'
                                            '        for i, (label, tip, cb) in enumerate((\n'
                                            '                ("Apply to all", "Copy the curve to every segment of the checked properties", '
                                            'self.apply_checked),\n'
                                            '                ("All segments", "Copy the curve to every segment of the current property", self.apply_all),\n'
                                            '                ("Clear", "Delete the keyframes of the current property", self.clear_keys),\n'
                                            '                ("Clear all", "Delete the keyframes of every property of this clip", self.clear_all_keys))):\n'
                                            '            b = QPushButton(label); b.setToolTip(tip); b.clicked.connect(cb); acts.addWidget(b, i // 2, i % 2)\n'
                                            '        f.addLayout(acts)\n'
                                            '        head = QHBoxLayout(); l2 = QLabel("Curve presets"); l2.setObjectName("H2"); head.addWidget(l2); '
                                            'head.addStretch()\n'
                                            '        save = QPushButton("Save curve"); save.setToolTip("Keep the curve shown above as a preset of your own"); '
                                            'save.clicked.connect(self._save_preset); head.addWidget(save)\n'
                                            '        self.more_btn = QPushButton("More…"); self.more_btn.clicked.connect(self._toggle_more); '
                                            'head.addWidget(self.more_btn); f.addLayout(head)\n'
                                            '        self.preset_grid = QGridLayout(); self.preset_grid.setSpacing(6); f.addLayout(self.preset_grid)\n'
                                            '        b1 = QPushButton("Delete key"); b1.clicked.connect(lambda: self.toggle_key(self.kprop.currentData(), '
                                            'only_remove=True))\n'
                                            '        f.addWidget(b1); f.addStretch()\n'
                                            '        self.tabs.addTab(sa, "Keyframes")\n')],
                                 'new': '6c0efc8a984fe27258b8eaf97e4dc30f67c24621731e976c159544e4d695f751'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {'minicut/render/recorder.py': '"""Voice recording into the project: the microphone is recorded to a WAV file in the asset folder (Recordings/)."""\n'
                               'from ..shared.deps import *\n'
                               'from ..shared.core import *\n'
                               '\n'
                               'try:\n'
                               '    from PySide6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices\n'
                               'except Exception:\n'
                               '    QAudioSource = None\n'
                               '\n'
                               '\n'
                               'class VoiceRecorder(QObject):\n'
                               '    def __init__(self):\n'
                               '        super().__init__(); self.src = None; self.io = None; self.chunks = []; self.t0 = 0.0; self.rate = SR; self.ch = 2\n'
                               '        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self._pull)\n'
                               '    def active(self): return self.src is not None\n'
                               '    def seconds(self): return (time.monotonic() - self.t0) if self.src is not None else 0.0\n'
                               '    def start(self, folder):\n'
                               '        self.folder = folder\n'
                               '        if QAudioSource is None: raise RuntimeError("Recording needs QtMultimedia, which is not available here.")\n'
                               '        dev = QMediaDevices.defaultAudioInput()\n'
                               '        if dev.isNull(): raise RuntimeError("No microphone was found.")\n'
                               '        fmt = QAudioFormat(); fmt.setSampleRate(SR); fmt.setChannelCount(2); '
                               'fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)\n'
                               '        if not dev.isFormatSupported(fmt): fmt = dev.preferredFormat(); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)\n'
                               '        self.rate = fmt.sampleRate(); self.ch = fmt.channelCount()\n'
                               '        self.src = QAudioSource(dev, fmt); self.chunks = []; self.io = self.src.start(); self.t0 = time.monotonic(); '
                               'self.timer.start()\n'
                               '    def _pull(self):\n'
                               '        if self.io is None: return\n'
                               '        data = bytes(self.io.readAll())\n'
                               '        if data: self.chunks.append(data)\n'
                               '    def stop(self):\n'
                               '        """Finish the take. Returns the WAV path (stereo, 16 bit) or None if the take is too short."""\n'
                               '        if self.src is None: return None\n'
                               '        self.timer.stop(); self._pull(); self.src.stop(); self.src = None; self.io = None\n'
                               '        raw = b"".join(self.chunks); self.chunks = []\n'
                               '        frame = 2 * self.ch\n'
                               '        if len(raw) < frame * self.rate // 4: return None\n'
                               '        arr = np.frombuffer(raw[: len(raw) // frame * frame], "<i2").reshape(-1, self.ch)\n'
                               '        if self.ch == 1: arr = np.repeat(arr, 2, axis=1)\n'
                               '        folder = os.path.join(self.folder, "Recordings"); os.makedirs(folder, exist_ok=True)\n'
                               '        path = os.path.join(folder, "voice_%s.wav" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))\n'
                               '        with wave.open(path, "wb") as w:\n'
                               '            w.setnchannels(2); w.setsampwidth(2); w.setframerate(self.rate); w.writeframes(np.ascontiguousarray(arr[:, :2], '
                               '"<i2").tobytes())\n'
                               '        return path\n',
 'minicut/workspace/curve_panel.py': '"""Keyframes tab helpers: curve presets drawn as small pictures, and the curve preset list."""\n'
                                     'from ..shared.deps import *\n'
                                     'from ..shared.core import *\n'
                                     '\n'
                                     '\n'
                                     'def bezier_points(e, n=40):\n'
                                     '    x1, y1, x2, y2 = [float(v) for v in e]; pts = []\n'
                                     '    for i in range(n + 1):\n'
                                     '        t = i / n; u = 1 - t\n'
                                     '        pts.append((3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3, 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** '
                                     '3))\n'
                                     '    return pts\n'
                                     '\n'
                                     '\n'
                                     'def all_presets(settings):\n'
                                     '    out = OrderedDict(EASE_PRESETS)\n'
                                     '    for k, v in (settings["curve_presets"] or {}).items(): out[k] = v\n'
                                     '    return out\n'
                                     '\n'
                                     '\n'
                                     'class PresetTile(QWidget):\n'
                                     '    clicked = Signal(object)\n'
                                     '    def __init__(self, name, curve, selected=False):\n'
                                     '        super().__init__(); self.name = name; self.curve = [float(v) for v in curve]; self.selected = selected\n'
                                     '        self.setFixedSize(92, 84); self.setCursor(Qt.PointingHandCursor); self.setToolTip(name)\n'
                                     '    def mousePressEvent(self, e):\n'
                                     '        if e.button() == Qt.LeftButton: self.clicked.emit(self.curve)\n'
                                     '    def paintEvent(self, e):\n'
                                     '        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)\n'
                                     '        p.fillRect(self.rect(), QColor(UI["ui_input"]))\n'
                                     '        p.setPen(QPen(QColor(UI["ui_accent"]) if self.selected else QColor("#3a3a40"), 2 if self.selected else 1))\n'
                                     '        p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)\n'
                                     '        r = QRectF(self.rect()).adjusted(10, 10, -10, -24)\n'
                                     '        def mp(x, y): return QPointF(r.left() + x * r.width(), r.bottom() - (y + 0.4) / 1.8 * r.height())\n'
                                     '        path = QPainterPath(mp(0, 0))\n'
                                     '        for x, y in bezier_points(self.curve)[1:]: path.lineTo(mp(x, y))\n'
                                     '        p.setPen(QPen(QColor(UI["ui_accent"]), 2.2)); p.drawPath(path)\n'
                                     '        p.setPen(QColor("#9aa0aa")); f = QFont(p.font()); f.setPointSize(max(7, f.pointSize() - 2)); p.setFont(f)\n'
                                     '        p.drawText(QRectF(0, self.height() - 22, self.width(), 20), Qt.AlignCenter, self.name)\n'}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v12"
try: sys.stdout.reconfigure(errors="replace")
except Exception: pass


def norm_hash(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
def path_of(rel): return os.path.join(HERE, *rel.split("/"))
def read(rel):
    p = path_of(rel)
    return open(p, "rb").read() if os.path.exists(p) else None
def say(msg=""): print(msg, flush=True)


def edited_text(rel, raw):
    """New bytes for a text-edited file. Raises ValueError if an expected text is not found exactly once."""
    info = EDITS[rel]
    text = raw.decode("utf-8"); crlf = "\r\n" in text; t = text.replace("\r\n", "\n")
    for old, new in info["edits"]:
        n = t.count(old)
        if n != 1: raise ValueError("%s: expected the patch text exactly once, found %d times" % (rel, n))
        t = t.replace(old, new, 1)
    return (t.replace("\n", "\r\n") if crlf else t).encode("utf-8")


def plan():
    """Work out what happens to every file. Nothing is written here."""
    rows, outputs = [], {}
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        cur = read(rel)
        if cur is None:
            rows.append((rel, "missing", "file not found: install the previous update first")); continue
        if norm_hash(cur) == info["new"]:
            rows.append((rel, "same", "already up to date")); continue
        if norm_hash(cur) != info["base"]:
            rows.append((rel, "edited", "differs from the version this patch was made for")); continue
        try:
            outputs[rel] = edited_text(rel, cur) if rel in EDITS else info["content"].encode("utf-8")
            rows.append((rel, "ok", "will be updated"))
        except ValueError as ex:
            rows.append((rel, "edited", str(ex)))
    for rel, src in NEW_FILES.items():
        cur = read(rel)
        if cur is None: rows.append((rel, "new", "will be created")); outputs[rel] = src.encode("utf-8")
        elif cur.decode("utf-8", "replace") == src: rows.append((rel, "same", "already up to date"))
        else: rows.append((rel, "edited", "already exists and differs from this patch"))
    return rows, outputs


def import_ok():
    code = "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; import minicut.app"
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=180)
        return r.returncode == 0, (r.stderr or r.stdout)[-1500:]
    except Exception as ex: return False, str(ex)


def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    ds = sorted(d for d in os.listdir(BACKUP_ROOT) if os.path.exists(os.path.join(BACKUP_ROOT, d, "MANIFEST.json")))
    return os.path.join(BACKUP_ROOT, ds[-1]) if ds else None


def revert(bdir):
    man = json.load(open(os.path.join(bdir, "MANIFEST.json"), encoding="utf-8"))
    for rel in man["replaced"]: shutil.copy2(os.path.join(bdir, *rel.split("/")), path_of(rel))
    for rel in man["created"]:
        if os.path.exists(path_of(rel)): os.remove(path_of(rel))
    say("Restored %d file(s), removed %d new file(s) from %s" % (len(man["replaced"]), len(man["created"]), bdir))


def main():
    if not os.path.isfile(path_of("minicut/app.py")):
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v12.py in the MiniCut folder (next to file.py) and run it again."); return 2
    if "--revert" in sys.argv:
        b = latest_backup()
        if not b: say("No backup found in _patch_backup/."); return 1
        revert(b); return 0
    rows, outputs = plan()
    say("MiniCut update: proxy bar, proxy settings, node page\n")
    for rel, st, note in rows: say("  %-40s %s" % (rel, note))
    say()
    if "--check" in sys.argv: return 0
    if all(st == "same" for _, st, _ in rows): say("Nothing to do: the update is already installed."); return 0
    if any(st == "missing" for _, st, _ in rows):
        say("STOPPED. A required file is missing:\n  " + "\n  ".join(rel for rel, st, _ in rows if st == "missing") +
            "\nInstall the previous update (apply_perf_gpu_patch_v11.py) first."); return 3
    bad = [rel for rel, st, _ in rows if st == "edited"]
    if bad and "--force" not in sys.argv:
        say("STOPPED. These files are not in the state this patch expects:\n  " + "\n  ".join(bad) +
            "\nIf the previous update is not installed yet, install it first.\n"
            "Otherwise your edits would be overwritten (they are backed up first). Run with --force to continue anyway.")
        return 3
    if bad:
        for rel in bad:
            try:
                if rel in EDITS: outputs[rel] = edited_text(rel, read(rel))
                elif rel in REPLACE: outputs[rel] = REPLACE[rel]["content"].encode("utf-8")
            except ValueError as ex: say("STOPPED: %s" % ex); return 3
    base_ok, _ = import_ok()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); bdir = os.path.join(BACKUP_ROOT, stamp); replaced, created = [], []
    os.makedirs(bdir, exist_ok=True)
    for rel in outputs:
        cur = path_of(rel)
        if os.path.exists(cur):
            dst = os.path.join(bdir, *rel.split("/")); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(cur, dst); replaced.append(rel)
        else: created.append(rel)
    json.dump({"patch": PATCH_NAME, "created": created, "replaced": replaced}, open(os.path.join(bdir, "MANIFEST.json"), "w", encoding="utf-8"), indent=1)
    try:
        for rel, data in outputs.items():
            p = path_of(rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f: f.write(data)
            if rel.endswith(".py"): py_compile.compile(p, doraise=True)
    except Exception as ex:
        say("ERROR while writing files: %s\nRestoring the backup ..." % ex); revert(bdir); return 1
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        if norm_hash(read(rel)) != info["new"]:
            say("ERROR: %s did not come out as expected, restoring the backup." % rel); revert(bdir); return 1
    ok, err = import_ok()
    if base_ok and not ok:
        say("The program no longer imports after the update, restoring the backup.\n" + err); revert(bdir); return 1
    for sub in ("minicut/render", "minicut/workspace", "minicut/shared"):
        shutil.rmtree(os.path.join(path_of(sub), "__pycache__"), ignore_errors=True)
    say("Done. %d file(s) updated, %d created.  Backup: %s" % (len(replaced), len(created), bdir))
    say("Start MiniCut as usual (Run_MiniCut.bat). Node page: pick a media on the left to edit its nodes.")
    say("To undo:  python apply_perf_gpu_patch_v12.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

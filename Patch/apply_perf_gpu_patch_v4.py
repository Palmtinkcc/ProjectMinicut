#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 4: PROXY BAR, PROXY SETTINGS, NODE PAGE REDESIGN
=====================================================================
Install AFTER apply_perf_gpu_patch_v3.py.

  * Timeline: a yellow bar under the ruler marks the parts of video clips whose proxy is ready (like CapCut).
  * Settings -> General: proxy size (360 / 540 / 720 p), proxy quality, the size of the proxy cache and a button
    to clear it.
  * Node page, rebuilt to be simpler:
      - left column: the list of media (clips). Pick one and the canvas shows only that media's nodes
        (plus the nodes that work on all media). New nodes are added to the chosen media.
      - the "how to use" text is now a "?" button.
      - the preview on the right can be zoomed (wheel, Fit / 100% / 200%), panned (drag) and expanded.
      - toolbar: Undo, Redo, Fit, Mute, Duplicate, Delete, Nodes on / off.
      - Ctrl+Z / Ctrl+Y undo / redo, Space play / pause inside the node page.
    The node data itself is unchanged (it is still stored in the project), so existing graphs keep working.

Files changed (the originals are backed up first):
  minicut/workspace/node_editor.py (replaced as a whole file),
  minicut/workspace/timeline.py, minicut/render/media.py, minicut/app.py, minicut/shared/core.py, minicut/shared/dialogs.py

    python apply_perf_gpu_patch_v4.py            install the update
    python apply_perf_gpu_patch_v4.py --check    only show what would change
    python apply_perf_gpu_patch_v4.py --revert   undo the last install
    python apply_perf_gpu_patch_v4.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': '0d8434c6430afbbb3d31500cd09d308d8e5df2b2227c096a3a2cb4fdb9e01f09',
                    'crlf': False,
                    'edits': [("CFG['encode_hw']=self.settings['encode_hw'];",
                               "CFG['encode_hw']=self.settings['encode_hw']; CFG['proxy_height']=self.settings['proxy_height']; "
                               "CFG['proxy_quality']=self.settings['proxy_quality'];"),
                              ('        d=SettingsDialog(self)\n        if d.exec():',
                               "        d=SettingsDialog(self); before=(self.settings['proxy_preview'], self.settings['proxy_height'], "
                               "self.settings['proxy_quality'])\n"
                               '        if d.exec():'),
                              ("            if self.pool.use_proxy != self.settings['proxy_preview']:\n"
                               "                with self.renderer._src_lock: self.pool.use_proxy = self.settings['proxy_preview']; self.pool.src.clear()\n",
                               "            now = (self.settings['proxy_preview'], self.settings['proxy_height'], self.settings['proxy_quality'])\n"
                               "            CFG['proxy_height'] = self.settings['proxy_height']; CFG['proxy_quality'] = self.settings['proxy_quality']\n"
                               "            if now != before or self.pool.use_proxy != self.settings['proxy_preview']:\n"
                               "                with self.renderer._src_lock: self.pool.use_proxy = self.settings['proxy_preview']; self.pool.src.clear()\n")],
                    'new': 'a1ec3ef181c97ffdbce71dacbec083bfddbbc31cabf428a4649c61e15c6b9632'},
 'minicut/render/media.py': {'base': 'a445f43b3410efcc8cad9c22dce83a0f103869e0eeabdc405d8025e7a3eff355',
                             'crlf': False,
                             'edits': [('("%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime)))',
                                        '("%s|%d|%d|%s|%s" % (os.path.abspath(path), st.st_size, int(st.st_mtime), CFG.get("proxy_height", PROXY_HEIGHT), '
                                        'CFG.get("proxy_quality", 23)))'),
                                       ('% PROXY_HEIGHT,', '% int(CFG.get("proxy_height", PROXY_HEIGHT)),'),
                                       ('"-crf", "23"', '"-crf", str(int(CFG.get("proxy_quality", 23)))')],
                             'new': '9e9a5105288b70249738ec1373c7b1d62e922091d1a973c59960fceafe4eccf7'},
 'minicut/shared/core.py': {'base': 'bc02961af54c514d2fcf2a8cc989b00d6631139dd2be8fbb51356ead6764bd19',
                            'crlf': False,
                            'edits': [('"encode_hw": "auto", "proxy_preview": True,',
                                       '"encode_hw": "auto", "proxy_preview": True, "proxy_height": 540, "proxy_quality": 23,')],
                            'new': '34ec108286f37bcb9d4ce63dcdc6e548d2b2fb09112a37225f73e5d88fca43c2'},
 'minicut/shared/dialogs.py': {'base': '2d78634ae1f78ac77a0a6784ec0bb56d2d8751580f4c57c2c23764c49bb74df8',
                               'crlf': False,
                               'edits': [('        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl); '
                                          'form.addRow("", self.proxy_cb)\n',
                                          '        self.p_h = QComboBox(); [self.p_h.addItem("%dp" % v, v) for v in (360, 540, 720)]; '
                                          'self.p_h.setCurrentIndex(max(0, self.p_h.findData(int(s["proxy_height"]))))\n'
                                          '        self.p_q = QComboBox(); [self.p_q.addItem(l, v) for l, v in (("High quality (bigger files)", 18), '
                                          '("Normal", 23), ("Small files", 28))]; self.p_q.setCurrentIndex(max(0, '
                                          'self.p_q.findData(int(s["proxy_quality"]))))\n'
                                          '        self.p_size = QLabel(""); self.p_size.setObjectName("Dim"); self.p_size.setWordWrap(True)\n'
                                          '        pb = QPushButton("Clear proxy cache"); pb.setToolTip("Delete all proxy files. They are rebuilt when '
                                          'needed."); pb.clicked.connect(self.clear_proxies)\n'
                                          '        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl); '
                                          'form.addRow("", self.proxy_cb)\n'
                                          '        form.addRow("Proxy size", self.p_h); form.addRow("Proxy quality", self.p_q); form.addRow("Proxy cache", '
                                          'self.p_size); form.addRow("", pb)\n'
                                          '        self.refresh_proxy_size()\n'),
                                         ('    def check_gpu(self):\n',
                                          '    def refresh_proxy_size(self):\n'
                                          '        d = os.path.join(APP_DIR, "proxies"); total = 0; n = 0\n'
                                          '        if os.path.isdir(d):\n'
                                          '            for f in os.listdir(d):\n'
                                          '                try: total += os.path.getsize(os.path.join(d, f)); n += 1\n'
                                          '                except OSError: pass\n'
                                          '        self.p_size.setText("%d file(s), %.1f MB" % (n, total / 1048576.0))\n'
                                          '    def clear_proxies(self):\n'
                                          '        d = os.path.join(APP_DIR, "proxies")\n'
                                          '        # Drop the open videos first, so the files are not held open by the preview.\n'
                                          '        with self.app.renderer._src_lock: self.app.pool.src.clear()\n'
                                          '        self.app.renderer.clear_preview_cache()\n'
                                          '        if os.path.isdir(d):\n'
                                          '            for f in os.listdir(d):\n'
                                          '                try: os.remove(os.path.join(d, f))\n'
                                          '                except OSError: pass\n'
                                          '        self.refresh_proxy_size()\n'
                                          '    def check_gpu(self):\n'),
                                         ('s["proxy_preview"] = self.proxy_cb.isChecked()',
                                          's["proxy_preview"] = self.proxy_cb.isChecked(); s["proxy_height"] = int(self.p_h.currentData()); s["proxy_quality"] '
                                          '= int(self.p_q.currentData()); CFG["proxy_height"] = s["proxy_height"]; CFG["proxy_quality"] = s["proxy_quality"]')],
                               'new': 'af295ede714dac750483ffb21326f0efe6d942b5513e3f01922e122f5c1b66cf'},
 'minicut/workspace/timeline.py': {'base': '16c538ea21b317ead3700ab432b21ca6a174a3c658c332b89d9f53a6a80e658e',
                                   'crlf': False,
                                   'edits': [('from ..shared.widgets import *\n', 'from ..shared.widgets import *\nfrom ..render.media import proxy_ready\n'),
                                             ('    def paintEvent(self, e):\n'
                                              '        self._paint_core(e)\n'
                                              '        app = self.app\n'
                                              '        if not app.proj: return\n',
                                              '    def _proxy_states(self):\n'
                                              '        """Which video files have a finished proxy. Checked twice a second by a timer, never on every '
                                              'paint."""\n'
                                              '        if not hasattr(self, "_pxy_timer"):\n'
                                              '            self._pxy = {}; self._pxy_timer = QTimer(self); self._pxy_timer.setInterval(500)\n'
                                              '            self._pxy_timer.timeout.connect(self._proxy_poll); self._pxy_timer.start()\n'
                                              '        return self._pxy\n'
                                              '    def _proxy_poll(self):\n'
                                              '        P = self.app.proj\n'
                                              '        if not P or not getattr(self.app.pool, "use_proxy", False):\n'
                                              '            if self._pxy: self._pxy = {}; self.update()\n'
                                              '            return\n'
                                              '        new = {c["path"]: proxy_ready(c["path"]) is not None for c in P.clips if c.get("kind") == "video" and '
                                              'c.get("path")}\n'
                                              '        if new != self._pxy: self._pxy = new; self.update()\n'
                                              '    def _draw_proxy_bars(self):\n'
                                              '        """Yellow bar under the ruler for every video clip whose proxy is ready (like CapCut)."""\n'
                                              '        self._proxy_states(); P = self.app.proj\n'
                                              '        if not P or not self._pxy: return\n'
                                              '        p = QPainter(self); p.setPen(Qt.NoPen); p.setBrush(QColor("#f2c94c")); W = self.width()\n'
                                              '        for c in P.clips:\n'
                                              '            if c.get("kind") != "video" or not self._pxy.get(c.get("path")): continue\n'
                                              '            x0 = max(self.HEAD, self.t2x(c["start"])); x1 = min(W, self.t2x(c["start"] + c["dur"]))\n'
                                              '            if x1 > x0: p.drawRect(QRectF(x0, self.RULER - 5, x1 - x0, 3))\n'
                                              '        p.end()\n'
                                              '    def paintEvent(self, e):\n'
                                              '        self._paint_core(e)\n'
                                              '        app = self.app\n'
                                              '        if not app.proj: return\n'
                                              '        self._draw_proxy_bars()\n')],
                                   'new': 'f7a016c6e10d2ee20aaf6cc0932a68c5a06917f374448f12cd9b3573bdb0bdb4'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {'minicut/workspace/node_editor.py': {'base': 'abad81b1e85023f6c71528ac73c30a2c4845170332cac30c7bd384cc6407831a',
                                      'content': '"""Node page: a simple, Scratch-like node editor. Pick a media (clip) on the left to work on its nodes '
                                                 'only;\n'
                                                 'the preview on the right can be zoomed, panned and expanded."""\n'
                                                 'from ..shared.deps import *\n'
                                                 'from ..shared.icons import *\n'
                                                 'from ..shared.theme import *\n'
                                                 'from ..shared.core import *\n'
                                                 'from ..shared.widgets import *\n'
                                                 'from ..render.nodegraph import *\n'
                                                 '\n'
                                                 '\n'
                                                 'NODE_HELP = ("Drag a block from the list (or double-click it) into the canvas.\\n"\n'
                                                 '             "Drag from a round socket to another socket to connect.\\n\\n"\n'
                                                 '             "Choose a media on the left to edit only the nodes for that media. Nodes that work on all media '
                                                 'stay visible.\\n\\n"\n'
                                                 '             "Mouse: drag empty space = box select · middle button or Space = pan · wheel = zoom · right '
                                                 'click = menu.\\n"\n'
                                                 '             "Keys: Del delete · Ctrl+D duplicate · M mute · Ctrl+Z / Ctrl+Y undo / redo.")\n'
                                                 'KIND_NAMES = {"video": "Video", "image": "Image", "gif": "GIF", "text": "Text", "audio": "Audio", '
                                                 '"compound": "Compound"}\n'
                                                 '\n'
                                                 '\n'
                                                 'def node_choices(app, opts):\n'
                                                 '    P = app.proj\n'
                                                 '    if isinstance(opts, (list, tuple)): return list(opts)\n'
                                                 '    clips = [(c["id"], "%s" % c.get("name", "clip")) for c in (P.clips if P else [])]\n'
                                                 '    if opts == "clips@": return [("@target", "Target clip")] + clips\n'
                                                 '    if opts == "clips*": return [("*", "All clips")] + clips\n'
                                                 '    if opts == "props": return [(k, v[0]) for k, v in OUT_PROPS.items()]\n'
                                                 '    if opts == "fxparams": return [("%s:%s" % (t, key), "%s · %s" % (sp["title"], label)) for t, sp in '
                                                 'FX.items() for key, label, kind, *_ in sp["params"] if kind in ("float", "int")]\n'
                                                 '    if opts == "audiosrc":\n'
                                                 '        trk = [("track:" + t["id"], "Track: " + t["name"]) for t in (P.tracks if P else [])]\n'
                                                 '        return [("*", "All audio"), ("@target", "Target clip")] + trk + [("clip:" + i, "Clip: " + n) for i, '
                                                 'n in clips]\n'
                                                 '    return []\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodeSocket(QGraphicsEllipseItem):\n'
                                                 '    R = 6\n'
                                                 '    def __init__(self, node, idx, is_out):\n'
                                                 '        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R, node)\n'
                                                 '        self.node, self.idx, self.is_out = node, idx, is_out\n'
                                                 '        self.setBrush(QColor("#e8efff")); self.setPen(QPen(QColor(UI["ui_panel"]), 2)); self.setZValue(3)\n'
                                                 '        self.setCursor(Qt.CrossCursor); self.setAcceptHoverEvents(True)\n'
                                                 '    def hoverEnterEvent(self, e): self.setBrush(QColor(UI["ui_accent"]))\n'
                                                 '    def hoverLeaveEvent(self, e): self.setBrush(QColor("#e8efff"))\n'
                                                 '    def mousePressEvent(self, e):\n'
                                                 '        if e.button() == Qt.LeftButton: self.scene().begin_link(self); e.accept()\n'
                                                 '        else: e.ignore()\n'
                                                 '    def mouseMoveEvent(self, e): self.scene().drag_link(e.scenePos())\n'
                                                 '    def mouseReleaseEvent(self, e): self.scene().end_link(e.scenePos())\n'
                                                 '\n'
                                                 '\n'
                                                 'class LinkItem(QGraphicsPathItem):\n'
                                                 '    def __init__(self, a=None, b=None, rec=None):\n'
                                                 '        super().__init__(); self.a, self.b, self.rec = a, b, rec; self.end = None\n'
                                                 '        self.setFlag(QGraphicsItem.ItemIsSelectable, True); self.setZValue(0); '
                                                 'self.setAcceptedMouseButtons(Qt.LeftButton)\n'
                                                 '        self.update_path()\n'
                                                 '    def shape(self):\n'
                                                 '        st = QPainterPathStroker(); st.setWidth(12); return st.createStroke(self.path())\n'
                                                 '    def update_path(self):\n'
                                                 '        p0 = self.a.scenePos() if self.a else self.end; p1 = self.b.scenePos() if self.b else self.end\n'
                                                 '        if p0 is None or p1 is None: return\n'
                                                 '        dx = max(50.0, abs(p1.x() - p0.x()) / 2); path = QPainterPath(p0)\n'
                                                 '        path.cubicTo(QPointF(p0.x() + dx, p0.y()), QPointF(p1.x() - dx, p1.y()), p1); self.setPath(path)\n'
                                                 '    def paint(self, p, opt, w=None):\n'
                                                 '        sel = self.isSelected()\n'
                                                 '        p.setRenderHint(QPainter.Antialiasing)\n'
                                                 '        p.setPen(QPen(QColor(UI["ui_accent"] if sel else "#7d8fb3"), 3 if sel else 2.2)); '
                                                 'p.setBrush(Qt.NoBrush); p.drawPath(self.path())\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodeItem(QGraphicsItem):\n'
                                                 '    W, HEAD, ROW = 220, 28, 26\n'
                                                 '    def __init__(self, scene, d):\n'
                                                 '        super().__init__(); self.sc = scene; self.d = d; self.spec = NODE_TYPES[d["type"]]\n'
                                                 '        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | '
                                                 'QGraphicsItem.ItemSendsGeometryChanges); self.setZValue(1)\n'
                                                 '        self.links = []; self.in_socks = []; self.out_socks = []; self.in_spins = []; self.readouts = []; '
                                                 'self.H = 60\n'
                                                 '        self._build(); self.setPos(d.get("x", 0), d.get("y", 0))\n'
                                                 '    def boundingRect(self): return QRectF(-8, -8, self.W + 16, self.H + 16)\n'
                                                 '    def _spin(self, v, cb):\n'
                                                 '        s = QDoubleSpinBox(); s.setObjectName("PropSpin"); s.setRange(-1e6, 1e6); s.setDecimals(2); '
                                                 's.setSingleStep(0.1); s.setKeyboardTracking(False)\n'
                                                 '        s.setValue(float(v)); s.setFixedSize(72, 20); s.setAlignment(Qt.AlignRight); '
                                                 's.valueChanged.connect(cb); return s\n'
                                                 '    def _set(self, k, v):\n'
                                                 '        self.sc.begin_edit(False); self.d["p"][k] = v; self.sc.touched()\n'
                                                 '    def _build(self):\n'
                                                 '        sp = self.spec; ins, outs = sp["ins"], sp["outs"]; sink = sp["sink"] is not None; rows = '
                                                 'max(len(ins), len(outs))\n'
                                                 '        box = QWidget(); box.setAttribute(Qt.WA_TranslucentBackground); '
                                                 'box.setStyleSheet("QLabel{background:transparent;}")\n'
                                                 '        lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)\n'
                                                 '        for i in range(rows):\n'
                                                 '            r = QWidget(); r.setFixedSize(self.W, self.ROW); h = QHBoxLayout(r); h.setContentsMargins(12, 2, '
                                                 '12, 2); h.setSpacing(6)\n'
                                                 '            if i < len(ins):\n'
                                                 '                h.addWidget(QLabel(ins[i][0]))\n'
                                                 '                if not sink:\n'
                                                 '                    k = "i%d" % i; s = self._spin(self.d["p"].get(k, ins[i][1]), lambda v, k=k: self._set(k, '
                                                 'v)); h.addWidget(s); self.in_spins.append(s)\n'
                                                 '                else: self.in_spins.append(None)\n'
                                                 '            h.addStretch()\n'
                                                 '            if i < len(outs):\n'
                                                 '                ro = QLabel(outs[i]); ro.setAlignment(Qt.AlignRight | Qt.AlignVCenter); h.addWidget(ro); '
                                                 'self.readouts.append(ro)\n'
                                                 '            lay.addWidget(r)\n'
                                                 '        for key, label, kind, dflt, opts in sp["params"]:\n'
                                                 '            r = QWidget(); r.setFixedSize(self.W, self.ROW); h = QHBoxLayout(r); h.setContentsMargins(12, 2, '
                                                 '12, 2); h.setSpacing(6)\n'
                                                 '            h.addWidget(QLabel(label)); cur = self.d["p"].get(key, dflt)\n'
                                                 '            if kind == "choice":\n'
                                                 '                w = QComboBox(); w.setFixedHeight(20)\n'
                                                 '                for val, lab in node_choices(self.sc.app, opts): w.addItem(lab, val)\n'
                                                 '                ix = w.findData(cur)\n'
                                                 '                if ix < 0: w.addItem("(missing)", cur); ix = w.count() - 1\n'
                                                 '                w.setCurrentIndex(ix); w.currentIndexChanged.connect(lambda _, w=w, key=key: self._set(key, '
                                                 'w.currentData()))\n'
                                                 '                h.addWidget(w, 1)\n'
                                                 '            elif kind == "bool":\n'
                                                 '                w = QCheckBox(); w.setChecked(bool(cur)); w.toggled.connect(lambda v, key=key: '
                                                 'self._set(key, bool(v))); h.addStretch(); h.addWidget(w)\n'
                                                 '            else:\n'
                                                 '                w = self._spin(cur, lambda v, key=key: self._set(key, v)); h.addStretch(); h.addWidget(w)\n'
                                                 '            lay.addWidget(r)\n'
                                                 '        total = (rows + len(sp["params"])) * self.ROW; box.setFixedSize(self.W, max(total, 1)); self.box = '
                                                 'box\n'
                                                 '        self.proxy = QGraphicsProxyWidget(self); self.proxy.setWidget(box); self.proxy.setPos(0, self.HEAD)\n'
                                                 '        self.H = self.HEAD + total + 8\n'
                                                 '        for i in range(len(ins)):\n'
                                                 '            s = NodeSocket(self, i, False); s.setPos(0, self.HEAD + self.ROW * i + self.ROW / 2); '
                                                 'self.in_socks.append(s)\n'
                                                 '        for j in range(len(outs)):\n'
                                                 '            s = NodeSocket(self, j, True); s.setPos(self.W, self.HEAD + self.ROW * j + self.ROW / 2); '
                                                 'self.out_socks.append(s)\n'
                                                 '    def refresh_inputs(self, linked):\n'
                                                 '        for i, s in enumerate(self.in_spins):\n'
                                                 '            if s is not None: s.setVisible(i not in linked)\n'
                                                 '    def paint(self, p, opt, w=None):\n'
                                                 '        p.setRenderHint(QPainter.Antialiasing); r = QRectF(0, 0, self.W, self.H); muted = '
                                                 'bool(self.d["p"].get("mute"))\n'
                                                 '        body = QPainterPath(); body.addRoundedRect(r, 10, 10)\n'
                                                 '        p.fillPath(body, QColor(UI["ui_panel"]))\n'
                                                 '        col = QColor(NODE_CATS.get(self.spec["cat"], "#555"))\n'
                                                 '        if muted: col.setAlpha(80)\n'
                                                 '        p.save(); p.setClipPath(body); p.fillRect(QRectF(0, 0, self.W, self.HEAD), col); p.restore()\n'
                                                 '        p.setPen(QColor("#ffffff") if not muted else QColor(255, 255, 255, 130)); f = QFont(p.font()); '
                                                 'f.setBold(True); f.setPointSize(max(8, f.pointSize())); p.setFont(f)\n'
                                                 '        p.drawText(QRectF(12, 0, self.W - 24, self.HEAD), Qt.AlignVCenter | Qt.AlignLeft, self.spec["title"] '
                                                 '+ ("  (muted)" if muted else ""))\n'
                                                 '        if self.isSelected(): p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(UI["ui_accent"]), 2)); '
                                                 'p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)\n'
                                                 '    def itemChange(self, change, value):\n'
                                                 '        if change == QGraphicsItem.ItemPositionHasChanged:\n'
                                                 '            p = self.pos(); self.d["x"], self.d["y"] = round(p.x(), 1), round(p.y(), 1)\n'
                                                 '            for l in self.links: l.update_path()\n'
                                                 '        return super().itemChange(change, value)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodeScene(QGraphicsScene):\n'
                                                 '    changed = Signal()\n'
                                                 '    def __init__(self, app):\n'
                                                 '        super().__init__(); self.app = app; self.graph = default_graph(); self.items_by_id = {}; '
                                                 'self.link_items = []\n'
                                                 '        self._tmp = None; self._from = None; self.on_edit = None; self.loading = False; self.filter_clip = '
                                                 'None\n'
                                                 '    # ---- model <-> items ----\n'
                                                 '    def load(self, graph):\n'
                                                 '        self.loading = True; self.clear(); self.items_by_id = {}; self.link_items = []; self._tmp = None; '
                                                 'self._from = None\n'
                                                 '        self.graph = graph; graph.setdefault("nodes", []); graph.setdefault("links", []); '
                                                 'graph.setdefault("on", True)\n'
                                                 '        for d in list(graph["nodes"]):\n'
                                                 '            if d.get("type") in NODE_TYPES:\n'
                                                 '                d.setdefault("p", {}); self.items_by_id[d["id"]] = NodeItem(self, d); '
                                                 'self.addItem(self.items_by_id[d["id"]])\n'
                                                 '            else: graph["nodes"].remove(d)\n'
                                                 '        for rec in list(graph["links"]):\n'
                                                 '            a, b = self.items_by_id.get(rec.get("from")), self.items_by_id.get(rec.get("to"))\n'
                                                 '            if a is None or b is None or rec.get("fo", 0) >= len(a.out_socks) or rec.get("ti", 0) >= '
                                                 'len(b.in_socks): graph["links"].remove(rec); continue\n'
                                                 '            self._add_link_item(a.out_socks[rec["fo"]], b.in_socks[rec["ti"]], rec)\n'
                                                 '        self._refresh_all(); self._apply_filter(); self.loading = False\n'
                                                 '    # ---- media filter: show only the nodes of the chosen media (plus nodes that work on every media) ----\n'
                                                 '    def set_filter(self, cid):\n'
                                                 '        self.filter_clip = cid; self._apply_filter()\n'
                                                 '    def _visible(self, d):\n'
                                                 '        if self.filter_clip is None: return True\n'
                                                 '        return d.get("p", {}).get("clip") in (None, "*", "@target", self.filter_clip)\n'
                                                 '    def _apply_filter(self):\n'
                                                 '        for it in self.items_by_id.values(): it.setVisible(self._visible(it.d))\n'
                                                 '        for li in self.link_items: li.setVisible(li.a.node.isVisible() and li.b.node.isVisible())\n'
                                                 '    def _linked_inputs(self, node): return {r["ti"] for r in self.graph["links"] if r["to"] == '
                                                 'node.d["id"]}\n'
                                                 '    def _refresh_all(self):\n'
                                                 '        for n in self.items_by_id.values(): n.refresh_inputs(self._linked_inputs(n))\n'
                                                 '    def _add_link_item(self, out_s, in_s, rec):\n'
                                                 '        li = LinkItem(out_s, in_s, rec); self.addItem(li); self.link_items.append(li); '
                                                 'out_s.node.links.append(li); in_s.node.links.append(li); return li\n'
                                                 '    def begin_edit(self, force=True):\n'
                                                 '        if self.on_edit and not self.loading: self.on_edit(force)\n'
                                                 '    def touched(self):\n'
                                                 '        if not self.loading: self.changed.emit()\n'
                                                 '    def new_node_dict(self, typ, pos, sel_clip=None):\n'
                                                 '        sp = NODE_TYPES[typ]; p = {}\n'
                                                 '        for key, label, kind, dflt, opts in sp["params"]: p[key] = dflt\n'
                                                 '        for i, (lab, dflt) in enumerate(sp["ins"]): p["i%d" % i] = dflt\n'
                                                 '        if sp["sink"] is not None and "clip" in p and sel_clip: p["clip"] = sel_clip\n'
                                                 '        return {"id": new_id(), "type": typ, "x": round(pos.x(), 1), "y": round(pos.y(), 1), "p": p}\n'
                                                 '    def add_node(self, typ, pos):\n'
                                                 '        if typ not in NODE_TYPES: return None\n'
                                                 '        self.begin_edit(); target = self.filter_clip if self.filter_clip is not None else self.app.sel\n'
                                                 '        d = self.new_node_dict(typ, pos, target); self.graph["nodes"].append(d)\n'
                                                 '        it = NodeItem(self, d); self.addItem(it); self.items_by_id[d["id"]] = it; self.clearSelection(); '
                                                 'it.setSelected(True); self.touched(); return it\n'
                                                 '    def remove_node(self, it):\n'
                                                 '        nid = it.d["id"]\n'
                                                 '        for rec in [r for r in self.graph["links"] if r["from"] == nid or r["to"] == nid]: '
                                                 'self._drop_link(rec)\n'
                                                 '        self.removeItem(it); self.items_by_id.pop(nid, None)\n'
                                                 '        if it.d in self.graph["nodes"]: self.graph["nodes"].remove(it.d)\n'
                                                 '    def _drop_link(self, rec):\n'
                                                 '        for li in [l for l in self.link_items if l.rec is rec]:\n'
                                                 '            for n in (li.a.node, li.b.node):\n'
                                                 '                if li in n.links: n.links.remove(li)\n'
                                                 '            self.removeItem(li); self.link_items.remove(li)\n'
                                                 '        if rec in self.graph["links"]: self.graph["links"].remove(rec)\n'
                                                 '        self._refresh_all()\n'
                                                 '    def delete_selected(self):\n'
                                                 '        sel = list(self.selectedItems())\n'
                                                 '        if not sel: return\n'
                                                 '        self.begin_edit()\n'
                                                 '        for it in sel:\n'
                                                 '            if isinstance(it, LinkItem) and it.rec in self.graph["links"]: self._drop_link(it.rec)\n'
                                                 '        for it in sel:\n'
                                                 '            if isinstance(it, NodeItem) and it.d["id"] in self.items_by_id: self.remove_node(it)\n'
                                                 '        self.touched()\n'
                                                 '    def duplicate_selected(self):\n'
                                                 '        src = [i for i in self.selectedItems() if isinstance(i, NodeItem)]\n'
                                                 '        if not src: return\n'
                                                 '        self.begin_edit(); self.clearSelection()\n'
                                                 '        for it in src:\n'
                                                 '            d = copy.deepcopy(it.d); d["id"] = new_id(); d["x"] += 30; d["y"] += 30; '
                                                 'self.graph["nodes"].append(d)\n'
                                                 '            n = NodeItem(self, d); self.addItem(n); self.items_by_id[d["id"]] = n; n.setSelected(True)\n'
                                                 '        self._apply_filter(); self.touched()\n'
                                                 '    def toggle_mute(self):\n'
                                                 '        for it in [i for i in self.selectedItems() if isinstance(i, NodeItem)]:\n'
                                                 '            self.begin_edit(); it.d["p"]["mute"] = not it.d["p"].get("mute"); it.update()\n'
                                                 '        self.touched()\n'
                                                 '    # ---- wiring ----\n'
                                                 '    def _downstream(self, nid):\n'
                                                 '        seen = set(); todo = [nid]\n'
                                                 '        while todo:\n'
                                                 '            n = todo.pop()\n'
                                                 '            for r in self.graph["links"]:\n'
                                                 '                if r["from"] == n and r["to"] not in seen: seen.add(r["to"]); todo.append(r["to"])\n'
                                                 '        return seen\n'
                                                 '    def connect(self, out_s, in_s):\n'
                                                 '        a, b = out_s.node.d["id"], in_s.node.d["id"]\n'
                                                 '        if a == b or a in self._downstream(b):\n'
                                                 '            if hasattr(self.app, "toast"): self.app.toast.show_msg("That connection would create a loop")\n'
                                                 '            return False\n'
                                                 '        self.begin_edit()\n'
                                                 '        for rec in [r for r in self.graph["links"] if r["to"] == b and r["ti"] == in_s.idx]: '
                                                 'self._drop_link(rec)\n'
                                                 '        rec = {"from": a, "fo": out_s.idx, "to": b, "ti": in_s.idx}; self.graph["links"].append(rec)\n'
                                                 '        self._add_link_item(out_s, in_s, rec); self._refresh_all(); self._apply_filter(); self.touched(); '
                                                 'return True\n'
                                                 '    def begin_link(self, sock):\n'
                                                 '        start = sock\n'
                                                 '        if not sock.is_out:\n'
                                                 '            rec = next((r for r in self.graph["links"] if r["to"] == sock.node.d["id"] and r["ti"] == '
                                                 'sock.idx), None)\n'
                                                 '            if rec:      # pick up an existing wire and re-route it\n'
                                                 '                start = self.items_by_id[rec["from"]].out_socks[rec["fo"]]; self.begin_edit(); '
                                                 'self._drop_link(rec); self.touched()\n'
                                                 '        self._from = start; self._tmp = LinkItem(start if start.is_out else None, None if start.is_out else '
                                                 'start); self.addItem(self._tmp)\n'
                                                 '        self._tmp.end = start.scenePos(); self._tmp.update_path()\n'
                                                 '    def drag_link(self, pos):\n'
                                                 '        if self._tmp is not None: self._tmp.end = pos; self._tmp.update_path()\n'
                                                 '    def end_link(self, pos):\n'
                                                 '        if self._tmp is None: return\n'
                                                 '        src = self._from; self.removeItem(self._tmp); self._tmp = None; self._from = None\n'
                                                 '        tgt = next((i for i in self.items(QRectF(pos.x() - 12, pos.y() - 12, 24, 24)) if isinstance(i, '
                                                 'NodeSocket) and i.is_out != src.is_out and i.node is not src.node), None)\n'
                                                 '        if tgt is not None: self.connect(src, tgt) if src.is_out else self.connect(tgt, src)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodeView(QGraphicsView):\n'
                                                 '    def __init__(self, scene, page):\n'
                                                 '        super().__init__(scene); self.page = page; self._pan = None\n'
                                                 '        self.setRenderHint(QPainter.Antialiasing); self.setDragMode(QGraphicsView.RubberBandDrag); '
                                                 'self.setRubberBandSelectionMode(Qt.IntersectsItemShape)\n'
                                                 '        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse); '
                                                 'self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)\n'
                                                 '        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); '
                                                 'self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)\n'
                                                 '        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate); self.setFrameShape(QFrame.NoFrame); '
                                                 'self.setAcceptDrops(True)\n'
                                                 '        self.setFocusPolicy(Qt.StrongFocus); scene.setSceneRect(-6000, -6000, 12000, 12000); '
                                                 'self.centerOn(0, 0)\n'
                                                 '    def fit_all(self):\n'
                                                 '        vis = [i for i in self.scene().items() if isinstance(i, NodeItem) and i.isVisible()]\n'
                                                 '        self.resetTransform()\n'
                                                 '        if not vis: self.centerOn(0, 0); return\n'
                                                 '        rect = QRectF()\n'
                                                 '        for n in vis: rect = rect.united(n.sceneBoundingRect())\n'
                                                 '        self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)\n'
                                                 '        s = self.transform().m11()\n'
                                                 '        if s > 1.4: self.resetTransform(); self.scale(1.4, 1.4); self.centerOn(rect.center())\n'
                                                 '    def drawBackground(self, p, rect):\n'
                                                 '        p.fillRect(rect, QColor(UI["tl_bg"])); g = 24; col = QColor(255, 255, 255, 18); p.setPen(QPen(col, '
                                                 '1.5))\n'
                                                 '        x0 = int(math.floor(rect.left() / g)) * g; y0 = int(math.floor(rect.top() / g)) * g\n'
                                                 '        pts = [QPointF(x, y) for x in range(x0, int(rect.right()) + g, g) for y in range(y0, '
                                                 'int(rect.bottom()) + g, g)]\n'
                                                 '        p.drawPoints(QPolygonF(pts))\n'
                                                 '    def wheelEvent(self, e):\n'
                                                 '        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15; cur = self.transform().m11()\n'
                                                 '        if 0.25 <= cur * f <= 2.5: self.scale(f, f)\n'
                                                 '    def mousePressEvent(self, e):\n'
                                                 '        if e.button() == Qt.MiddleButton: self._pan = e.position(); self.setCursor(Qt.ClosedHandCursor); '
                                                 'return\n'
                                                 '        super().mousePressEvent(e)\n'
                                                 '    def mouseMoveEvent(self, e):\n'
                                                 '        if self._pan is not None:\n'
                                                 '            d = e.position() - self._pan; self._pan = e.position()\n'
                                                 '            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x())); '
                                                 'self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y())); return\n'
                                                 '        super().mouseMoveEvent(e)\n'
                                                 '    def mouseReleaseEvent(self, e):\n'
                                                 '        if e.button() == Qt.MiddleButton and self._pan is not None: self._pan = None; self.unsetCursor(); '
                                                 'return\n'
                                                 '        super().mouseReleaseEvent(e)\n'
                                                 '    def keyPressEvent(self, e):\n'
                                                 '        ctrl = bool(e.modifiers() & Qt.ControlModifier)\n'
                                                 '        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace): self.page.delete_selected(); return\n'
                                                 '        if e.key() == Qt.Key_D and ctrl: self.page.scene.duplicate_selected(); return\n'
                                                 '        if e.key() == Qt.Key_Z and ctrl: self.page.app.do_undo(); return\n'
                                                 '        if e.key() == Qt.Key_Y and ctrl: self.page.app.do_redo(); return\n'
                                                 '        if e.key() == Qt.Key_M: self.page.scene.toggle_mute(); return\n'
                                                 '        if e.key() == Qt.Key_Space: self.page.app.toggle_play(); return\n'
                                                 '        super().keyPressEvent(e)\n'
                                                 '    def contextMenuEvent(self, e):\n'
                                                 '        pos = self.mapToScene(e.pos()); it = self.itemAt(e.pos()); m = QMenu(self)\n'
                                                 '        node = it\n'
                                                 '        while node is not None and not isinstance(node, (NodeItem, LinkItem)): node = node.parentItem()\n'
                                                 '        if isinstance(node, NodeItem):\n'
                                                 '            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)\n'
                                                 '            m.addAction("Duplicate", self.page.scene.duplicate_selected); m.addAction("Mute / unmute", '
                                                 'self.page.scene.toggle_mute); m.addAction("Delete", self.page.delete_selected)\n'
                                                 '        elif isinstance(node, LinkItem):\n'
                                                 '            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)\n'
                                                 '            m.addAction("Delete connection", self.page.delete_selected)\n'
                                                 '        else:\n'
                                                 '            for cat in NODE_CATS:\n'
                                                 '                sub = m.addMenu(cat)\n'
                                                 '                for typ, sp in NODE_TYPES.items():\n'
                                                 '                    if sp["cat"] == cat: sub.addAction(sp["title"], lambda typ=typ: '
                                                 'self.page.scene.add_node(typ, pos))\n'
                                                 '        m.exec(e.globalPos())\n'
                                                 '    def dragEnterEvent(self, e):\n'
                                                 '        if e.mimeData().hasText() and e.mimeData().text().startswith("minicut-node:"): '
                                                 'e.acceptProposedAction()\n'
                                                 '    def dragMoveEvent(self, e): e.acceptProposedAction()\n'
                                                 '    def dropEvent(self, e):\n'
                                                 '        t = e.mimeData().text()\n'
                                                 '        if t.startswith("minicut-node:"): self.page.scene.add_node(t.split(":", 1)[1], '
                                                 'self.mapToScene(e.position().toPoint())); e.acceptProposedAction(); self.setFocus()\n'
                                                 '\n'
                                                 '\n'
                                                 'class MediaList(QListWidget):\n'
                                                 '    """Left column: the media (clips) of the project. Choosing one shows only that media\'s nodes."""\n'
                                                 '    picked = Signal(object)\n'
                                                 '    def __init__(self):\n'
                                                 '        super().__init__(); self.setObjectName("MediaList"); self.setMinimumWidth(170); '
                                                 'self.setFocusPolicy(Qt.NoFocus)\n'
                                                 '        self.currentItemChanged.connect(self._emit)\n'
                                                 '    def _emit(self, cur, prev):\n'
                                                 '        if cur is not None: self.picked.emit(cur.data(Qt.UserRole))\n'
                                                 '    def fill(self, clips, keep):\n'
                                                 '        self.blockSignals(True); self.clear()\n'
                                                 '        it = QListWidgetItem("All media (shared nodes)"); it.setData(Qt.UserRole, None); self.addItem(it)\n'
                                                 '        for c in clips:\n'
                                                 '            it = QListWidgetItem("%s  ·  %s" % (c.get("name", "clip"), KIND_NAMES.get(c.get("kind"), '
                                                 'c.get("kind", "")))); it.setData(Qt.UserRole, c["id"]); self.addItem(it)\n'
                                                 '        row = 0\n'
                                                 '        for i in range(self.count()):\n'
                                                 '            if self.item(i).data(Qt.UserRole) == keep: row = i\n'
                                                 '        self.setCurrentRow(row); self.blockSignals(False)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodePalette(QTreeWidget):\n'
                                                 '    def __init__(self):\n'
                                                 '        super().__init__(); self.setHeaderHidden(True); self.setDragEnabled(True); self.setIndentation(14); '
                                                 'self.setMinimumWidth(170)\n'
                                                 '        for cat in NODE_CATS:\n'
                                                 '            top = QTreeWidgetItem([cat]); top.setForeground(0, QColor(NODE_CATS[cat])); f = top.font(0); '
                                                 'f.setBold(True); top.setFont(0, f); self.addTopLevelItem(top)\n'
                                                 '            for typ, sp in NODE_TYPES.items():\n'
                                                 '                if sp["cat"] == cat: ch = QTreeWidgetItem([sp["title"]]); ch.setData(0, Qt.UserRole, typ); '
                                                 'top.addChild(ch)\n'
                                                 '            top.setExpanded(True)\n'
                                                 '    def startDrag(self, actions):\n'
                                                 '        it = self.currentItem(); t = it.data(0, Qt.UserRole) if it else None\n'
                                                 '        if not t: return\n'
                                                 '        md = QMimeData(); md.setText("minicut-node:" + t); dr = QDrag(self); dr.setMimeData(md); '
                                                 'dr.exec(Qt.CopyAction)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodePreview(QWidget):\n'
                                                 '    """Preview with zoom (wheel or buttons), pan (drag) and double-click to fit again."""\n'
                                                 '    def __init__(self):\n'
                                                 '        super().__init__(); self.img = None; self.zoom = None; self.pan = QPointF(0, 0); self._drag = None\n'
                                                 '        self.setMinimumSize(240, 140); self.setCursor(Qt.OpenHandCursor)\n'
                                                 '    def set_img(self, img): self.img = img; self.update()\n'
                                                 '    def fit_scale(self):\n'
                                                 '        if self.img is None or self.img.isNull(): return 1.0\n'
                                                 '        return min(self.width() / max(1, self.img.width()), self.height() / max(1, self.img.height()))\n'
                                                 '    def cur_scale(self): return self.fit_scale() if self.zoom is None else self.zoom\n'
                                                 '    def set_zoom(self, z):\n'
                                                 '        self.zoom = None if z is None else max(0.1, min(8.0, z)); self.pan = QPointF(0, 0); self.update()\n'
                                                 '    def zoom_by(self, f): self.set_zoom(self.cur_scale() * f)\n'
                                                 '    def paintEvent(self, e):\n'
                                                 '        p = QPainter(self); p.fillRect(self.rect(), QColor(UI["vp_bg"]))\n'
                                                 '        if self.img is None or self.img.isNull():\n'
                                                 '            p.setPen(QColor("#6b7a99")); p.drawText(self.rect(), Qt.AlignCenter, "No preview yet"); return\n'
                                                 '        s = self.cur_scale(); w, h = self.img.width() * s, self.img.height() * s\n'
                                                 '        r = QRectF((self.width() - w) / 2 + self.pan.x(), (self.height() - h) / 2 + self.pan.y(), w, h)\n'
                                                 '        p.setRenderHint(QPainter.SmoothPixmapTransform, True); p.drawImage(r, self.img)\n'
                                                 '    def wheelEvent(self, e): self.zoom_by(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)\n'
                                                 '    def mousePressEvent(self, e):\n'
                                                 '        if e.button() == Qt.LeftButton: self._drag = e.position(); self.setCursor(Qt.ClosedHandCursor)\n'
                                                 '    def mouseMoveEvent(self, e):\n'
                                                 '        if self._drag is not None:\n'
                                                 '            d = e.position() - self._drag; self._drag = e.position(); self.pan = self.pan + d; '
                                                 'self.update()\n'
                                                 '    def mouseReleaseEvent(self, e): self._drag = None; self.setCursor(Qt.OpenHandCursor)\n'
                                                 '    def mouseDoubleClickEvent(self, e): self.set_zoom(None)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodePage(QWidget):\n'
                                                 '    def __init__(self, app):\n'
                                                 '        super().__init__(); self.app = app; self._pid = None; self._cp_t = 0.0; self._last_img = None\n'
                                                 '        self.media_id = None; self._chosen = False\n'
                                                 '        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 10); root.setSpacing(8)\n'
                                                 '        top = QHBoxLayout(); top.setSpacing(6)\n'
                                                 '        back = QPushButton("Editor"); back.setIcon(app_icon("angle_left")); '
                                                 'back.clicked.connect(app.close_nodes); top.addWidget(back)\n'
                                                 '        t = QLabel("Nodes"); t.setObjectName("Logo"); top.addWidget(t); self.plabel = QLabel(""); '
                                                 'self.plabel.setObjectName("ProjTitle"); top.addWidget(self.plabel); top.addStretch()\n'
                                                 '        self.en = QCheckBox("Nodes on"); self.en.setToolTip("Turn the whole graph off to compare with the '
                                                 'original clips"); self.en.toggled.connect(self.set_enabled); top.addWidget(self.en)\n'
                                                 '        for label, tip, cb in (("Undo", "Undo (Ctrl+Z)", lambda: self.app.do_undo()), ("Redo", "Redo '
                                                 '(Ctrl+Y)", lambda: self.app.do_redo()),\n'
                                                 '                               ("Fit", "Fit all visible nodes", lambda: self.view.fit_all()),\n'
                                                 '                               ("Mute", "Mute / unmute selected (M)", lambda: self.scene.toggle_mute()),\n'
                                                 '                               ("Duplicate", "Duplicate (Ctrl+D)", lambda: '
                                                 'self.scene.duplicate_selected()),\n'
                                                 '                               ("Delete", "Delete (Del)", self.delete_selected)):\n'
                                                 '            b = QPushButton(label); b.setToolTip(tip); b.clicked.connect(cb); top.addWidget(b)\n'
                                                 '        hb = QToolButton(); hb.setText("?"); hb.setToolTip(NODE_HELP); hb.setFocusPolicy(Qt.NoFocus); '
                                                 'top.addWidget(hb)\n'
                                                 '        root.addLayout(top)\n'
                                                 '        self.scene = NodeScene(app); self.scene.on_edit = self.checkpoint; '
                                                 'self.scene.changed.connect(self.on_graph_changed)\n'
                                                 '        self.view = NodeView(self.scene, self)\n'
                                                 '        self.media = MediaList(); self.media.picked.connect(self.set_media)\n'
                                                 '        self.palette = NodePalette(); self.palette.itemDoubleClicked.connect(self.add_from_palette)\n'
                                                 '        pv = QWidget(); pl = QVBoxLayout(pv); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(6)\n'
                                                 '        self.preview = NodePreview(); pl.addWidget(self.preview, 1)\n'
                                                 '        tr = QHBoxLayout(); tr.setSpacing(4)\n'
                                                 '        self.prev_b = tool("", "Previous frame", lambda: app.step(-1), icon="previous")\n'
                                                 '        self.play_b = tool("", "Play / Pause (Space)", app.toggle_play, icon="play", isize=20)\n'
                                                 '        self.next_b = tool("", "Next frame", lambda: app.step(1), icon="next")\n'
                                                 '        tr.addStretch(); [tr.addWidget(b) for b in (self.prev_b, self.play_b, self.next_b)]; '
                                                 'tr.addStretch()\n'
                                                 '        for lab, z in (("Fit", None), ("100%", 1.0), ("200%", 2.0)):\n'
                                                 '            zb = QPushButton(lab); zb.setToolTip("Preview zoom"); zb.clicked.connect(lambda _=False, z=z: '
                                                 'self.preview.set_zoom(z)); tr.addWidget(zb)\n'
                                                 '        self.exp_b = QPushButton("Expand"); self.exp_b.setCheckable(True); self.exp_b.setToolTip("Make the '
                                                 'preview bigger"); self.exp_b.toggled.connect(self.set_expanded); tr.addWidget(self.exp_b)\n'
                                                 '        pl.addLayout(tr)\n'
                                                 '        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, 1000); '
                                                 'self.seek.setFocusPolicy(Qt.NoFocus); self.seek.valueChanged.connect(self.on_seek); pl.addWidget(self.seek)\n'
                                                 '        self.time = QLabel(""); self.time.setObjectName("Dim"); self.time.setAlignment(Qt.AlignCenter); '
                                                 'pl.addWidget(self.time)\n'
                                                 '        ml = QLabel("Media  (pick one to edit its nodes)"); ml.setObjectName("H2"); pl.addWidget(ml)\n'
                                                 '        self.media.setMaximumHeight(190); pl.addWidget(self.media)\n'
                                                 '        self.body = QSplitter(Qt.Horizontal); self.body.addWidget(self.palette); '
                                                 'self.body.addWidget(self.view); self.body.addWidget(pv)\n'
                                                 '        self.body.setSizes([200, 740, 420]); self.body.setStretchFactor(0, 0); self.body.setStretchFactor(1, '
                                                 '1); self.body.setStretchFactor(2, 0)\n'
                                                 '        root.addWidget(self.body, 1)\n'
                                                 '        self.timer = QTimer(self); self.timer.setInterval(90); self.timer.timeout.connect(self.sync)\n'
                                                 '    # ---- model ----\n'
                                                 '    def reload(self):\n'
                                                 '        P = self.app.proj\n'
                                                 '        if P is None: return\n'
                                                 '        if not hasattr(P, "graph") or not isinstance(P.graph, dict): P.graph = default_graph()\n'
                                                 '        self._pid = id(P)\n'
                                                 '        ids = {c["id"] for c in P.clips}\n'
                                                 '        if self.media_id is not None and self.media_id not in ids: self.media_id = None\n'
                                                 '        if self.media_id is None and not self._chosen and self.app.sel in ids: self.media_id = self.app.sel\n'
                                                 '        self.scene.load(P.graph); self.scene.set_filter(self.media_id)\n'
                                                 '        self.media.fill(P.clips, self.media_id)\n'
                                                 '        self.en.blockSignals(True); self.en.setChecked(P.graph.get("on", True)); '
                                                 'self.en.blockSignals(False)\n'
                                                 '        self._update_title()\n'
                                                 '    def _update_title(self):\n'
                                                 '        P = self.app.proj\n'
                                                 '        if P is None: return\n'
                                                 '        c = next((c for c in P.clips if c["id"] == self.media_id), None)\n'
                                                 '        self.plabel.setText(P.name + ("  ·  " + c.get("name", "clip") if c else "  ·  all media"))\n'
                                                 '    def set_media(self, cid):\n'
                                                 '        self._chosen = True; self.media_id = cid; self.scene.set_filter(cid); self.view.fit_all(); '
                                                 'self._update_title()\n'
                                                 '    def set_expanded(self, v):\n'
                                                 '        self.body.setSizes([160, 380, 900] if v else [200, 740, 420])\n'
                                                 '    def checkpoint(self, force=True):\n'
                                                 '        now = time.monotonic()\n'
                                                 '        if (force or now - self._cp_t > 0.6) and self.app.proj: self.app.checkpoint()\n'
                                                 '        self._cp_t = now\n'
                                                 '    def on_graph_changed(self): self.app.graph_edited()\n'
                                                 '    def set_enabled(self, v):\n'
                                                 '        self.checkpoint(True); self.app.proj.graph["on"] = bool(v); self.app.graph_edited()\n'
                                                 '    def delete_selected(self): self.scene.delete_selected()\n'
                                                 '    def add_from_palette(self, it, col):\n'
                                                 '        typ = it.data(0, Qt.UserRole)\n'
                                                 '        if typ: self.scene.add_node(typ, self.view.mapToScene(self.view.viewport().rect().center()))\n'
                                                 '    def on_seek(self, v):\n'
                                                 '        if self.app.proj and not getattr(self, "_syncing", False): self.app.seek(self.app.proj.duration() * '
                                                 'v / 1000.0)\n'
                                                 '    # ---- live updates ----\n'
                                                 '    def showEvent(self, e):\n'
                                                 '        super().showEvent(e)\n'
                                                 '        if self.app.proj is not None: self.reload()\n'
                                                 '        self.timer.start()\n'
                                                 '    def hideEvent(self, e): super().hideEvent(e); self.timer.stop()\n'
                                                 '    def sync(self):\n'
                                                 '        a = self.app; P = a.proj\n'
                                                 '        if P is None or not self.isVisible(): return\n'
                                                 '        self._syncing = True\n'
                                                 '        dur = max(0.01, P.duration()); self.seek.setValue(int(max(0.0, min(1.0, a.t / dur)) * 1000)); '
                                                 'self._syncing = False\n'
                                                 '        self.time.setText(fmt_time(a.t, P.fps) + " / " + fmt_time(P.duration(), P.fps)); '
                                                 'set_play_icon(self.play_b, a.playing)\n'
                                                 '        img = getattr(a.viewport, "img", None) if hasattr(a, "viewport") else None\n'
                                                 '        if img is not self._last_img: self._last_img = img; self.preview.set_img(img)\n'
                                                 '        try:\n'
                                                 '            clip = next((c for c in P.clips if c["id"] == self.media_id), None) if self.media_id else None\n'
                                                 '            if clip is None: clip = a.sel_clip() or next((c for c in P.clips if c["kind"] in ("video", '
                                                 '"image", "gif", "text")), None)\n'
                                                 '            memo, err = node_debug(P, a.t, clip)\n'
                                                 '            for nid, it in self.scene.items_by_id.items():\n'
                                                 '                vals = memo.get(nid)\n'
                                                 '                for j, lab in enumerate(it.readouts):\n'
                                                 '                    base = it.spec["outs"][j]; lab.setText(base if vals is None or j >= len(vals) else "%s  '
                                                 '%.2f" % (base, vals[j]))\n'
                                                 '                if nid in err: it.setToolTip("This node is part of a loop or failed; its value was '
                                                 'ignored")\n'
                                                 '        except Exception as ex: print("[nodes] readout:", ex)\n'
                                                 '\n'
                                                 '\n'
                                                 'class NodesMixin:\n'
                                                 '    """Opening the node editor page."""\n'
                                                 '    def open_nodes(self):\n'
                                                 '        if not self.proj: return\n'
                                                 '        self.stop_play()\n'
                                                 '        if not hasattr(self, "nodes_page"): self.nodes_page = NodePage(self); '
                                                 'self.stack.addWidget(self.nodes_page)\n'
                                                 '        self.nodes_page.reload(); self.stack.setCurrentWidget(self.nodes_page); self.request_render()\n'
                                                 '    def close_nodes(self):\n'
                                                 '        if self.proj: self.stack.setCurrentWidget(self.editor); self.on_changed(insp=False)\n'
                                                 '    def in_nodes(self): return hasattr(self, "nodes_page") and self.stack.currentWidget() is '
                                                 'self.nodes_page\n'
                                                 '    def graph_edited(self):\n'
                                                 '        """The node graph changed: drop cached frames and re-render with the new graph."""\n'
                                                 '        if not self.proj: return\n'
                                                 '        self.renderer.clear_preview_cache(); self.request_render()\n',
                                      'new': 'a92573c96dbf9dd77275d1e8920865c919cdbd37fdd7eaa7c822214ef583c2bb'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v4"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v4.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v3.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v4.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

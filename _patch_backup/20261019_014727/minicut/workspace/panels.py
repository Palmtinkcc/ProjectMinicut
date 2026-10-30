"""Side panels: media list, preview controls, inspector (properties) and the mask editor."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.widgets import *
from ..render.renderer import *
from ..render.renderer import _mask_shape
from .viewport import *
from .effects_panel import EffectsPanel


class MaskCanvas(QWidget):
    def __init__(self, panel):
        super().__init__(); self.panel = panel; self.setMinimumHeight(170); self.bg = None; self.drag = None
    def frame_rect(self):
        aw, ah = self.panel.src_size; W, H = max(10, self.width() - 16), max(10, self.height() - 16)
        s = min(W / aw, H / ah); w, h = aw * s, ah * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.fillRect(self.rect(), QColor("#141416"))
        r = self.frame_rect()
        if self.bg is not None: p.drawImage(r, self.bg)
        else: p.fillRect(r, QColor("#2a2a2e"))
        sh = self.panel.shape(); ms = self.panel.ms()
        if sh == "None": return
        p.setPen(QPen(QColor("#22d3ee"), 1.6)); p.setBrush(QColor(34, 211, 238, 40))
        if sh in ("Split", "Filmstrip"):
            cx, cy = r.left() + ms["cx"] * r.width(), r.top() + ms["cy"] * r.height()
            th = math.radians(ms["rot"]); dx, dy = math.cos(th), math.sin(th); nx, ny = -dy, dx; L = r.width() + r.height()
            offs = [0] if sh == "Split" else [-ms["h"] * r.height() / 2, ms["h"] * r.height() / 2]
            p.setClipRect(r)
            for o in offs:
                p.drawLine(QPointF(cx + nx * o - dx * L, cy + ny * o - dy * L), QPointF(cx + nx * o + dx * L, cy + ny * o + dy * L))
            p.setClipping(False)
        else:
            poly = mask_polygon(sh, ms, r.width(), r.height())
            if poly is not None: p.drawPolygon(QPolygonF([QPointF(r.left() + x, r.top() + y) for x, y in poly]))
            if sh == "Custom":
                pts = ms.get("pts", [])
                p.setPen(QPen(QColor("#22d3ee"), 1.2))
                for i in range(len(pts) - 1):
                    p.drawLine(QPointF(r.left() + pts[i][0] * r.width(), r.top() + pts[i][1] * r.height()),
                               QPointF(r.left() + pts[i + 1][0] * r.width(), r.top() + pts[i + 1][1] * r.height()))
                p.setBrush(QColor("#ffffff")); p.setPen(QPen(QColor("#0e0e10"), 1))
                for x, y in pts: p.drawEllipse(QPointF(r.left() + x * r.width(), r.top() + y * r.height()), 4, 4)
        if sh != "Custom":
            p.setBrush(QColor("#ffffff")); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(r.left() + ms["cx"] * r.width(), r.top() + ms["cy"] * r.height()), 4, 4)
    def _norm(self, pos):
        r = self.frame_rect()
        return (min(1.0, max(0.0, (pos.x() - r.left()) / r.width())), min(1.0, max(0.0, (pos.y() - r.top()) / r.height())))
    def _near(self, pos):
        r = self.frame_rect()
        for i, (x, y) in enumerate(self.panel.ms().get("pts", [])):
            if abs(r.left() + x * r.width() - pos.x()) < 7 and abs(r.top() + y * r.height() - pos.y()) < 7: return i
        return None
    def mousePressEvent(self, e):
        pos = e.position(); sh = self.panel.shape()
        if sh == "None" or self.panel.app.sel_clip() is None: return
        if sh == "Custom":
            i = self._near(pos)
            if e.button() == Qt.RightButton:
                if i is not None: self.panel.edit(lambda ms, c: ms["pts"].pop(i))
                return
            if i is None:
                x, y = self._norm(pos); self.panel.edit(lambda ms, c: ms["pts"].append([x, y]))
                i = len(self.panel.ms()["pts"]) - 1
            self.drag = ("pt", i)
        else:
            ms = self.panel.ms(); x, y = self._norm(pos); self.drag = ("move", x - ms["cx"], y - ms["cy"])
    def mouseMoveEvent(self, e):
        if not self.drag: return
        x, y = self._norm(e.position())
        if self.drag[0] == "pt":
            i = self.drag[1]; self.panel.edit(lambda ms, c: ms["pts"].__setitem__(i, [x, y]))
        else:
            _, ox, oy = self.drag; self.panel.edit(lambda ms, c: ms.update(cx=x - ox, cy=y - oy))
    def mouseReleaseEvent(self, e): self.drag = None
    def wheelEvent(self, e):
        e.accept()
        if self.panel.shape() in ("None", "Custom"): return
        f = 1.08 if e.angleDelta().y() > 0 else 1 / 1.08
        self.panel.edit(lambda ms, c: ms.update(w=min(4.0, ms["w"] * f), h=min(4.0, ms["h"] * f)))


class MaskPanel(QWidget):
    ROWS = [("cx", "Position X", 0, 100, 100, "%"), ("cy", "Position Y", 0, 100, 100, "%"),
            ("w", "Width", 1, 300, 100, "%"), ("h", "Height", 1, 300, 100, "%"),
            ("rot", "Rotate", -180, 180, 1, "°"), ("round", "Round corners", 0, 100, 100, ""),
            ("feather", "Feather", 0, 100, 1, "")]
    def __init__(self, app, holder_fn=None):
        super().__init__(); self.app = app; self.holder_fn = holder_fn; self.cid = None; self.loading = False; self._before = None; self.src_size = (16, 9)
        self._ct = QTimer(self); self._ct.setSingleShot(True); self._ct.setInterval(450); self._ct.timeout.connect(self._commit)
        v = QVBoxLayout(self); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(8)
        grid = QGridLayout(); grid.setSpacing(6); self.btns = {}
        for i, name in enumerate(MASKS):
            b = QToolButton(); b.setText(name); b.setCheckable(True); b.setFixedHeight(30)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, n=name: self.set_shape(n)); grid.addWidget(b, i // 4, i % 4); self.btns[name] = b
        v.addLayout(grid)
        self.canvas = MaskCanvas(self); v.addWidget(self.canvas, 1)
        self.hint = QLabel(""); self.hint.setWordWrap(True); self.hint.setStyleSheet("color:#8a8a92;"); v.addWidget(self.hint)
        form = QGridLayout(); form.setHorizontalSpacing(8); form.setVerticalSpacing(6); self.sl = {}
        for r, (k, lab, lo, hi, sc, suf) in enumerate(self.ROWS):
            l = QLabel(lab); s = QSlider(Qt.Horizontal); s.setRange(lo, hi)
            val = QLabel("0"); val.setFixedWidth(44); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda x, k=k, sc=sc, suf=suf, val=val: self._slider(k, x, sc, suf, val))
            form.addWidget(l, r, 0); form.addWidget(s, r, 1); form.addWidget(val, r, 2); self.sl[k] = (s, sc, val, l)
        v.addLayout(form)
        row = QHBoxLayout(); self.inv = QCheckBox("Invert")
        self.inv.toggled.connect(lambda on: self.edit(lambda ms, c: ms.update(invert=bool(on))))
        rst = QPushButton("Reset"); rst.clicked.connect(self.reset)
        row.addWidget(self.inv); row.addStretch(1); row.addWidget(rst); v.addLayout(row)
        self._update_ui("None")
    def _h(self, c):
        """The dict that holds the mask: the clip itself (Mask tab) or e.g. the parameters of one effect (area blur)."""
        return c if (c is None or self.holder_fn is None) else self.holder_fn(c)
    def shape(self):
        h = self._h(self.app.sel_clip()); s = h.get("mask", "None") if h else "None"
        return s if s in MASKS else "None"
    def ms(self):
        h = self._h(self.app.sel_clip()); return _mask_shape(h) if h is not None else dict(MASK_DEFAULT)
    def edit(self, fn):
        h = self._h(self.app.sel_clip())
        if h is None or self.loading: return
        if self._before is None: self._before = self.app.begin()
        fn(_mask_shape(h), h); self._ct.start(); self._sync_sliders(h)
        self.app.request_render(); self.canvas.update()
    def _commit(self):
        if self._before is not None: self.app.commit(self._before); self._before = None
    def _slider(self, k, x, sc, suf, val):
        val.setText(f"{x}{suf}")
        if self.loading: return
        if k == "feather": self.edit(lambda ms, c: c.__setitem__("mask_feather", x))
        else: self.edit(lambda ms, c: ms.__setitem__(k, x / sc))
    def _sync_sliders(self, c):
        self.loading = True
        try:
            ms = _mask_shape(c)
            for k, (s, sc, val, l) in self.sl.items():
                s.setValue(int(round(c.get("mask_feather", 0) if k == "feather" else ms[k] * sc)))
            self.inv.setChecked(bool(ms["invert"]))
        finally: self.loading = False
    def set_shape(self, n):
        self.edit(lambda ms, c: c.__setitem__("mask", n)); self._update_ui(n)
    def reset(self):
        self.edit(lambda ms, c: (ms.clear(), ms.update(copy.deepcopy(MASK_DEFAULT)), c.__setitem__("mask_feather", 0)))
    def _update_ui(self, sh):
        for n, b in self.btns.items(): b.setChecked(n == sh)
        par = sh not in ("None", "Custom")
        vis = {"cx": par, "cy": par, "w": sh in ("Circle", "Rect", "Heart", "Star"),
               "h": sh in ("Circle", "Rect", "Heart", "Star", "Filmstrip"), "rot": par,
               "round": sh == "Rect", "feather": sh != "None"}
        for k, (s, sc, val, l) in self.sl.items():
            for w in (s, val, l): w.setVisible(vis[k])
        self.inv.setVisible(sh != "None")
        self.hint.setText("คลิกบนภาพเพื่อเพิ่มจุด • ลากจุดเพื่อย้าย • คลิกขวาที่จุดเพื่อลบ (ต้องมีอย่างน้อย 3 จุด)" if sh == "Custom"
                          else "" if sh == "None" else "ลากบนภาพเพื่อย้ายมาสก์ • หมุนลูกกลิ้งเมาส์เพื่อย่อ/ขยาย")
        self.canvas.update()
    def load(self, c, force=False):
        h = self._h(c); key = (c["id"] if c else None, id(h))
        if key == self.cid and not force: return
        self.cid = key
        if c and h is not None: self._sync_sliders(h); self._grab_bg(c)
        self._update_ui(self.shape())
    def follow(self, t):
        """The playhead moved: show the picture under the playhead in the mask editor (about every 50 ms at most)."""
        c = self.app.sel_clip()
        if not c or c["kind"] == "audio" or not self.isVisible(): return
        last = getattr(self, "_bg_key", None)
        if last is not None and last[0] == c["id"] and abs(last[1] - t) < 0.05: return
        self._bg_key = (c["id"], t); self._grab_bg(c, t); self.canvas.update()
    def _grab_bg(self, c, t=None):
        t = self.app.t if t is None else t
        self.canvas.bg = None; pj = self.app.proj; self.src_size = (pj.w, pj.h) if pj else (16, 9)
        try:
            r = self.app.renderer; src = r.pool.get(c)
            if src is None: return
            self.src_size = (max(1, src.w), max(1, src.h))
            with getattr(r, "_src_lock", threading.RLock()):
                img = src.frame(max(0.0, c["inp"] + (t - c["start"])) if c["kind"] != "image" else 0, .25)
            if img is not None: self.canvas.bg = np_to_qimage(img)
        except Exception as ex: print("mask bg:", ex)


def placeholder_icon(kind, w=112, h=64):
    pm = QPixmap(w, h); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen); p.setBrush(QColor("#16213a")); p.drawRoundedRect(0, 0, w, h, 8, 8)
    if kind == "audio":
        p.setPen(QPen(QColor("#5aa2ff"), 2.2, Qt.SolidLine, Qt.RoundCap))
        heights = [8, 14, 6, 22, 30, 15, 24, 11, 32, 18, 9, 25, 13, 29, 17, 7, 21, 12]
        cx = w / 2 - len(heights) * 3 / 2
        for i, hh in enumerate(heights): p.drawLine(QPointF(cx + i * 3, h / 2 - hh / 2), QPointF(cx + i * 3, h / 2 + hh / 2))
    else:
        nm = {"video": "video", "image": "image", "gif": "gif"}.get(kind)
        if nm:
            s = int(min(w, h) * 0.5); p.drawPixmap((w - s) // 2, (h - s) // 2, svg_pixmap(nm, "#5aa2ff", s))
        else:
            p.setPen(QColor("#5aa2ff")); f = p.font(); f.setPointSize(15); f.setBold(True); p.setFont(f)
            p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "?")
    p.end()
    return QIcon(pm)


def icon_from_image(img, w=112, h=64):
    pm = QPixmap(w, h); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath(); path.addRoundedRect(0, 0, w, h, 8, 8); p.setClipPath(path); p.fillRect(0, 0, w, h, QColor("#05080f"))
    s = min(w / img.width(), h / img.height()); iw, ih = img.width() * s, img.height() * s
    p.setRenderHint(QPainter.SmoothPixmapTransform); p.drawImage(QRectF((w - iw) / 2, (h - ih) / 2, iw, ih), img); p.end()
    return QIcon(pm)


def scan_folder(folder, depth=2, limit=600):
    out = []
    def rec(d, lv):
        try: entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except Exception: return
        for e in entries:
            if len(out) >= limit: return
            try:
                if e.is_dir(follow_symlinks=False):
                    if lv < depth and not e.name.startswith("."): rec(e.path, lv + 1)
                elif kind_of(e.name): out.append(e.path)
            except Exception: pass
    if folder and os.path.isdir(folder): rec(folder, 0)
    return out


class MediaList(QListWidget):
    files_dropped = Signal(list)
    def __init__(self):
        super().__init__(); self.setViewMode(QListView.IconMode); self.setIconSize(QSize(112, 64)); self.setGridSize(QSize(124, 100))
        self.setResizeMode(QListView.Adjust); self.setMovement(QListView.Static); self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection); self.setDragEnabled(True); self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop); self.setDefaultDropAction(Qt.CopyAction); self.setUniformItemSizes(True)
    def mimeTypes(self): return ["text/uri-list"]
    def mimeData(self, items):
        md = QMimeData(); md.setUrls([QUrl.fromLocalFile(i.data(Qt.UserRole)) for i in items]); return md
    def supportedDropActions(self): return Qt.CopyAction
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self: e.setDropAction(Qt.CopyAction); e.accept()
        else: e.ignore()
    def dragMoveEvent(self, e):
        if e.source() is not self: e.setDropAction(Qt.CopyAction); e.accept()
    def dropEvent(self, e):
        if e.source() is self: return
        self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]); e.accept()


class MediaPanel(Panel):
    def __init__(self, app):
        super().__init__("Media"); self.app = app
        self.head.addWidget(tool("Import", "Import media", app.import_dialog, icon="import"))
        folder_btn = tool("", "Choose asset folder (saved for every project)", self.choose_folder); folder_btn.setIcon(app_icon("folder_open")); self.head.addWidget(folder_btn)
        refresh_btn = tool("", "Refresh media list", self.reload); refresh_btn.setIcon(app_icon("refresh")); self.head.addWidget(refresh_btn)
        text_btn = tool("", "Add text", app.add_text); text_btn.setIcon(app_icon("text")); self.head.addWidget(text_btn)
        self.tabs = QTabBar(); self.tabs.addTab("Project"); self.tabs.addTab("Asset folder"); self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(lambda *_: self.reload()); self.body.addWidget(self.tabs)
        row = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Search…")
        self.filter = QComboBox(); self.filter.addItems(["All", "Video", "Image", "GIF", "Audio"])
        self.search.textChanged.connect(self.reload); self.filter.currentIndexChanged.connect(self.reload)
        row.addWidget(self.search, 1); row.addWidget(self.filter); self.body.addLayout(row)
        self.folder_lbl = QLabel(); self.folder_lbl.setObjectName("Dim"); self.body.addWidget(self.folder_lbl)
        self.list = MediaList(); self.body.addWidget(self.list, 1)
        self.list.files_dropped.connect(app.import_files)
        self.list.itemDoubleClicked.connect(lambda it: app.add_files([it.data(Qt.UserRole)], app.t, None))
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Asset folder", self.app.settings["asset_folder"])
        if d: self.app.settings["asset_folder"] = d; self.app.settings.save(); self.tabs.setCurrentIndex(1); self.reload()
    def reload(self):
        if not self.app.proj: return
        self.list.clear(); folder = self.app.settings["asset_folder"]
        self.folder_lbl.setText(folder if self.tabs.currentIndex() == 1 else f"{len(self.app.proj.media)} item(s) in project")
        files = scan_folder(folder) if self.tabs.currentIndex() == 1 else [p for p in self.app.proj.media if os.path.exists(p)]
        flt = self.filter.currentText().lower(); q = self.search.text().lower()
        for pth in files:
            k = kind_of(pth)
            if flt != "all" and k != flt: continue
            if q and q not in os.path.basename(pth).lower(): continue
            it = QListWidgetItem(placeholder_icon(k), os.path.basename(pth)); it.setData(Qt.UserRole, pth)
            it.setData(Qt.UserRole + 1, k); it.setData(Qt.UserRole + 2, k == "audio"); it.setToolTip(pth); self.list.addItem(it)
        self.refresh_icons()
    def refresh_icons(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole + 2): continue
            img = self.app.thumbs.thumb(it.data(Qt.UserRole), it.data(Qt.UserRole + 1), 1.0, 64)
            if img: it.setIcon(icon_from_image(img)); it.setData(Qt.UserRole + 2, True)


class PreviewPanel(Panel):
    def __init__(self, app):
        super().__init__("Player"); self.app = app
        app.viewport = Viewport(app); self.body.addWidget(app.viewport, 1)
        bar = QHBoxLayout(); self.time = QLabel(); bar.addWidget(self.time); bar.addStretch()
        bar.addWidget(tool("", "Previous frame", lambda: app.step(-1), icon="previous"))
        self.play_btn = tool("", "Play / Pause", app.toggle_play, icon="play", isize=20); self.play_btn.setStyleSheet("padding:2px 12px;")
        bar.addWidget(self.play_btn); bar.addWidget(tool("", "Next frame", lambda: app.step(1), icon="next")); bar.addStretch()
        self.quality = QComboBox(); self.quality.setToolTip("Viewport render quality (resource usage while editing)")
        for lab, v in QUALITIES: self.quality.addItem(lab, v)
        self.quality.setCurrentIndex(max(0, self.quality.findData(app.settings["preview_quality"])))
        self.quality.currentIndexChanged.connect(self._q); bar.addWidget(self.quality)
        bar.addWidget(tool("", "Fit view", icon="zoom_fit", cb=lambda: (setattr(app.viewport, "zoom", 1.0), setattr(app.viewport, "pan", QPointF()), app.viewport.update())))
        self.body.addLayout(bar)
    def _q(self):
        self.app.settings["preview_quality"] = self.quality.currentData(); self.app.settings.save(); self.app.request_render()


class PropRow(QWidget):
    def __init__(self, insp, name, label, lo, hi, slo, shi, dec, suffix):
        super().__init__(); self.insp = insp; self.name = name; self.k = 10 ** dec
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        l = QLabel(label); l.setFixedWidth(74); l.setObjectName("Dim")
        self.sl = QSlider(Qt.Horizontal); self.sl.setRange(int(slo * self.k), int(shi * self.k)); self.sl.setFocusPolicy(Qt.NoFocus)
        self.sp = QDoubleSpinBox(); self.sp.setRange(lo, hi); self.sp.setDecimals(dec); self.sp.setSuffix(suffix)
        self.sp.setMinimumWidth(104); self.sp.setMaximumWidth(118); self.sp.setAlignment(Qt.AlignRight); self.sp.setObjectName("PropSpin"); self.sp.setKeyboardTracking(False)  # no NoButtons: with QSS it collapses the text field to 1px
        self.kb = tool("", "Add / remove keyframe at playhead", icon=svg_icon("keyframe", "#34446a"), isize=14); self.kb.setFixedSize(24, 24)
        lay.addWidget(l); lay.addWidget(self.sl, 1); lay.addWidget(self.sp); lay.addWidget(self.kb)
        self.sl.valueChanged.connect(self._from_slider); self.sp.valueChanged.connect(self._from_spin)
        self.kb.clicked.connect(lambda: insp.toggle_key(name))
    def _from_slider(self, v):
        self.sp.blockSignals(True); self.sp.setValue(v / self.k); self.sp.blockSignals(False); self.insp.on_prop(self.name, v / self.k)
    def _from_spin(self, v):
        self.sl.blockSignals(True); self.sl.setValue(int(round(v * self.k))); self.sl.blockSignals(False); self.insp.on_prop(self.name, v)
    def set(self, v, on, any_):
        self.sp.blockSignals(True); self.sl.blockSignals(True)
        self.sp.setValue(v); self.sl.setValue(int(round(v * self.k)))
        self.sp.blockSignals(False); self.sl.blockSignals(False)
        self.kb.setIcon(svg_icon("keyframe", "#ffd166" if on else ("#5aa2ff" if any_ else "#34446a")))


class Inspector(Panel):
    TRANSFORM = [("x", "Position X", -20000, 20000, -2000, 2000, 0, " px"), ("y", "Position Y", -20000, 20000, -2000, 2000, 0, " px"),
                 ("sx", "Scale X", -5000, 5000, 0, 400, 1, "%"), ("sy", "Scale Y", -5000, 5000, 0, 400, 1, "%"),
                 ("rot", "Rotation", -36000, 36000, -180, 180, 1, "°"), ("opacity", "Opacity", 0, 100, 0, 100, 0, "%")]
    def _init_core(self, app):
        super().__init__("Properties"); self.app = app; self.loading = False; self.rows = {}; self._seg = None
        self.empty = QLabel("Select a clip to edit its properties"); self.empty.setAlignment(Qt.AlignCenter); self.empty.setObjectName("Dim")
        self.tabs = QTabWidget(); self.body.addWidget(self.empty, 1); self.body.addWidget(self.tabs, 1)
        def page():
            sa = QScrollArea(); sa.setWidgetResizable(True); w = QWidget(); f = QVBoxLayout(w); f.setSpacing(8); sa.setWidget(w); return sa, f
        # Video
        sa, f = page()
        for spec in self.TRANSFORM: r = PropRow(self, *spec); self.rows[spec[0]] = r; f.addWidget(r)
        self.uniform = QCheckBox("Uniform scale"); self.uniform.setChecked(True); f.addWidget(self.uniform)
        bl = QHBoxLayout(); l = QLabel("Blend"); l.setFixedWidth(74); l.setObjectName("Dim"); bl.addWidget(l)
        self.blend = QComboBox(); self.blend.addItems([b.title() for b in BLENDS]); self.blend.currentIndexChanged.connect(self.on_blend)
        bl.addWidget(self.blend, 1); f.addLayout(bl)
        g = QGridLayout()
        for i, (t, cb) in enumerate([("Fit", lambda: self.quick("fit")), ("Fill", lambda: self.quick("fill")), ("Flip H", lambda: self.quick("fh")),
                                     ("Flip V", lambda: self.quick("fv")), ("Center", lambda: self.quick("center")), ("Reset", lambda: self.quick("reset"))]):
            b = QPushButton(t); b.setFocusPolicy(Qt.NoFocus); b.clicked.connect(cb); g.addWidget(b, i // 3, i % 3)
        f.addLayout(g); f.addStretch(); self.tabs.addTab(sa, "Video")
        # Effects: effect layers (colour, blur, colour split, area blur, key ...)
        sa, f = page()
        self.area_panel = MaskPanel(app, holder_fn=lambda c: self.fx_panel.area_holder(c))
        self.fx_panel = EffectsPanel(app, self.area_panel); f.addWidget(self.fx_panel); f.addStretch(); self.tabs.addTab(sa, "Effects")
        # Text
        sa, f = page(); self.txt = QPlainTextEdit(); self.txt.setMaximumHeight(90); self.txt.textChanged.connect(lambda: self.on_text("text", self.txt.toPlainText()))
        f.addWidget(self.txt); form = QFormLayout()
        self.font_cb = QFontComboBox(); self.font_cb.currentFontChanged.connect(lambda fnt: self.on_text("font", fnt.family()))
        self.fsize = QSpinBox(); self.fsize.setRange(4, 1000); self.fsize.valueChanged.connect(lambda v: self.on_text("fsize", v))
        self.tcol = ColorButton(); self.tcol.changed.connect(lambda c: self.on_text("tcolor", c))
        self.bold = QCheckBox("Bold"); self.bold.toggled.connect(lambda v: self.on_text("bold", v))
        self.stroke = QSpinBox(); self.stroke.setRange(0, 80); self.stroke.valueChanged.connect(lambda v: self.on_text("stroke", v))
        self.scol = ColorButton("#000000"); self.scol.changed.connect(lambda c: self.on_text("scolor", c))
        for lab, w in (("Font", self.font_cb), ("Size", self.fsize), ("Color", self.tcol), ("", self.bold), ("Outline", self.stroke), ("Outline color", self.scol)):
            form.addRow(lab, w)
        f.addLayout(form); f.addStretch(); self.tabs.addTab(sa, "Text")
        # Audio
        sa, f = page(); r = PropRow(self, "volume", "Volume", 0, 1000, 0, 200, 0, "%"); self.rows["volume"] = r; f.addWidget(r); f.addStretch()
        self.tabs.addTab(sa, "Audio")
        # Keyframes
        sa, f = page(); r = QHBoxLayout(); self.kprop = QComboBox(); [self.kprop.addItem(lab, k) for k, lab in KEY_PROPS]
        self.kprop.currentIndexChanged.connect(lambda *_: self.refresh()); r.addWidget(self.kprop, 1)
        r.addWidget(tool("", "Previous keyframe", lambda: self.jump(-1), icon=svg_combo_icon(("angle_left", "keyframe")), isize=26)); r.addWidget(tool("", "Next keyframe", lambda: self.jump(1), icon=svg_combo_icon(("keyframe", "angle_right")), isize=26)); f.addLayout(r)
        self.kinfo = QLabel(); self.kinfo.setObjectName("Dim"); self.kinfo.setWordWrap(True); f.addWidget(self.kinfo)
        r = QHBoxLayout(); self.preset = QComboBox(); self.preset.addItems(list(EASE_PRESETS) + ["Custom"])
        self.preset.activated.connect(self.on_preset); r.addWidget(QLabel("Curve")); r.addWidget(self.preset, 1)
        ab = QPushButton("Apply curve to all segments"); ab.setToolTip("Copy the current curve to every segment of this property"); ab.clicked.connect(self.apply_all); r.addWidget(ab); f.addLayout(r)
        self.apply_transform_btn = QPushButton("Apply this curve to all Transform")
        self.apply_transform_btn.setIcon(app_icon("check"))
        self.apply_transform_btn.setMinimumHeight(30)
        self.apply_transform_btn.setToolTip("Apply the curve shown below to Position, Scale, Rotation and Opacity keyframe segments on this clip")
        self.apply_transform_btn.clicked.connect(self.apply_transform_all); f.addWidget(self.apply_transform_btn)
        self.ease = EaseEditor(); self.ease.changed.connect(self.on_ease); f.addWidget(self.ease)
        r = QHBoxLayout(); b1 = QPushButton("Delete key"); b1.clicked.connect(lambda: self.toggle_key(self.kprop.currentData(), only_remove=True))
        b2 = QPushButton("Clear all"); b2.clicked.connect(self.clear_keys); r.addWidget(b1); r.addWidget(b2); f.addLayout(r); f.addStretch()
        self.tabs.addTab(sa, "Keyframes")
    # ---- refresh ----
    def _refresh_core(self, full=False):
        c = self.app.sel_clip(); self.empty.setVisible(c is None); self.tabs.setVisible(c is not None)
        if not c: return
        self.loading = True; k = c["kind"]; vis = is_visual(k)
        for i, ok in enumerate((vis, vis, k == "text", k in ("video", "audio"), True)): self.tabs.setTabVisible(i, ok)
        lt = self.app.t - c["start"]
        for n, row in self.rows.items(): row.set(prop_at(c, n, lt), key_at(c, n, lt) is not None, bool(c["props"][n]["k"]))
        self.blend.setCurrentIndex(BLENDS.index(c["blend"]) if c["blend"] in BLENDS else 0)
        self.fx_panel.load(c, force=full)
        if full:
            if self.txt.toPlainText() != c["text"]: self.txt.setPlainText(c["text"])
            self.font_cb.setCurrentFont(QFont(c["font"])); self.fsize.setValue(int(c["fsize"])); self.tcol.set(c["tcolor"])
            self.bold.setChecked(bool(c["bold"])); self.stroke.setValue(int(c["stroke"])); self.scol.set(c["scolor"])
        name = self.kprop.currentData(); ks = c["props"][name]["k"]; self._seg = None
        for i in range(len(ks) - 1):
            if ks[i]["t"] - 1e-6 <= lt < ks[i + 1]["t"]: self._seg = i
        if self._seg is None:
            self.kinfo.setText(f"{len(ks)} keyframe(s). Place the playhead between two keyframes to edit the motion curve."); self.ease.setEnabled(False)
        else:
            e = ks[self._seg]["e"]; self.kinfo.setText(f"Segment {self._seg + 1} → {self._seg + 2} of {len(ks)} keyframes")
            self.ease.setEnabled(True); self.ease.set_e(e)
            match = next((n for n, v in EASE_PRESETS.items() if [round(x, 3) for x in v] == [round(x, 3) for x in e]), "Custom")
            self.preset.setCurrentText(match)
        self.loading = False
    # ---- edits ----
    def _c(self):
        return None if self.loading else self.app.sel_clip()
    def on_prop(self, name, v):
        c = self._c()
        if not c: return
        self.app.checkpoint(("prop", c["id"], name)); lt = self.app.t - c["start"]
        if name in ("sx", "sy") and self.uniform.isChecked():
            other = "sy" if name == "sx" else "sx"; old = prop_at(c, name, lt)
            if abs(old) > 1e-6: set_prop(c, other, lt, round(prop_at(c, other, lt) * v / old, 2))
        set_prop(c, name, lt, v); self.app.on_changed(insp=False); self.refresh()
    def toggle_key(self, name, only_remove=False):
        c = self.app.sel_clip()
        if not c: return
        self.app.checkpoint(); lt = self.app.t - c["start"]; k = key_at(c, name, lt)
        if k: remove_key(c, name, k)
        elif not only_remove: add_key(c, name, lt)
        self.app.on_changed(insp=False); self.refresh()
    def clear_keys(self):
        c = self.app.sel_clip()
        if not c: return
        self.app.checkpoint(); name = self.kprop.currentData(); p = c["props"][name]
        p["v"] = prop_at(c, name, self.app.t - c["start"]); p["k"] = []; self.app.on_changed(insp=False); self.refresh()
    def jump(self, d):
        c = self.app.sel_clip()
        if not c: return
        lt = self.app.t - c["start"]; ts = sorted({kf["t"] for pr in c["props"].values() for kf in pr["k"]})
        nxt = [t for t in ts if t > lt + 1e-4] if d > 0 else [t for t in ts if t < lt - 1e-4]
        if nxt: self.app.seek(c["start"] + (nxt[0] if d > 0 else nxt[-1]))
    def on_ease(self, e):
        c = self._c()
        if not c or self._seg is None: return
        self.app.checkpoint(("ease", c["id"])); c["props"][self.kprop.currentData()]["k"][self._seg]["e"] = list(e)
        self.preset.setCurrentText("Custom"); self.app.on_changed(insp=False)
    def on_preset(self, *_):
        name = self.preset.currentText()
        if name in EASE_PRESETS:
            curve = EASE_PRESETS[name]
            self.ease.set_e(curve)
            if self._seg is not None: self.on_ease(curve)
            self.preset.setCurrentText(name)
    def _curve_to_copy(self):
        # The curve editor is the source of truth (including a newly selected preset).
        return [float(v) for v in self.ease.e]
    def apply_all(self):
        c = self.app.sel_clip()
        if not c: return
        self.app.checkpoint()
        for kf in c["props"][self.kprop.currentData()]["k"]: kf["e"] = list(self.ease.e)
        self.app.on_changed(insp=False)
    def apply_transform_all(self):
        c = self.app.sel_clip()
        if not c: return
        curve = self._curve_to_copy()
        names = ("x", "y", "sx", "sy", "rot", "opacity")
        targets = [(name, kf) for name in names for kf in c["props"].get(name, {}).get("k", [])[:-1]]
        if not targets:
            if hasattr(self.app, "toast"): self.app.toast.show_msg("Add at least 2 keyframes to a Transform property first")
            return
        self.app.checkpoint()
        for _, kf in targets: kf["e"] = list(curve)
        self.app.on_changed(insp=False); self.refresh()
        if hasattr(self.app, "toast"): self.app.toast.show_msg(f"Curve applied to {len(targets)} Transform segments")
    def on_blend(self, i):
        c = self._c()
        if c: self.app.checkpoint(); c["blend"] = BLENDS[i]; self.app.on_changed(insp=False)
    def on_text(self, key, v):
        c = self._c()
        if not c or c["kind"] != "text": return
        self.app.checkpoint(("text", c["id"], key)); c[key] = v
        if key == "text": c["name"] = (v.split("\n")[0] or "Text")[:40]
        self.app.on_changed(insp=False)
    def quick(self, what):
        c = self.app.sel_clip()
        if not c or not is_visual(c["kind"]): return
        self.app.checkpoint(); lt = self.app.t - c["start"]; P = self.app.proj
        if what == "fit": set_prop(c, "sx", lt, 100.0); set_prop(c, "sy", lt, 100.0)
        elif what == "fill":
            bs = self.app.renderer.base_size(P, c)
            if bs: f = round(max(P.w / bs[0], P.h / bs[1]) * 100, 2); set_prop(c, "sx", lt, f); set_prop(c, "sy", lt, f); set_prop(c, "x", lt, 0.0); set_prop(c, "y", lt, 0.0)
        elif what == "fh": set_prop(c, "sx", lt, -prop_at(c, "sx", lt))
        elif what == "fv": set_prop(c, "sy", lt, -prop_at(c, "sy", lt))
        elif what == "center": set_prop(c, "x", lt, 0.0); set_prop(c, "y", lt, 0.0)
        elif what == "reset":
            for k in ("x", "y", "sx", "sy", "rot", "opacity"): c["props"][k] = {"v": DEFAULT_PROPS[k], "k": []}
        self.app.on_changed(insp=False); self.refresh()
    def __init__(self, app):
        self._init_core(app)
        self.mask_panel = MaskPanel(app)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(self.mask_panel)
        self._mask_tab = self.tabs.addTab(sc, "Mask")
    def refresh(self, full=False):
        self._refresh_core(full)
        c = self.app.sel_clip()
        self.tabs.setTabVisible(self._mask_tab, bool(c) and c["kind"] != "audio")
        self.mask_panel.load(c, force=full)

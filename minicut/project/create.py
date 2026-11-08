"""Project creation: new-project dialog, home screen, open / load / save of project files."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.widgets import *
from ..render.media import *
from ..render.renderer import *
from ..shared.ui import *

QComboBox = ComboBox

# ── Aspect-ratio visual button ────────────────────────────────────────────────
class _RatioBtn(QWidget):
    clicked = Signal()

    def __init__(self, label, w_ratio, h_ratio, parent=None):
        super().__init__(parent)
        self.label = label
        self.w_ratio = w_ratio
        self.h_ratio = h_ratio
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(64, 64)

    def setSelected(self, v):
        self._selected = bool(v)
        self.update()

    def isSelected(self):
        return self._selected

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = pal()
        accent = QColor(c["accent"])
        base = QColor(255, 255, 255, 25)
        sel_bg = QColor(accent.red(), accent.green(), accent.blue(), 40)

        # outer cell
        bg = sel_bg if self._selected else base
        pen_col = accent if self._selected else QColor(255, 255, 255, 50)
        p.setPen(QPen(pen_col, 1.5))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, 63, 63), 8, 8)

        # inner ratio rectangle
        max_w, max_h = 36, 36
        r = self.w_ratio / self.h_ratio
        if r >= 1:
            rw = max_w
            rh = max(10, int(max_w / r))
        else:
            rh = max_h
            rw = max(10, int(max_h * r))
        rx = (64 - rw) // 2
        ry = (64 - rh) // 2 - 6

        rect_pen = accent if self._selected else QColor(255, 255, 255, 180)
        p.setPen(QPen(rect_pen, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(rx, ry, rw, rh), 2, 2)

        # label
        font = QFont()
        font.setPointSize(8)
        font.setBold(self._selected)
        p.setFont(font)
        text_col = accent if self._selected else QColor(255, 255, 255, 180)
        p.setPen(text_col)
        p.drawText(QRect(0, ry + rh + 4, 64, 16), Qt.AlignCenter, self.label)


# ── New Project Dialog ────────────────────────────────────────────────────────
class NewProjectDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "New Project", 560)
        self.card.setMinimumHeight(360)

        # ── Project name ──────────────────────────────────────────
        name_lbl = QLabel("Project Name")
        name_lbl.setObjectName("Dim")
        self.name = TextField(f"Project {datetime.datetime.now():%Y-%m-%d %H%M}")
        self.body.addWidget(name_lbl)
        self.body.addWidget(self.name)

        # ── Aspect ratio grid ─────────────────────────────────────
        ratio_lbl = QLabel("Aspect Ratio")
        ratio_lbl.setObjectName("Dim")
        self.body.addWidget(ratio_lbl)

        ratios = [
            ("16:9",  16, 9),
            ("9:16",  9, 16),
            ("1:1",   1,  1),
            ("4:3",   4,  3),
            ("3:4",   3,  4),
            ("21:9", 21,  9),
        ]
        grid_w = QWidget()
        grid = QHBoxLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._ratio_btns = []
        for label, wr, hr in ratios:
            btn = _RatioBtn(label, wr, hr)
            btn.clicked.connect(lambda b=btn: self._select_ratio(b))
            grid.addWidget(btn)
            self._ratio_btns.append(btn)
        grid.addStretch()
        self.body.addWidget(grid_w)

        # ── Resolution preset (drives actual px) ──────────────────
        res_lbl = QLabel("Resolution")
        res_lbl.setObjectName("Dim")
        self.preset = QComboBox()
        [self.preset.addItem(n, (w, h)) for n, w, h in SIZE_PRESETS]
        idx = next(
            (i for i, (_, w, h) in enumerate(SIZE_PRESETS)
             if (w, h) == (app.settings["default_w"], app.settings["default_h"])), 0)
        self.preset.setCurrentIndex(idx)

        # ── FPS ───────────────────────────────────────────────────
        fps_lbl = QLabel("Frame Rate")
        fps_lbl.setObjectName("Dim")
        self.fps = QComboBox()
        [self.fps.addItem(f"{f} fps", f) for f in (24, 25, 30, 50, 60)]
        self.fps.setCurrentIndex(max(0, self.fps.findData(app.settings["default_fps"])))

        row2 = QHBoxLayout()
        col_res = QVBoxLayout()
        col_res.setSpacing(4)
        col_res.addWidget(res_lbl)
        col_res.addWidget(self.preset)
        col_fps = QVBoxLayout()
        col_fps.setSpacing(4)
        col_fps.addWidget(fps_lbl)
        col_fps.addWidget(self.fps)
        row2.addLayout(col_res, 2)
        row2.addSpacing(12)
        row2.addLayout(col_fps, 1)
        self.body.addLayout(row2)

        # sync ratio buttons with current preset
        self._sync_ratio_from_preset()
        self.preset.currentIndexChanged.connect(self._sync_ratio_from_preset)

        # ── Buttons ───────────────────────────────────────────────
        self.body.addSpacing(4)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(Btn("Cancel", None, "soft", "", self.reject))
        btn_row.addWidget(Btn("Create", "check", "accent", "", self.accept))
        self.body.addLayout(btn_row)

    # ── helpers ──────────────────────────────────────────────────
    def _select_ratio(self, btn):
        for b in self._ratio_btns:
            b.setSelected(b is btn)
        # find best matching preset
        wr, hr = btn.w_ratio, btn.h_ratio
        best = -1
        for i, (_, pw, ph) in enumerate(SIZE_PRESETS):
            if pw > ph and wr > hr:
                best = i; break
            if ph > pw and hr > wr:
                best = i; break
            if pw == ph and wr == hr:
                best = i; break
        if best >= 0:
            self.preset.setCurrentIndex(best)

    def _sync_ratio_from_preset(self):
        w, h = self.preset.currentData()
        from math import gcd
        g = gcd(w, h)
        wr, hr = w // g, h // g
        # simplify very large ratios
        for b in self._ratio_btns:
            match = False
            bw, bh = b.w_ratio, b.h_ratio
            # compare as floats
            if abs(bw / bh - wr / hr) < 0.01:
                match = True
            b.setSelected(match)

    def data(self):
        w, h = self.preset.currentData()
        return self.name.text().strip() or "Untitled", w, h, self.fps.currentData()


# ── Home screen & project I/O ─────────────────────────────────────────────────
class ProjectMixin:
    """Project creation / opening / saving and the home screen."""

    def _build_home(self):
        l = QVBoxLayout(self.home)
        l.setContentsMargins(42, 32, 42, 32)

        title = QLabel("MiniCut")
        title.setObjectName("H1")
        sub = QLabel("Lightweight video editor")
        sub.setObjectName("Dim")
        l.addWidget(title)
        l.addWidget(sub)

        row = QHBoxLayout()
        b = QPushButton("New project")
        b.setIcon(app_icon("import"))
        b.setObjectName("Accent")
        b.clicked.connect(self.new_project)
        row.addWidget(b)
        b = QPushButton("Open project…")
        b.setIcon(app_icon("folder_open"))
        b.clicked.connect(self.open_dialog)
        row.addWidget(b)
        b = QPushButton("Settings")
        b.setIcon(app_icon("settings"))
        b.clicked.connect(self.open_settings)
        row.addWidget(b)
        row.addStretch()
        l.addLayout(row)

        l.addWidget(QLabel("Recent projects"))
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(
            lambda it: self.load_project(it.data(Qt.UserRole)))
        l.addWidget(self.recent, 1)

    def show_home(self):
        self.finish_record()
        self.exit_media_preview(clear_selection=True)
        self.stop_play()
        self.refresh_recent()
        self.stack.setCurrentWidget(self.home)

    def refresh_recent(self):
        self.recent.clear()
        folder = self.settings["project_folder"]
        os.makedirs(folder, exist_ok=True)
        for p in sorted(
            [os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith(".minicut")],
            key=os.path.getmtime, reverse=True
        ):
            it = QListWidgetItem(
                app_icon("project"),
                os.path.basename(p) + "   ·   " +
                datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"))
            it.setData(Qt.UserRole, p)
            self.recent.addItem(it)

    def new_project(self):
        d = NewProjectDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        name, w, h, fps = d.data()
        self.proj = Project(name, w, h, fps)
        self.proj.path = None
        self.t = 0
        self.sel = None
        self._undo = []
        self._redo = []
        self._retire_renderer()
        self.pool = MediaPool(use_proxy=self.settings["proxy_preview"])
        self.renderer = Renderer(self.pool)
        self._build_editor()
        self.stack.setCurrentWidget(self.editor)
        self.request_render()

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Open MiniCut project",
            self.settings["project_folder"],
            "MiniCut project (*.minicut *.json)")
        if p:
            self.load_project(p)

    def load_project(self, p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.proj = Project.from_dict(d)
            self.proj.path = p
            self.t = 0
            self.sel = None
            self._undo = []
            self._redo = []
            self._retire_renderer()
            self.pool = MediaPool(use_proxy=self.settings["proxy_preview"])
            self.renderer = Renderer(self.pool)
            self._build_editor()
            self.stack.setCurrentWidget(self.editor)
            self.request_render()
        except Exception as ex:
            QMessageBox.warning(self, "Open failed", str(ex))

    def _retire_renderer(self):
        """Stop the previous project's render worker, baked-proxy manager and media pool."""
        w = getattr(self, "_rworker", None)
        if w is not None:
            try:
                w.stop()
            except Exception:
                pass
            self._rworker = None
        old = getattr(self, "renderer", None)
        if old is not None:
            bm = getattr(old, "bake", None)
            if bm is not None:
                try:
                    bm.stop()
                except Exception:
                    pass
            try:
                with old._src_lock:
                    self.pool.reset()
            except Exception:
                pass

    def save_project(self):
        if not self.proj:
            return
        path = self.proj.path
        if not path:
            folder = self.settings["project_folder"]
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, safe_name(self.proj.name) + ".minicut")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.proj.to_dict(), f, ensure_ascii=False, indent=2)
            self.proj.path = path
            self.settings.save()
            self.refresh_recent()
            self._saved_sig = self._proj_sig()
            if not getattr(self, "_quiet_save", False):
                self.toast.show_msg("Project saved")
        except Exception as ex:
            if getattr(self, "_quiet_save", False):
                self.toast.show_msg("Auto save failed: " + str(ex))
            else:
                QMessageBox.warning(self, "Save failed", str(ex))

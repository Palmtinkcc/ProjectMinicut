"""Project creation: new-project dialog, home screen (project cards, storage ring, Manage), open / load / save of project files."""
import hashlib, shutil
from PySide6.QtGui import QDesktopServices
from ..shared.deps import *
from ..shared.icons import *
from ..shared.icons import _project_root
from ..shared.core import *
from ..shared.widgets import *
from ..render.media import *
from ..render.renderer import *
from ..shared.ui import *

try:
    from PySide6.QtSvg import QSvgRenderer as _QSvgRenderer
except Exception:
    _QSvgRenderer = None

QComboBox = ComboBox

# ── Home screen settings ──────────────────────────────────────────────────────
# The resolution of a new project is a quality = the SHORT side in pixels; every aspect ratio follows it:
# 720p -> 16:9 is 1280x720, 1:1 is 720x720, 9:16 is 720x1280, 21:9 is 1680x720.
QUALITIES = (("480p", 480), ("720p", 720), ("1080p", 1080), ("1440p", 1440), ("4K", 2160))
FPS_CHOICES = (24, 25, 30, 50, 60)
RATIOS = (("16:9", 16, 9), ("9:16", 9, 16), ("1:1", 1, 1), ("4:3", 4, 3), ("3:4", 3, 4), ("21:9", 21, 9))
YOUTUBE_URL = "https://youtube.com/@palmtiti?si=8TltTlvzL28o3XQt"
GITHUB_URL = "https://github.com/Palmtinkcc/Velocut"

# Storage the program uses (folders inside APP_DIR): key = folder name, label, group on the home page, can be deleted, what it is.
STORAGE_ITEMS = (
    ("proxies", "Proxy videos", "Proxy", True, "Light copies of your videos that keep the preview smooth. They are made again when needed."),
    ("bake", "Baked segments", "Cache", True, "Pre-rendered pieces of the timeline (Adaptive Proxy). Made again when needed."),
    ("audiocache", "Audio waveforms", "Cache", True, "Decoded sound used for waveforms and playback. Made again when needed."),
    ("fxcache", "Effect previews", "Cache", True, "Small pictures of the effects in the Effects panel."),
    ("smartkey", "Smart Key renders", "Smart Key", True, "Cut-outs rendered by Smart Key. If you delete them, they have to be rendered again."),
    ("extracted_audio", "Extracted audio", "Other", False, "Sound taken out of videos. Projects may use these files, so they are not deleted here."),
    ("custom_effects", "Custom effects", "Other", False, "Effects you made or imported. Delete them in the Effects panel."),
)
GROUPS = (("Program", "#ffd60a"), ("Proxy", "#2f6bff"), ("Cache", "#00e5a0"), ("Smart Key", "#ff9f0a"), ("Projects", "#bf5af2"), ("Other", "#8e8e9b"))
GROUP_COLOR = dict(GROUPS)
THUMB_W = 360


def _nearest(v, choices):
    return min(choices, key=lambda c: abs(c - v))


def size_for(rw, rh, short):
    """Pixel size of the aspect ratio rw:rh whose SHORT side is `short` (both sides are even numbers, the encoder needs that)."""
    if rw >= rh: h = float(short); w = short * rw / float(rh)
    else: w = float(short); h = short * rh / float(rw)
    return int(round(w / 2.0)) * 2, int(round(h / 2.0)) * 2


def home_defaults(settings):
    """(quality, fps) the home page starts with: the last choice, or the size of the old default project."""
    d = settings.d; qs = [v for _, v in QUALITIES]
    try: q = int(d.get("default_quality") or min(int(d.get("default_w", 1920)), int(d.get("default_h", 1080))))
    except (TypeError, ValueError): q = 1080
    try: f = int(d.get("default_fps", 30))
    except (TypeError, ValueError): f = 30
    return _nearest(q, qs), (f if f in FPS_CHOICES else 30)


def fmt_bytes(n):
    n = float(max(0, n))
    if n < 1024: return "%d B" % n
    for u in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024 or u == "GB": return "%.1f %s" % (n, u)


def _dir_size(path):
    """(bytes, files) of everything below `path` ((0, 0) when it is not there). Never raises."""
    total = n = 0
    try:
        if os.path.isfile(path): return os.path.getsize(path), 1
        for root, _dirs, files in os.walk(path):
            for f in files:
                try: total += os.path.getsize(os.path.join(root, f)); n += 1
                except OSError: pass
    except Exception: pass
    return total, n


def scan_storage(project_folder):
    """What the program keeps on the disk, one dict per kind: key, label, group, bytes, files, path, deletable, desc.
    Runs in a helper thread (the proxy folder can hold many GB)."""
    rows = []; known = {it[0] for it in STORAGE_ITEMS}
    root = _project_root()
    if os.path.isfile(os.path.join(root, "file.py")):
        b, n = _dir_size(root); rows.append({"key": "program", "label": "Program", "group": "Program", "bytes": b, "files": n, "path": root, "deletable": False, "desc": "MiniCut itself: code and fonts."})
    for key, label, group, deletable, desc in STORAGE_ITEMS:
        p = os.path.join(APP_DIR, key); b, n = _dir_size(p)
        rows.append({"key": key, "label": label, "group": group, "bytes": b, "files": n, "path": p, "deletable": deletable, "desc": desc})
    b, n = _dir_size(project_folder)
    rows.append({"key": "projects", "label": "Projects", "group": "Projects", "bytes": b, "files": n, "path": project_folder, "deletable": False, "desc": "Your project files. Delete a project with the bin on its card."})
    pf = os.path.realpath(project_folder); ob = on = 0
    try:
        for nm in os.listdir(APP_DIR):
            p = os.path.join(APP_DIR, nm)
            if nm in known or os.path.realpath(p) == pf: continue
            b, n = _dir_size(p); ob += b; on += n
    except OSError: pass
    rows.append({"key": "other", "label": "Other", "group": "Other", "bytes": ob, "files": on, "path": APP_DIR, "deletable": False, "desc": "Settings, small state files and project pictures of the home page."})
    return rows


def group_totals(rows):
    d = {g: 0 for g, _ in GROUPS}
    for r in rows: d[r["group"]] = d.get(r["group"], 0) + r["bytes"]
    return [(g, c, d[g]) for g, c in GROUPS]


def clear_dir(path):
    """Delete everything INSIDE `path` (the folder stays). Returns (removed, could_not_remove)."""
    n = bad = 0
    if not os.path.isdir(path): return 0, 0
    for nm in os.listdir(path):
        p = os.path.join(path, nm)
        try:
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p); n += 1
        except OSError: bad += 1
    return n, bad


def read_project_meta(path):
    """Cheap facts for a project card, read from the file: size, fps, length and the first picture source. None if it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as f: d = json.load(f)
        clips = [c for c in (d.get("clips") or []) if isinstance(c, dict)]
        dur = max((float(c.get("start", 0)) + float(c.get("dur", 0)) for c in clips), default=0.0)
        vis = sorted((c for c in clips if c.get("kind") in ("video", "image", "gif") and c.get("path")), key=lambda c: float(c.get("start", 0)))
        src = (vis[0]["path"], vis[0]["kind"], float(vis[0].get("inp", 0) or 0)) if vis else None
        return {"w": int(d.get("w", 1920)), "h": int(d.get("h", 1080)), "fps": int(d.get("fps", 30)), "dur": dur, "clips": len(clips), "src": src}
    except Exception:
        return None


def _thumb_file(path):
    try: mt = int(os.path.getmtime(path))
    except OSError: mt = 0
    key = hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()
    return key, os.path.join(APP_DIR, "home_thumbs", "%s_%d.jpg" % (key, mt))


def forget_thumb(path):
    key, f = _thumb_file(path); d = os.path.dirname(f)
    try:
        for nm in os.listdir(d):
            if nm.startswith(key + "_"): os.remove(os.path.join(d, nm))
    except OSError: pass


def make_thumb(path, meta):
    """The first picture of the project as a QImage (kept as a small jpg in APP_DIR/home_thumbs, so the next time it is instant)."""
    if not meta or not meta.get("src"): return None
    key, f = _thumb_file(path)
    if os.path.isfile(f):
        img = QImage(f)
        if not img.isNull(): return img
    src, kind, inp = meta["src"]; frame = None
    if not os.path.isfile(src): return None
    try:
        if kind == "video":
            cap = cv2.VideoCapture(safe_path(src))
            try:
                if cap.isOpened():
                    if inp > 0: cap.set(cv2.CAP_PROP_POS_MSEC, inp * 1000.0)
                    ok, fr = cap.read()
                    if not ok and inp > 0: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, fr = cap.read()
                    frame = fr if ok else None
            finally: cap.release()
        else:
            frame = cv2.cvtColor(np.asarray(Image.open(src).convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception: frame = None
    if frame is None or frame.size == 0: return None
    h, w = frame.shape[:2]
    frame = cv2.resize(frame, (THUMB_W, max(1, int(round(h * THUMB_W / float(w))))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if ok:
        try:
            forget_thumb(path); os.makedirs(os.path.dirname(f), exist_ok=True); buf.tofile(f)
        except OSError: pass
    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)); hh, ww = rgb.shape[:2]
    return QImage(rgb.data, ww, hh, 3 * ww, QImage.Format_RGB888).copy()

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
    """Name + aspect ratio. The pixel size is the chosen resolution (the SHORT side, from the home page) applied to that aspect ratio."""
    def __init__(self, app, quality=None, fps=None):
        super().__init__(app, "New Project", 560)
        self.card.setMinimumHeight(360)
        dq, df = home_defaults(app.settings)
        quality = dq if quality is None else quality
        fps = df if fps is None else fps

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

        grid_w = QWidget()
        grid = QHBoxLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._ratio_btns = []
        for label, wr, hr in RATIOS:
            btn = _RatioBtn(label, wr, hr)
            btn.clicked.connect(lambda b=btn: self._select_ratio(b))
            grid.addWidget(btn)
            self._ratio_btns.append(btn)
        grid.addStretch()
        self.body.addWidget(grid_w)

        # ── Resolution (short side) ───────────────────────────────
        res_lbl = QLabel("Resolution")
        res_lbl.setObjectName("Dim")
        self.preset = QComboBox()
        [self.preset.addItem(n, v) for n, v in QUALITIES]
        self.preset.setCurrentIndex(max(0, self.preset.findData(quality)))

        # ── FPS ───────────────────────────────────────────────────
        fps_lbl = QLabel("Frame Rate")
        fps_lbl.setObjectName("Dim")
        self.fps = QComboBox()
        [self.fps.addItem(f"{f} fps", f) for f in FPS_CHOICES]
        self.fps.setCurrentIndex(max(0, self.fps.findData(fps)))

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

        self.size_lbl = QLabel("")
        self.size_lbl.setObjectName("Dim")
        self.body.addWidget(self.size_lbl)

        # start with the aspect ratio of the old default project (16:9 when nothing fits)
        try:
            dw, dh = int(app.settings["default_w"]), int(app.settings["default_h"])
            start = min(self._ratio_btns, key=lambda b: abs(b.w_ratio / b.h_ratio - dw / dh))
        except Exception:
            start = self._ratio_btns[0]
        self._select_ratio(start)
        self.preset.currentIndexChanged.connect(self._update_size)

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
        self._ratio = (btn.w_ratio, btn.h_ratio)
        self._update_size()

    def _update_size(self, *_):
        w, h = size_for(self._ratio[0], self._ratio[1], self.preset.currentData())
        self.size_lbl.setText(f"{w} × {h} px")

    def data(self):
        w, h = size_for(self._ratio[0], self._ratio[1], self.preset.currentData())
        return self.name.text().strip() or "Untitled", w, h, self.fps.currentData()


# ── Home screen widgets ───────────────────────────────────────────────────────
class _FnJob(QRunnable):
    """Runs a function in a pool thread (nothing from it may touch widgets: it reports through _HomeBus)."""
    def __init__(self, fn):
        super().__init__(); self.fn = fn
    def run(self):
        try: self.fn()
        except Exception: pass


class _HomeBus(QObject):
    """The helper threads put their results on these signals; Qt delivers them in the window's thread."""
    meta = Signal(str, object, object)     # project path, facts (dict or None), picture (QImage or None)
    storage = Signal(object)               # list of rows from scan_storage()
    note = Signal(str)                     # a short message for the toast


class _ProjectCard(QFrame):
    open_req = Signal(str)
    dup_req = Signal(str)
    del_req = Signal(str)
    W, H, TH = 208, 184, 117               # card, and the height of the picture (16:9 of the inner width)

    def __init__(self, path):
        super().__init__()
        self.path = path; self.img = None; self.hover = False
        self.title = os.path.splitext(os.path.basename(path))[0]
        try: self.date = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except OSError: self.date = ""
        self.info = self.date
        self.setFixedSize(self.W, self.H); self.setCursor(Qt.PointingHandCursor); self.setToolTip(f"{self.title}\n{self.date}\n{path}")
        self.b_dup = tool("", "Duplicate", lambda: self.dup_req.emit(self.path), icon="duplicate", isize=14)
        self.b_del = tool("", "Delete", lambda: self.del_req.emit(self.path), icon="delete", isize=14)
        for b in (self.b_dup, self.b_del):
            b.setParent(self); b.setFixedSize(24, 24); b.setCursor(Qt.PointingHandCursor); b.show()
        self.b_del.move(self.W - 8 - 24, self.H - 8 - 24)
        self.b_dup.move(self.W - 8 - 24 - 26, self.H - 8 - 24)

    def set_meta(self, meta, img):
        if meta: self.info = "%d×%d · %d fps" % (meta["w"], meta["h"], meta["fps"])
        if img is not None: self.img = img
        self.update()

    def enterEvent(self, e):
        self.hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.hover = False; self.update(); super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()): self.open_req.emit(self.path)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform); c = pal()
        p.setPen(QPen(QColor(c["accent"] if self.hover else c["line"]), 1)); p.setBrush(QColor(c["field_h"] if self.hover else c["card"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)
        tr = QRectF(8, 8, self.W - 16, self.TH); clip = QPainterPath(); clip.addRoundedRect(tr, 8, 8)
        if self.img is not None and self.img.width() > 0 and self.img.height() > 0:
            p.save(); p.setClipPath(clip)
            s = max(tr.width() / self.img.width(), tr.height() / self.img.height()); sw, sh = self.img.width() * s, self.img.height() * s
            p.drawImage(QRectF(tr.x() + (tr.width() - sw) / 2, tr.y() + (tr.height() - sh) / 2, sw, sh), self.img); p.restore()
        else:
            p.setPen(Qt.NoPen); p.setBrush(QColor(c["field"])); p.drawPath(clip)
            p.drawPixmap(int(tr.center().x() - 16), int(tr.center().y() - 16), svg_pixmap("project", c["dim"], 32))
        f = QFont(); f.setPixelSize(13); f.setBold(True); p.setFont(f); p.setPen(QColor(c["text"]))
        p.drawText(QRectF(10, tr.bottom() + 6, self.W - 20, 20), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.title, Qt.ElideRight, self.W - 20))
        f2 = QFont(); f2.setPixelSize(11); p.setFont(f2); p.setPen(QColor(c["dim"])); wi = self.W - 20 - 56
        p.drawText(QRectF(10, self.H - 32, wi, 24), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.info, Qt.ElideRight, wi))


class _CardGrid(QWidget):
    """The project cards, as many in a row as fit."""
    GAP = 14

    def __init__(self):
        super().__init__()
        self._cards = []; self._cols = 0
        self.g = QGridLayout(self); self.g.setContentsMargins(2, 2, 2, 2); self.g.setSpacing(self.GAP); self.g.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def set_cards(self, cards):
        for c in self._cards:
            self.g.removeWidget(c); c.setParent(None); c.deleteLater()
        self._cards = list(cards); self._cols = 0; self._flow()

    def _flow(self):
        cols = max(1, (self.width() - 4 + self.GAP) // (_ProjectCard.W + self.GAP))
        if cols == self._cols: return
        for c in self._cards: self.g.removeWidget(c)
        for i, c in enumerate(self._cards):
            self.g.addWidget(c, i // cols, i % cols); c.show()
        self._cols = cols

    def resizeEvent(self, e):
        super().resizeEvent(e); self._flow()


class _StorageRing(QWidget):
    """Ring: how the disk space of the program is shared between its kinds of data."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(176, 176); self.parts = []; self.measured = False

    def set_parts(self, parts):
        self.parts = list(parts); self.measured = True; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); th = 12; m = th / 2.0 + 3
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(c["field"]), th)); p.drawEllipse(r)
        total = sum(b for _, _, b in self.parts)
        if total > 0:
            start = 90 * 16
            for _lbl, col, b in self.parts:
                if b <= 0: continue
                span = int(round(-360 * 16 * b / float(total))); pen = QPen(QColor(col), th); pen.setCapStyle(Qt.FlatCap)
                p.setPen(pen); p.drawArc(r, start, span); start += span
        f = QFont(); f.setPixelSize(20); f.setBold(True); p.setFont(f); p.setPen(QColor(c["text"]))
        p.drawText(QRectF(0, self.height() / 2 - 24, self.width(), 28), Qt.AlignCenter, fmt_bytes(total) if self.measured else "…")
        f2 = QFont(); f2.setPixelSize(11); p.setFont(f2); p.setPen(QColor(c["dim"]))
        p.drawText(QRectF(0, self.height() / 2 + 4, self.width(), 18), Qt.AlignCenter, "used by MiniCut" if self.measured else "measuring")


class _StorageBars(QWidget):
    """One bar per kind of data (the same colours as the ring), as long as its share of the biggest one."""
    ROW = 36

    def __init__(self):
        super().__init__(); self.parts = []; self.setFixedHeight(len(GROUPS) * self.ROW + 4)

    def set_parts(self, parts):
        self.parts = list(parts); self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); big = max([b for _, _, b in self.parts] or [0]); w = self.width()
        f = QFont(); f.setPixelSize(12); p.setFont(f)
        for i, (lbl, col, b) in enumerate(self.parts):
            y = i * self.ROW
            p.setPen(QColor(c["text"])); p.drawText(QRectF(0, y, w, 20), Qt.AlignVCenter | Qt.AlignLeft, lbl)
            p.setPen(QColor(c["dim"])); p.drawText(QRectF(0, y, w, 20), Qt.AlignVCenter | Qt.AlignRight, fmt_bytes(b))
            p.setPen(Qt.NoPen); p.setBrush(QColor(c["field"])); p.drawRoundedRect(QRectF(0, y + 22, w, 5), 2.5, 2.5)
            if b > 0 and big > 0:
                p.setBrush(QColor(col)); p.drawRoundedRect(QRectF(0, y + 22, max(5.0, w * b / float(big)), 5), 2.5, 2.5)


_GH_PATH = ("M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z")


class _BrandIcon(QWidget):
    """Round link button: YouTube or GitHub (drawn here, no picture files needed)."""
    def __init__(self, kind, url, tip):
        super().__init__()
        self.kind = kind; self.url = url; self._hover = False; self._rend = {}
        self.setFixedSize(32, 32); self.setCursor(Qt.PointingHandCursor); self.setToolTip(tip)

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()): QDesktopServices.openUrl(QUrl(self.url))

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(2, 2, 28, 28)
        if self.kind == "youtube":
            p.setPen(Qt.NoPen); p.setBrush(QColor("#ff3b30" if self._hover else "#ff0000")); p.drawEllipse(r)
            p.setBrush(QColor("#ffffff")); p.drawPolygon(QPolygonF([QPointF(12.5, 10.0), QPointF(12.5, 22.0), QPointF(22.5, 16.0)]))
        else:
            col = "#ffffff" if self._hover else pal()["text"]
            rend = self._rend.get(col)
            if rend is None and _QSvgRenderer is not None:
                svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="%s" d="%s"/></svg>' % (col, _GH_PATH)
                rend = self._rend[col] = _QSvgRenderer(QByteArray(svg.encode("utf-8")))
            if rend is not None and rend.isValid(): rend.render(p, r)
            else:
                p.setPen(Qt.NoPen); p.setBrush(QColor(col)); p.drawEllipse(r)


class ManageDialog(AnimatedDialog):
    """Storage in detail: every kind of data with its size, number of files and folder; the ones that can be rebuilt can be deleted."""
    def __init__(self, app):
        super().__init__(app, "Manage storage", 660)
        self.app = app
        self.sub = QLabel(""); self.sub.setObjectName("Dim"); self.body.addWidget(self.sub)
        self.box = QWidget(); self.rows = QVBoxLayout(self.box); self.rows.setContentsMargins(0, 0, 6, 0); self.rows.setSpacing(8)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setFixedHeight(400)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        sc.setWidget(self.box); self.box.setAutoFillBackground(False); sc.viewport().setAutoFillBackground(False)
        self.body.addWidget(sc)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(Btn("Close", None, "soft", "", self.accept)); self.body.addLayout(row)
        app._home_bus.storage.connect(self.fill)
        self.fill(app._storage_rows); app._scan_storage()

    def fill(self, rows):
        while self.rows.count():
            it = self.rows.takeAt(0); w = it.widget()
            if w is not None: w.setParent(None); w.deleteLater()
        total = sum(r["bytes"] for r in rows)
        self.sub.setText("MiniCut uses %s on this computer." % fmt_bytes(total) if rows else "Measuring…")
        for r in rows:
            fr = QFrame(); fr.setObjectName("Sec"); fr.setStyleSheet("QFrame#Sec{background:%s;border:1px solid %s;border-radius:10px;}" % (pal()["card"], pal()["line"]))
            h = QHBoxLayout(fr); h.setContentsMargins(12, 8, 10, 8); h.setSpacing(10)
            dot = QLabel(); dot.setFixedSize(10, 10); dot.setStyleSheet("background:%s;border-radius:5px;" % GROUP_COLOR.get(r["group"], "#8e8e9b")); h.addWidget(dot, 0, Qt.AlignTop)
            col = QVBoxLayout(); col.setSpacing(1)
            t = QLabel("<b>%s</b>   %s · %d file(s)" % (r["label"], fmt_bytes(r["bytes"]), r["files"])); col.addWidget(t)
            d = QLabel(r["desc"]); d.setObjectName("Dim"); d.setWordWrap(True); col.addWidget(d)
            pth = QLabel(r["path"]); pth.setObjectName("Dim"); pth.setToolTip(r["path"]); pth.setTextInteractionFlags(Qt.TextSelectableByMouse); col.addWidget(pth)
            h.addLayout(col, 1)
            h.addWidget(Btn("", "folder_open", "ghost", "Open the folder", lambda _=False, p=r["path"]: self._open(p)), 0, Qt.AlignTop)
            if r["deletable"]:
                b = Btn("Delete", "delete", "danger", "Delete these files (they are made again when needed)", lambda _=False, k=r["key"], n=r["label"], s=r["bytes"]: self._delete(k, n, s))
                b.setEnabled(r["bytes"] > 0); h.addWidget(b, 0, Qt.AlignTop)
            self.rows.addWidget(fr)
        self.rows.addStretch()

    def _open(self, path):
        if os.path.isdir(path): QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _delete(self, key, name, size):
        if ask(self, "Delete " + name, "Delete %s of “%s”? This cannot be undone." % (fmt_bytes(size), name), ("Delete", "Cancel")) == "Delete":
            self.app._delete_storage(key)


# ── Home screen & project I/O ─────────────────────────────────────────────────
class ProjectMixin:
    """Project creation / opening / saving and the home screen."""

    def _build_home(self):
        self._home_bus = _HomeBus(self); self._home_pool = QThreadPool(); self._home_pool.setMaxThreadCount(2)
        self._home_bus.meta.connect(self._on_card_meta); self._home_bus.storage.connect(self._on_storage); self._home_bus.note.connect(self._on_home_note)
        self._cards = {}; self._storage_rows = []; self._scan_busy = False

        root = QHBoxLayout(self.home)
        root.setContentsMargins(20, 24, 24, 20)
        root.setSpacing(18)

        # left rail: links
        rail = QVBoxLayout()
        rail.setSpacing(10)
        rail.addStretch()
        rail.addWidget(_BrandIcon("youtube", YOUTUBE_URL, "YouTube"))
        rail.addWidget(_BrandIcon("github", GITHUB_URL, "GitHub"))
        root.addLayout(rail)

        # centre: title, new project, project cards
        centre = QVBoxLayout()
        centre.setSpacing(14)
        head = QHBoxLayout()
        title = QLabel("MINICUT")
        title.setObjectName("H1")
        title.setStyleSheet("font-size:30px;font-weight:800;color:#2f8bff;")
        head.addWidget(title)
        head.addStretch()
        q, f = home_defaults(self.settings)
        res_lbl = QLabel("Resolution")
        res_lbl.setObjectName("Dim")
        self.home_q = QComboBox()
        [self.home_q.addItem(n, v) for n, v in QUALITIES]
        self.home_q.setCurrentIndex(max(0, self.home_q.findData(q)))
        self.home_q.setFixedWidth(104)
        self.home_q.setToolTip("Size of new projects: the short side. 16:9 is 1280×720 at 720p, 1:1 is 720×720.")
        fps_lbl = QLabel("FPS")
        fps_lbl.setObjectName("Dim")
        self.home_fps = QComboBox()
        [self.home_fps.addItem(str(x), x) for x in FPS_CHOICES]
        self.home_fps.setCurrentIndex(max(0, self.home_fps.findData(f)))
        self.home_fps.setFixedWidth(84)
        self.home_fps.setToolTip("Frame rate of new projects")
        self.home_q.currentIndexChanged.connect(self._home_defaults_changed)
        self.home_fps.currentIndexChanged.connect(self._home_defaults_changed)
        for w in (res_lbl, self.home_q, fps_lbl, self.home_fps):
            head.addWidget(w)
            head.addSpacing(6)
        centre.addLayout(head)

        top = QHBoxLayout()
        top.setSpacing(10)
        plus = QPushButton()
        plus.setObjectName("Accent")
        plus.setIcon(app_icon("plus", "#ffffff"))
        plus.setIconSize(QSize(30, 30))
        plus.setFixedSize(210, 56)
        plus.setCursor(Qt.PointingHandCursor)
        plus.setToolTip("New project")
        plus.clicked.connect(self.new_project)
        top.addWidget(plus)
        top.addWidget(Btn("Open…", "folder_open", "soft", "Open a project file", self.open_dialog), 0, Qt.AlignBottom)
        top.addWidget(Btn("Settings", "settings", "soft", "", self.open_settings), 0, Qt.AlignBottom)
        top.addStretch()
        centre.addLayout(top)

        self.home_empty = QLabel("No projects yet. Press + to start your first one.")
        self.home_empty.setObjectName("Dim")
        centre.addWidget(self.home_empty)
        self.home_grid = _CardGrid()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        sc.setWidget(self.home_grid)
        self.home_grid.setAutoFillBackground(False)
        sc.viewport().setAutoFillBackground(False)
        centre.addWidget(sc, 1)
        root.addLayout(centre, 1)

        # right: storage ring, bars, Manage
        right = QVBoxLayout()
        right.setSpacing(14)
        self.home_ring = _StorageRing()
        self.home_bars = _StorageBars()
        right.addWidget(self.home_ring, 0, Qt.AlignHCenter)
        right.addWidget(self.home_bars)
        right.addStretch()
        manage = QPushButton("Manage")
        manage.setObjectName("Accent")
        manage.setFixedSize(150, 34)
        manage.setCursor(Qt.PointingHandCursor)
        manage.setToolTip("See and delete what MiniCut keeps on the disk")
        manage.clicked.connect(self.open_manage)
        right.addWidget(manage, 0, Qt.AlignHCenter)
        right_w = QWidget()
        right_w.setFixedWidth(250)
        right_w.setLayout(right)
        root.addWidget(right_w)
        self.home_bars.set_parts(group_totals([]))

    def show_home(self):
        self.finish_record()
        self.exit_media_preview(clear_selection=True)
        self.stop_play()
        self.stack.setCurrentWidget(self.home)
        self.refresh_recent()

    def refresh_recent(self):
        """Fill the project cards and measure the storage. Only while the home page is on screen (saving calls this too)."""
        if self.stack.currentWidget() is not self.home: return
        self._rebuild_cards()
        self._scan_storage()

    # ── project cards ────────────────────────────────────────────
    def _rebuild_cards(self):
        folder = self.settings["project_folder"]
        os.makedirs(folder, exist_ok=True)
        paths = []
        try:
            paths = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".minicut")],
                           key=os.path.getmtime, reverse=True)
        except OSError:
            pass
        self._cards = {}
        for p in paths:
            c = _ProjectCard(p)
            c.open_req.connect(self.load_project)
            c.dup_req.connect(self._dup_project)
            c.del_req.connect(self._del_project)
            self._cards[p] = c
        self.home_grid.set_cards(list(self._cards.values()))
        self.home_empty.setVisible(not paths)
        for p in paths:
            self._home_pool.start(_FnJob(lambda p=p: self._card_job(p)))

    def _card_job(self, p):
        """Helper thread: facts + first picture of one project."""
        meta = read_project_meta(p)
        img = make_thumb(p, meta)
        self._home_bus.meta.emit(p, meta, img)

    def _on_card_meta(self, p, meta, img):
        c = self._cards.get(p)
        if c is None: return
        try: c.set_meta(meta, img)
        except RuntimeError: pass          # the card was removed meanwhile

    def _dup_project(self, path):
        base, ext = os.path.splitext(path)
        new = f"{base} copy{ext}"; n = 1
        while os.path.exists(new):
            n += 1; new = f"{base} copy {n}{ext}"
        try:
            shutil.copyfile(path, new)
        except OSError as ex:
            QMessageBox.warning(self, "Duplicate failed", str(ex)); return
        self.toast.show_msg("Project duplicated")
        self._rebuild_cards()

    def _del_project(self, path):
        name = os.path.splitext(os.path.basename(path))[0]
        if ask(self, "Delete project", "Delete “%s”? The project file is removed and this cannot be undone. Your media files are not touched." % name, ("Delete", "Cancel")) != "Delete":
            return
        try:
            os.remove(path)
        except OSError as ex:
            QMessageBox.warning(self, "Delete failed", str(ex)); return
        forget_thumb(path)
        self.toast.show_msg("Project deleted")
        self._rebuild_cards()
        self._scan_storage()

    # ── resolution / fps of new projects ─────────────────────────
    def _home_defaults_changed(self, *_):
        self.settings.d["default_quality"] = self.home_q.currentData()
        self.settings.d["default_fps"] = self.home_fps.currentData()
        self.settings.save()

    # ── storage ──────────────────────────────────────────────────
    def _scan_storage(self):
        if self._scan_busy: return
        self._scan_busy = True
        pf = self.settings["project_folder"]
        def job():
            rows = []
            try: rows = scan_storage(pf)
            finally: self._home_bus.storage.emit(rows)
        self._home_pool.start(_FnJob(job))

    def _on_storage(self, rows):
        self._scan_busy = False
        if not rows: return
        self._storage_rows = rows
        parts = group_totals(rows)
        self.home_ring.set_parts(parts)
        self.home_bars.set_parts(parts)

    def _on_home_note(self, msg):
        self.toast.show_msg(msg)

    def open_manage(self):
        d = ManageDialog(self)
        d.exec()
        try: self._home_bus.storage.disconnect(d.fill)
        except Exception: pass
        d.deleteLater()

    def _delete_storage(self, key):
        """Delete one kind of data (Manage). Files the program has open are let go first; what is still in use is skipped and counted."""
        r = getattr(self, "renderer", None); pool = getattr(self, "pool", None)
        path = os.path.join(APP_DIR, key)
        try:
            if key == "proxies" and r is not None and pool is not None:
                with r._src_lock: pool.reset()           # closes the open proxy files (same as Settings > Clear proxies)
            if key == "bake":
                from ..render.bake import clear_cache
                n, mb = clear_cache(getattr(r, "bake", None))
                self.toast.show_msg("Removed %d file(s), %.0f MB." % (n, mb))
                if r is not None: r.clear_preview_cache()
                self._scan_storage(); return
            if r is not None and key in ("proxies", "audiocache", "smartkey", "fxcache"): r.clear_preview_cache()
        except Exception:
            pass
        def job():
            n, bad = clear_dir(path)
            self._home_bus.note.emit("Removed %d item(s)." % n + ("  %d still in use were kept." % bad if bad else ""))
            self._home_bus.storage.emit(scan_storage(self.settings["project_folder"]))
        self._scan_busy = True
        self._home_pool.start(_FnJob(job))

    # ── project I/O ──────────────────────────────────────────────
    def new_project(self):
        q = getattr(self, "home_q", None); f = getattr(self, "home_fps", None)
        d = NewProjectDialog(self, q.currentData() if q else None, f.currentData() if f else None)
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

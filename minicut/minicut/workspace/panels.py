"""Side panels: media list, preview controls, inspector (properties) and the mask editor."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.widgets import *
from ..shared.ui import *
from .preview_widgets import SoundPreview
from ..render.renderer import *
from ..render.renderer import _mask_shape
from .afx_panel import AudioFxPanel
from .curve_panel import PresetTile, all_presets
from .viewport import *
from .effects_panel import EffectsPanel


class MaskCanvas(QWidget):
    def __init__(self, panel):
        super().__init__(); self.panel = panel; self.setMinimumHeight(170); self.bg = None; self.drag = None
        self.zoom = 1.0; self.pan = (0.0, 0.0)   # zoom and pan of the picture (wheel = zoom in EVERY mode, middle / right drag = pan)
        self.zbar = QWidget(self); zl = QHBoxLayout(self.zbar); zl.setContentsMargins(4, 2, 4, 2); zl.setSpacing(0)
        for ic, tip, fn in (("zoom_in", "Zoom in", lambda: self.zoom_by(1.25)), ("zoom_out", "Zoom out", lambda: self.zoom_by(1 / 1.25)), ("zoom_fit", "Fit", self.zoom_reset)):
            zl.addWidget(tool("", tip, fn, icon=ic, isize=16))
        self.zbar.setStyleSheet("background:rgba(20,20,22,200); border-radius:8px;"); self.zbar.adjustSize()
    def resizeEvent(self, e): self.zbar.move(self.width() - self.zbar.width() - 6, 6)
    def zoom_reset(self): self.zoom = 1.0; self.pan = (0.0, 0.0); self.update()
    def zoom_by(self, f, at=None):
        """Zoom the picture; the point under `at` (default: the middle) stays where it is."""
        p = at if at is not None else QPointF(self.width() / 2, self.height() / 2); r0 = self.frame_rect()
        nx = (p.x() - r0.left()) / r0.width(); ny = (p.y() - r0.top()) / r0.height()
        self.zoom = min(16.0, max(1.0, self.zoom * f)); r1 = self.frame_rect()
        self.pan = (self.pan[0] + p.x() - (r1.left() + nx * r1.width()), self.pan[1] + p.y() - (r1.top() + ny * r1.height()))
        if self.zoom <= 1.0: self.pan = (0.0, 0.0)
        self.update()
    def frame_rect(self):
        aw, ah = self.panel.src_size; W, H = max(10, self.width() - 16), max(10, self.height() - 16)
        s = min(W / aw, H / ah) * self.zoom; w, h = aw * s, ah * s
        return QRectF((self.width() - w) / 2 + self.pan[0], (self.height() - h) / 2 + self.pan[1], w, h)
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
        if e.button() == Qt.MiddleButton or (e.button() == Qt.RightButton and sh != "Custom"): self.drag = ("pan", pos.x(), pos.y()); return
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
        if self.drag[0] == "pan":
            px, py = self.pan; self.pan = (px + e.position().x() - self.drag[1], py + e.position().y() - self.drag[2])
            self.drag = ("pan", e.position().x(), e.position().y()); self.update(); return
        x, y = self._norm(e.position())
        if self.drag[0] == "pt":
            i = self.drag[1]; self.panel.edit(lambda ms, c: ms["pts"].__setitem__(i, [x, y]))
        else:
            _, ox, oy = self.drag; self.panel.edit(lambda ms, c: ms.update(cx=x - ox, cy=y - oy))
    def mouseReleaseEvent(self, e): self.drag = None
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MiddleButton: self.zoom = 1.0; self.pan = (0.0, 0.0); self.update()
    def wheelEvent(self, e):
        """Wheel = zoom the picture (every mask mode, so small details can be edited). Ctrl + wheel = make the mask bigger / smaller."""
        e.accept(); up = e.angleDelta().y() > 0
        if (e.modifiers() & Qt.ControlModifier) and self.panel.shape() not in ("None", "Custom"):
            f = 1.08 if up else 1 / 1.08
            self.panel.edit(lambda ms, c: ms.update(w=min(4.0, ms["w"] * f), h=min(4.0, ms["h"] * f))); return
        self.zoom_by(1.15 if up else 1 / 1.15, e.position())


QComboBox = ComboBox; QCheckBox = CheckBox       # drawn by the program


class MaskPanel(QWidget):
    ROWS = [("cx", "Position X", 0, 100, 100, "%"), ("cy", "Position Y", 0, 100, 100, "%"),
            ("w", "Width", 1, 300, 100, "%"), ("h", "Height", 1, 300, 100, "%"),
            ("rot", "Rotate", -180, 180, 1, "°"), ("round", "Round corners", 0, 100, 100, ""),
            ("feather", "Feather", 0, 100, 1, "")]
    def __init__(self, app, holder_fn=None):
        super().__init__(); self.app = app; self.holder_fn = holder_fn; self.cid = None; self.loading = False; self._before = None; self.src_size = (16, 9)
        self._ct = QTimer(self); self._ct.setSingleShot(True); self._ct.setInterval(450); self._ct.timeout.connect(self._commit)
        v = QVBoxLayout(self); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(8)
        self.layer = 0
        lr = QHBoxLayout(); lr.setSpacing(6); lay_lab = QLabel("Layer")
        self.layer_box = QComboBox(); self.layer_box.currentIndexChanged.connect(self._on_layer)
        self.mode_box = QComboBox()
        for t, d in (("Add", "add"), ("Subtract", "subtract"), ("Intersect", "intersect")): self.mode_box.addItem(t, d)
        self.mode_box.currentIndexChanged.connect(self._on_mode)
        add_lay = Btn("Layer", "plus", "soft", "Add another mask to this clip: it can add to, cut out of or intersect the masks before it", self.add_layer, h=30)
        self.del_lay = Btn("Remove", "delete", "danger", "Remove this mask layer", self.remove_layer, h=30)
        self.del_lay.label = ""; self.del_lay.setFixedWidth(38)
        for dd in (self.layer_box, self.mode_box): dd.setMinimumWidth(40)
        lr.addWidget(lay_lab); lr.addWidget(self.layer_box, 1); lr.addWidget(add_lay); lr.addWidget(self.del_lay)
        mr = QHBoxLayout(); mr.setSpacing(6); cl = label("Combine", True, 12); mr.addWidget(cl); mr.addWidget(self.mode_box, 1)
        self.layer_row = QWidget(); lv = QVBoxLayout(self.layer_row); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6); lv.addLayout(lr); lv.addLayout(mr); v.addWidget(self.layer_row)
        grid = QGridLayout(); grid.setSpacing(6); self.btns = {}
        for i, name in enumerate(MASKS):
            b = Btn(name, None, "soft", "", None, True, 30); b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, n=name: self.set_shape(n)); grid.addWidget(b, i // 3, i % 3); self.btns[name] = b
        v.addLayout(grid)
        ir = QHBoxLayout(); ir.setSpacing(6); img_lab = QLabel("Image")
        self.img_box = QComboBox(); self.img_box.currentIndexChanged.connect(self._on_img)
        self.chan_box = QComboBox()
        for t, d in (("Transparency (alpha)", "alpha"), ("Brightness", "luma")): self.chan_box.addItem(t, d)
        self.chan_box.currentIndexChanged.connect(self._on_chan)
        for dd in (self.img_box, self.chan_box): dd.setMinimumWidth(40)
        ir.addWidget(img_lab); ir.addWidget(self.img_box, 1)
        cr = QHBoxLayout(); cr.setSpacing(6); cl2 = label("Use", True, 12); cr.addWidget(cl2); cr.addWidget(self.chan_box, 1)
        self.img_row = QWidget(); iv = QVBoxLayout(self.img_row); iv.setContentsMargins(0, 0, 0, 0); iv.setSpacing(6); iv.addLayout(ir); iv.addLayout(cr); v.addWidget(self.img_row)
        self.canvas = MaskCanvas(self); v.addWidget(self.canvas, 1)
        self.hint = label("", True, 11); self.hint.setWordWrap(True); v.addWidget(self.hint)
        form = QGridLayout(); form.setHorizontalSpacing(8); form.setVerticalSpacing(6); self.sl = {}
        for r, (k, lab, lo, hi, sc, suf) in enumerate(self.ROWS):
            l = label(lab, True, 12); s = IntSlider(); s.setRange(lo, hi)
            val = QLabel("0"); val.setFixedWidth(44); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda x, k=k, sc=sc, suf=suf, val=val: self._slider(k, x, sc, suf, val))
            form.addWidget(l, r, 0); form.addWidget(s, r, 1); form.addWidget(val, r, 2); self.sl[k] = (s, sc, val, l)
        v.addLayout(form)
        row = QHBoxLayout(); self.inv = QCheckBox("Invert")
        self.inv.toggled.connect(lambda on: self.edit(lambda ms, c: ms.update(invert=bool(on))))
        rst = Btn("Reset", "reset", "soft", "Back to the start values", self.reset, h=28)
        row.addWidget(self.inv); row.addStretch(1); row.addWidget(rst); v.addLayout(row)
        self._update_ui("None")
    def _h(self, c):
        """The dict that holds the mask: the clip itself, the selected extra layer of the clip, or e.g. the parameters of one effect (area blur)."""
        if c is None: return None
        if self.holder_fn is not None: return self.holder_fn(c)
        if self.layer > 0 and self.layer - 1 < len(c.get("mask_layers") or []): return c["mask_layers"][self.layer - 1]
        return c
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
    def _refresh_layers(self):
        c = self.app.sel_clip(); area = self.holder_fn is not None
        self.layer_row.setVisible(not area and c is not None)
        if area or c is None: return
        n = 1 + len(c.get("mask_layers") or []); self.layer = min(self.layer, n - 1)
        self.layer_box.blockSignals(True); self.layer_box.clear(); self.layer_box.addItem("Base layer")
        for i in range(1, n): self.layer_box.addItem("Layer %d" % (i + 1))
        self.layer_box.setCurrentIndex(self.layer); self.layer_box.blockSignals(False)
        self.mode_box.blockSignals(True)
        if self.layer > 0: self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(c["mask_layers"][self.layer - 1].get("mode", "add"))))
        self.mode_box.setEnabled(self.layer > 0); self.mode_box.blockSignals(False); self.del_lay.setEnabled(self.layer > 0)
    def _on_layer(self, i):
        if self.loading: return
        self.layer = max(0, i); c = self.app.sel_clip()
        if c: self.load(c, force=True)
    def _on_mode(self, i):
        c = self.app.sel_clip()
        if self.loading or c is None or self.layer <= 0 or self.holder_fn is not None: return
        self.app.checkpoint(); c["mask_layers"][self.layer - 1]["mode"] = self.mode_box.currentData()
        self.app.on_changed(insp=False); self.canvas.update()
    def add_layer(self):
        c = self.app.sel_clip()
        if c is None: return
        self.app.checkpoint(); c.setdefault("mask_layers", []).append({"mode": "subtract", "mask": "Circle", "mask_shape": {}, "mask_feather": 0})
        self.layer = len(c["mask_layers"]); self.app.on_changed(insp=False); self.load(c, force=True)
    def remove_layer(self):
        c = self.app.sel_clip()
        if c is None or self.layer <= 0: return
        self.app.checkpoint(); c["mask_layers"].pop(self.layer - 1); self.layer = max(0, self.layer - 1)
        self.app.on_changed(insp=False); self.load(c, force=True)
    def _refresh_images(self):
        c = self.app.sel_clip(); sh = self.shape()
        self.img_row.setVisible(sh == "Image" and c is not None)
        if sh != "Image" or c is None: return
        ms = _mask_shape(self._h(c))
        self.img_box.blockSignals(True); self.img_box.clear(); self.img_box.addItem("choose an image…", "")
        for p in (self.app.proj.media if self.app.proj else []):
            if kind_of(p) == "image": self.img_box.addItem(os.path.basename(p), p)
        self.img_box.setCurrentIndex(max(0, self.img_box.findData(ms.get("img", "")))); self.img_box.blockSignals(False)
        self.chan_box.blockSignals(True); self.chan_box.setCurrentIndex(max(0, self.chan_box.findData(ms.get("channel", "alpha")))); self.chan_box.blockSignals(False)
    def _on_img(self, i):
        if self.loading: return
        path = self.img_box.currentData() or ""
        self.edit(lambda ms, c: ms.update(img=path))
    def _on_chan(self, i):
        if self.loading: return
        ch = self.chan_box.currentData() or "alpha"
        self.edit(lambda ms, c: ms.update(channel=ch))
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
        self.hint.setText("คลิก = เพิ่มจุด • ลากจุด = ย้าย • คลิกขวาที่จุด = ลบ • ล้อเมาส์ = ซูม • ลากด้วยปุ่มกลาง = เลื่อนภาพ" if sh == "Custom"
                          else "" if sh == "None" else "ลากเพื่อย้ายมาสก์ • ล้อเมาส์ = ซูมภาพ • Ctrl+ล้อ = ย่อ/ขยายมาสก์ • คลิกขวาลาก = เลื่อนภาพ")
        self.canvas.update()
    def load(self, c, force=False):
        h = self._h(c); key = (c["id"] if c else None, id(h))
        if key == self.cid and not force: return
        self.cid = key
        if c and h is not None: self._sync_sliders(h); self._grab_bg(c)
        self._update_ui(self.shape())
        self._refresh_layers(); self._refresh_images()
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
                img = src.frame(max(0.0, src_time(c, t - c["start"])) if c["kind"] != "image" else 0, .25)
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


class IndexTabs(Segmented):
    """Two or three choices side by side that act like tabs (currentIndex / currentChanged)."""
    currentChanged = Signal(int)
    def __init__(self, items):
        super().__init__([(t, i) for i, t in enumerate(items)], 0); self.changed.connect(lambda v: self.currentChanged.emit(v))
    def currentIndex(self): return self.cur
    def setCurrentIndex(self, i): self.setValue(i); self.currentChanged.emit(i)


def _dur_of(app, path):
    key = ("d", path)
    if key in app.thumbs.cache: return app.thumbs.cache[key] or 0.0
    if key not in app.thumbs.pending: app.thumbs._run(key, lambda: ffprobe_dur(path))
    return 0.0


def _fmt_dur(d):
    d = int(round(d)); return "%d:%02d" % (d // 60, d % 60) if d < 3600 else "%d:%02d:%02d" % (d // 3600, d // 60 % 60, d % 60)


class MediaDelegate(QStyledItemDelegate):
    """A media card: picture, kind badge, length, name. Move the mouse over a video card to skim through it."""
    def __init__(self, lst): super().__init__(lst); self.lst = lst; self._pm = {}
    def _pixmap(self, path, kind, t, w):
        img = self.lst.app.thumbs.thumb(path, kind, t, 110, True)
        if img is None: return None
        key = (path, round(t, 1)); pm = self._pm.get(key)
        if pm is None:
            if len(self._pm) > 400: self._pm.clear()
            pm = self._pm[key] = QPixmap.fromImage(img)
        return pm
    _CHK = None
    def _checker(self):
        """Patch 48: transparent pictures (PNG, GIF) are shown on a grey chequerboard, so dark or white art on a clear background is not lost."""
        if MediaDelegate._CHK is None:
            pm = QPixmap(16, 16); pm.fill(QColor("#7d7d84")); q = QPainter(pm); q.fillRect(0, 0, 8, 8, QColor("#64646b")); q.fillRect(8, 8, 8, 8, QColor("#64646b")); q.end()
            MediaDelegate._CHK = QBrush(pm)
        return MediaDelegate._CHK
    def sizeHint(self, opt, idx): return QSize(150, 124)
    def paint(self, p, opt, idx):
        p.save(); p.setRenderHint(QPainter.Antialiasing); c = pal(); path = idx.data(Qt.UserRole); kind = idx.data(Qt.UserRole + 1); app = self.lst.app
        r = QRectF(opt.rect).adjusted(4, 4, -4, -4); sel = bool(opt.state & QStyle.State_Selected); hov = bool(opt.state & QStyle.State_MouseOver)
        p.setPen(QPen(QColor(c["accent"]) if sel else QColor(c["line"] if not hov else c["dim"]), 2 if sel else 1)); p.setBrush(QColor(c["field_h"] if hov else c["card"])); p.drawRoundedRect(r, 10, 10)
        th = QRectF(r.left() + 6, r.top() + 6, r.width() - 12, (r.width() - 12) * 9 / 16); clip = QPainterPath(); clip.addRoundedRect(th, 7, 7); p.save(); p.setClipPath(clip); p.fillRect(th, QColor("#111114"))
        dur = _dur_of(app, path) if kind in ("video", "gif", "audio") else 0.0
        mp = getattr(app, "_mprev", None); mprev_active = mp is not None and mp.get("path") == path
        frac = mp["frac"] if mprev_active else (self.lst.hover[1] if (hov and self.lst.hover and self.lst.hover[0] == idx.row() and kind == "video" and dur > 0) else None)
        if kind == "audio":
            pk = app.thumbs.wave(path); p.setPen(QPen(QColor(c["accent"]), 2, Qt.SolidLine, Qt.RoundCap)); mid = th.center().y(); n = int(th.width() / 4)
            for i in range(n):
                a = (min(1.0, pk[int((i + .5) / n * len(pk))] * 3) if (pk is not None and len(pk)) else 0.25 + 0.2 * math.sin(i * 0.7)) * (th.height() / 2 - 6)
                x = th.left() + 4 + i * 4; p.drawLine(QPointF(x, mid - max(1, a)), QPointF(x, mid + max(1, a)))
        elif kind in ("video", "image", "gif"):
            pm = self._pixmap(path, kind, (frac * dur) if (frac is not None and not mprev_active) else 1.0, 110) or (self._pixmap(path, kind, 1.0, 110))
            if pm is not None:
                if kind != "video": p.fillRect(th, self._checker())
                sc = pm.scaled(int(th.width()), int(th.height()), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.drawPixmap(int(th.left()), int(th.top()), sc, (sc.width() - int(th.width())) // 2, (sc.height() - int(th.height())) // 2, int(th.width()), int(th.height()))
        p.restore()
        if frac is not None:
            if mprev_active:
                vx = th.left() + th.width() * frac
                p.setPen(QPen(QColor(0, 0, 0, 120), 4, Qt.SolidLine, Qt.RoundCap)); p.drawLine(QPointF(vx, th.top() + 1), QPointF(vx, th.bottom() - 1))
                p.setPen(QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.RoundCap)); p.drawLine(QPointF(vx, th.top() + 1), QPointF(vx, th.bottom() - 1))
            else:
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 130)); p.drawRect(QRectF(th.left(), th.bottom() - 4, th.width(), 4)); p.setBrush(QColor(c["accent"])); p.drawRect(QRectF(th.left(), th.bottom() - 4, th.width() * frac, 4))
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 150)); p.drawRoundedRect(QRectF(th.left() + 5, th.top() + 5, 22, 20), 6, 6); p.drawPixmap(int(th.left() + 8), int(th.top() + 7), svg_pixmap({"video": "video", "image": "image", "gif": "gif", "audio": "audio"}.get(kind, "video"), "#ffffff", 16))
        if dur > 0:
            txt = _fmt_dur(dur); f = QFont(p.font()); f.setPixelSize(11); f.setBold(True); p.setFont(f); w = p.fontMetrics().horizontalAdvance(txt) + 10
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 150)); p.drawRoundedRect(QRectF(th.right() - w - 5, th.bottom() - 25, w, 19), 6, 6); p.setPen(QColor("#ffffff")); p.drawText(QRectF(th.right() - w - 5, th.bottom() - 25, w, 19), Qt.AlignCenter, txt)
        f = QFont(p.font()); f.setPixelSize(12); p.setFont(f); p.setPen(QColor(c["text"])); name = idx.data(Qt.DisplayRole)
        p.drawText(QRectF(r.left() + 8, th.bottom() + 4, r.width() - 16, 20), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(name, Qt.ElideMiddle, int(r.width() - 16)))
        p.restore()


class MediaList(QListWidget):
    files_dropped = Signal(list)
    def __init__(self, app):
        super().__init__(); self.app = app; self.hover = None; self.setViewMode(QListView.IconMode); self.setIconSize(QSize(1, 1)); self.setGridSize(QSize(150, 124)); self.setItemDelegate(MediaDelegate(self))
        self.setResizeMode(QListView.Adjust); self.setMovement(QListView.Static); self.setWordWrap(True); self.setMouseTracking(True); self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection); self.setDragEnabled(True); self.setAcceptDrops(True); self.setFrameShape(QFrame.NoFrame)
        self.setDragDropMode(QAbstractItemView.DragDrop); self.setDefaultDropAction(Qt.CopyAction); self.setUniformItemSizes(True); self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        app.thumbs.updated.connect(self.viewport().update)
    _SCRUB_DY = 18          # moving the mouse this far up / down while dragging the white line means "take the file out"
    _press = None; _scrub = None; _drag_started = False
    def _card_frac(self, rc, x): return max(0.0, min(1.0, (x - (rc.left() + 10)) / max(1, rc.width() - 20)))
    def repaint_path(self, path):
        for r in range(self.count()):
            if self.item(r).data(Qt.UserRole) == path: self.viewport().update(self.visualRect(self.indexFromItem(self.item(r)))); return
        self.viewport().update()
    def leaveEvent(self, e): self.hover = None; self.viewport().update(); super().leaveEvent(e)
    def mousePressEvent(self, e):
        self._press = None; self._drag_started = False; self._scrub = None
        pt = e.position().toPoint(); i = self.indexAt(pt); mp = self.app._mprev
        if e.button() == Qt.LeftButton and i.isValid():
            self._press = (i.row(), pt, i.data(Qt.UserRole), i.data(Qt.UserRole + 1))
            if mp is not None and i.data(Qt.UserRole) == mp["path"] and not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self._scrub = pt; self.app.media_scrub_begin(self._card_frac(self.visualRect(i), pt.x()))      # the card is the progress bar
        super().mousePressEvent(e)
    def mouseMoveEvent(self, e):
        pt = e.position().toPoint()
        if self._scrub is not None:
            if (e.buttons() & Qt.LeftButton) and abs(pt.y() - self._scrub.y()) <= self._SCRUB_DY:
                self.app.media_scrub(self._card_frac(self.visualRect(self.indexFromItem(self.item(self._press[0]))), pt.x())); return
            self._scrub = None; self.app.media_scrub_end()          # left the card sideways-up / down: this is a drag of the file
        i = self.indexAt(pt); old = self.hover
        if i.isValid():
            rc = self.visualRect(i); self.hover = (i.row(), self._card_frac(rc, pt.x()))
        else: self.hover = None
        if self.hover != old: self.viewport().update()
        super().mouseMoveEvent(e)
    def event(self, e):
        if e.type() == QEvent.ShortcutOverride and e.key() == Qt.Key_Delete and self.selectedItems(): e.accept(); return True      # Delete is for the media here, not for the timeline
        return super().event(e)
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self.selectedItems(): self.app.media.remove_selected(); e.accept(); return
        super().keyPressEvent(e)
    def contextMenuEvent(self, e):
        i = self.indexAt(e.pos())
        if not i.isValid(): return
        if not i.data(Qt.UserRole) in {x.data(Qt.UserRole) for x in self.selectedItems()}: self.setCurrentIndex(i)
        rec = self.app.is_recording_file(i.data(Qt.UserRole)); m = QMenu(self)
        m.addAction("Delete recording (also deletes the file)" if rec else "Remove from media pool", self.app.media.remove_selected); m.exec(e.globalPos())
    def startDrag(self, actions):
        self._drag_started = True; pm = getattr(self.app, "media", None)
        if pm is not None: pm.sync_preview_selection(True)
        super().startDrag(actions)
    def mouseReleaseEvent(self, e):
        scrub = self._scrub; self._scrub = None; press = self._press; self._press = None
        if scrub is not None: self.app.media_scrub_end()
        super().mouseReleaseEvent(e); pt = e.position().toPoint()
        if scrub is None and press and e.button() == Qt.LeftButton and not self._drag_started and not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
            i = self.indexAt(pt)       # one click (not a drag): preview this file in the Player
            if i.isValid() and i.row() == press[0] and (pt - press[1]).manhattanLength() < QApplication.startDragDistance():
                self.item(i.row()).setSelected(True)        # (a rebuild of the list between press and release may have cleared the selection)
                self.app.media_click(press[2], press[3], self._card_frac(self.visualRect(i), pt.x()))
        pm = getattr(self.app, "media", None)
        if pm is not None: pm.sync_preview_selection(True)
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
        self.head.addWidget(Btn("Import", "import", "accent", "Add video, image or sound files to this project", app.import_dialog, h=28))
        self.head.addWidget(tool("", "Choose the asset folder (saved for every project)", self.choose_folder, icon="folder_open", isize=20))
        self.head.addWidget(tool("", "Refresh the list", self.reload, icon="refresh", isize=20))
        self.tabs = IndexTabs(["In project", "Asset folder"]); self.tabs.currentChanged.connect(lambda *_: self.reload()); self.body.addWidget(self.tabs)
        row = QHBoxLayout(); row.setSpacing(6); self.search = TextField("", "Search…"); self.filter = Dropdown([(x, x) for x in ("All", "Video", "Image", "GIF", "Audio")], 92)
        self.search.textChanged.connect(self.reload); self.filter.changed.connect(self.reload)
        row.addWidget(self.search, 1); row.addWidget(self.filter); self.body.addLayout(row)
        self.folder_lbl = label("", True, 11); self.body.addWidget(self.folder_lbl)
        self.list = MediaList(app); self.body.addWidget(self.list, 1)
        self.list.files_dropped.connect(app.import_files)
        self.list.itemDoubleClicked.connect(lambda it: app.add_files([it.data(Qt.UserRole)], app.t, None))
        self.list.itemSelectionChanged.connect(self.sync_preview_selection)
    def remove_selected(self):
        """Remove the selected files from the media pool (tab: In project). Files used on the timeline stay."""
        app = self.app
        if self.tabs.currentIndex() != 0:
            if hasattr(app, "toast"): app.toast.show_msg("Only files of the project list can be removed (tab: In project)", 2500)
            return
        paths = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
        if not paths: return
        used = [p for p in paths if app.media_in_use(p)]
        if used: QMessageBox.warning(app, "MiniCut", "Still used on the timeline, so not removed:\n" + "\n".join(os.path.basename(p) for p in used) + "\n\nRemove the clip(s) from the timeline first.")
        app.remove_media([p for p in paths if p not in used])
    def sync_preview_selection(self, force=False):
        """The media preview lives only while its card is selected: click away / select nothing and it stops."""
        mp = self.app._mprev
        if mp is None: return
        if not force and (QApplication.mouseButtons() & Qt.LeftButton): return      # a click is still going on: its mouse release decides
        if mp["path"] not in {i.data(Qt.UserRole) for i in self.list.selectedItems()}: self.app.exit_media_preview()
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Asset folder", self.app.settings["asset_folder"])
        if d: self.app.settings["asset_folder"] = d; self.app.settings.save(); self.tabs.setCurrentIndex(1); self.reload()
    def reload(self, *_):
        if not self.app.proj: return
        mp = self.app._mprev; keep = mp["path"] if mp is not None else None
        self.list.blockSignals(True); self.list.clear(); folder = self.app.settings["asset_folder"]
        self.folder_lbl.setText(folder if self.tabs.currentIndex() == 1 else f"{len(self.app.proj.media)} item(s) — double-click to add to the timeline")
        files = scan_folder(folder) if self.tabs.currentIndex() == 1 else [p for p in self.app.proj.media if os.path.exists(p)]
        flt = self.filter.currentText().lower(); q = self.search.text().lower()
        for pth in files:
            k = kind_of(pth)
            if flt != "all" and k != flt: continue
            if q and q not in os.path.basename(pth).lower(): continue
            it = QListWidgetItem(os.path.basename(pth)); it.setData(Qt.UserRole, pth); it.setData(Qt.UserRole + 1, k); it.setToolTip(pth); self.list.addItem(it)
        found = False
        if keep is not None:                  # the file being previewed stays selected when the list is rebuilt
            for r in range(self.list.count()):
                it = self.list.item(r)
                if it.data(Qt.UserRole) == keep: it.setSelected(True); self.list.setCurrentItem(it); found = True; break
        self.list.blockSignals(False)
        if keep is not None and not found: self.app.exit_media_preview()
    def refresh_icons(self): self.list.viewport().update()


class PreviewPanel(Panel):
    def __init__(self, app):
        super().__init__("Player"); self.app = app
        app.viewport = Viewport(app); self.body.addWidget(app.viewport, 1)
        bar = QHBoxLayout(); bar.setSpacing(6); self.time = QLabel(); bar.addWidget(self.time); bar.addStretch()
        bar.addWidget(Btn("", "previous", "ghost", "Previous frame", lambda: app.step(-1), h=34))
        self.play_btn = Btn("", "play", "soft", "Play / Pause (Space)", app.toggle_play, h=36); self.play_btn.setFixedWidth(52)
        bar.addWidget(self.play_btn); bar.addWidget(Btn("", "next", "ghost", "Next frame", lambda: app.step(1), h=34)); bar.addStretch()
        l = label("Quality", True, 12); bar.addWidget(l); self.quality = Dropdown([], 130); self.quality.setToolTip("How sharp the preview is while editing (lower = lighter on the computer)")
        for lab, v in QUALITIES: self.quality.addItem(lab, v)
        self.quality.setCurrentIndex(max(0, self.quality.findData(app.settings["preview_quality"])))
        self.quality.changed.connect(self._q); bar.addWidget(self.quality)
        bar.addWidget(Btn("Fit", "zoom_fit", "ghost", "Fit the picture to the window", lambda: (setattr(app.viewport, "zoom", 1.0), setattr(app.viewport, "pan", QPointF()), app.viewport.update()), h=30))
        self.body.addLayout(bar)
    def _q(self):
        self.app.settings["preview_quality"] = self.quality.currentData(); self.app.settings.save(); self.app.request_render()


class PropRow(QWidget):
    """One animatable value: [slider] [number you can drag or type] [keyframe diamond]. mode "num" = number + diamond only."""
    def __init__(self, insp, name, label, lo, hi, slo, shi, dec, suffix, mode="slider", tag="", default=None):
        super().__init__(); self.insp = insp; self.name = name; self.mode = mode
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6); self.setToolTip(label)
        dflt = DEFAULT_PROPS.get(name, 0) if default is None else default
        self.sl = Slider(slo, shi, 0, dflt, dec) if mode == "slider" else None
        self.sp = NumberField(0, lo, hi, dec, suffix, "" if mode == "slider" else tag, scrub=max(0.05, (shi - slo) / 600.0) if dec else max(1.0, (shi - slo) / 800.0), width=84 if mode == "slider" else None)
        self.kb = KeyDot()
        if mode == "slider" and tag: t = label_w(tag); t.setFixedWidth(12); lay.addWidget(t)
        if self.sl is not None: lay.addWidget(self.sl, 1)
        lay.addWidget(self.sp, 0 if self.sl is not None else 1); lay.addWidget(self.kb)
        if self.sl is not None: self.sl.changed.connect(self._from_slider)
        self.sp.changed.connect(self._from_spin); self.kb.clicked.connect(lambda: insp.toggle_key(name))
    def _from_slider(self, v): self.sp.setValue(v); self.insp.on_prop(self.name, v)
    def _from_spin(self, v):
        if self.sl is not None: self.sl.setValue(v)
        self.insp.on_prop(self.name, v)
    def set(self, v, on, any_):
        busy = (self.sl is not None and self.sl._drag) or self.sp._press is not None or self.sp.ed.isVisible()
        if not busy:
            self.sp.setValue(v)
            if self.sl is not None: self.sl.setValue(v)
        self.kb.setState(on, any_)


class RotRow(QWidget):
    """Rotation: a knob you turn, the number, quarter-turn buttons. Same calls as PropRow."""
    def __init__(self, insp):
        super().__init__(); self.insp = insp; self.name = "rot"; lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(12)
        self.dial = Dial(0); lay.addWidget(self.dial); col = QVBoxLayout(); col.setSpacing(6)
        r = QHBoxLayout(); r.setSpacing(6); self.sp = NumberField(0, -36000, 36000, 1, "°", scrub=0.5); self.kb = KeyDot(); r.addWidget(self.sp, 1); r.addWidget(self.kb); col.addLayout(r)
        q = QHBoxLayout(); q.setSpacing(4)
        for txt, d in (("−90°", -90), ("+90°", 90)): q.addWidget(Btn(txt, None, "soft", "Turn by " + txt, lambda _=False, d=d: self._add(d), h=26))
        col.addLayout(q); col.addStretch(); lay.addLayout(col, 1)
        self.dial.changed.connect(self._from_dial); self.sp.changed.connect(self._from_spin); self.kb.clicked.connect(lambda: insp.toggle_key("rot"))
    def _add(self, d): v = round(self.dial.value() + d, 1); self.dial.setValue(v); self.sp.setValue(v); self.insp.on_prop("rot", v)
    def _from_dial(self, v): self.sp.setValue(v); self.insp.on_prop("rot", v)
    def _from_spin(self, v): self.dial.setValue(v); self.insp.on_prop("rot", v)
    def set(self, v, on, any_):
        if self.sp._press is None and not self.sp.ed.isVisible() and self.dial._last is None: self.sp.setValue(v); self.dial.setValue(v)
        self.kb.setState(on, any_)


def label_w(text): return label(text, True, 12)


class Inspector(Panel):
    def _init_core(self, app):
        super().__init__("Properties"); self.app = app; self.loading = False; self.rows = {}; self._seg = None; self._ratio = {}
        self.empty = QLabel("Select a clip on the timeline\nto edit it here"); self.empty.setAlignment(Qt.AlignCenter); self.empty.setObjectName("Dim")
        self.tabs = TabHost(); self.body.addWidget(self.empty, 1); self.body.addWidget(self.tabs, 1)
        def page():
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); w = QWidget(); w.setStyleSheet("background:transparent;"); f = QVBoxLayout(w)
            f.setContentsMargins(2, 10, 6, 10); f.setSpacing(10); sa.setWidget(w); return sa, f
        # ---- Basic: where the clip is, how big, how turned, how see-through ----
        sa, f = page()
        q = QGridLayout(); q.setSpacing(6)
        for i, (txt, ic, tip, key) in enumerate((("Fit", "fit", "Fit to the screen", "fit"), ("Fill", "fill", "Fill the screen", "fill"), ("Center", "center", "Put in the middle", "center"), ("Reset", "reset", "Back to the start values", "reset"))):
            q.addWidget(Btn(txt, ic, "soft", tip, lambda _=False, k=key: self.quick(k)), i // 2, i % 2)
        f.addLayout(q)
        sec = Section("Position", "move"); r = QHBoxLayout(); r.setSpacing(10)
        for n, lab, tag in (("x", "Position X", "X"), ("y", "Position Y", "Y")):
            row = PropRow(self, n, lab, -20000, 20000, -2000, 2000, 0, " px", "num", tag); self.rows[n] = row; r.addWidget(row)
        sec.body.addLayout(r); f.addWidget(sec)
        self.uniform = Toggle("Keep ratio", True, "X and Y change together"); sec = Section("Size", "scale", self.uniform)
        for n, lab, tag in (("sx", "Width", "W"), ("sy", "Height", "H")):
            row = PropRow(self, n, lab, -5000, 5000, 0, 400, 1, "%", "slider", tag); self.rows[n] = row; sec.body.addWidget(row)
        f.addWidget(sec)
        sec = Section("Rotation", "rotate"); row = RotRow(self); self.rows["rot"] = row; sec.body.addWidget(row)
        fl = QHBoxLayout(); fl.setSpacing(6); fl.addWidget(Btn("Flip H", "flip", "soft", "Mirror left / right", lambda: self.quick("fh"), h=28)); fl.addWidget(Btn("Flip V", "swap_vert", "soft", "Mirror up / down", lambda: self.quick("fv"), h=28)); sec.body.addLayout(fl); f.addWidget(sec)
        sec = Section("Look", "opacity"); row = PropRow(self, "opacity", "Opacity", 0, 100, 0, 100, 0, "%", "slider", "Opacity"); row.layout().itemAt(0).widget().setFixedWidth(52); self.rows["opacity"] = row; sec.body.addWidget(row)
        self.blend = Dropdown([(b.title(), b) for b in BLENDS]); self.blend.changed.connect(self.on_blend)
        br = QHBoxLayout(); l = label_w("Blend"); l.setFixedWidth(52); br.addWidget(l); br.addWidget(self.blend, 1); sec.body.addLayout(br); f.addWidget(sec)
        f.addStretch(); self.tabs.addTab(sa, "Basic", "move", "Position, size, rotation, look")
        # ---- Effects: effect layers (colour, blur, colour split, area blur, key ...) ----
        sa, f = page()
        self.area_panel = MaskPanel(app, holder_fn=lambda c: self.fx_panel.area_holder(c))
        self.fx_panel = EffectsPanel(app, self.area_panel); f.addWidget(self.fx_panel); f.addStretch(); self.tabs.addTab(sa, "Effects", "effects", "Effects with a live preview")
        # ---- Text ----
        sa, f = page(); sec = Section("Text", "text"); self.txt = TextBox(96); self.txt.textChanged.connect(lambda: self.on_text("text", self.txt.toPlainText())); sec.body.addWidget(self.txt); f.addWidget(sec)
        sec = Section("Style", "adjust")
        fams = sorted(set(QFontDatabase.families())); self.font_cb = Dropdown([(x, x) for x in fams]); self.font_cb.changed.connect(lambda i: self.on_text("font", self.font_cb.currentData()))
        self.fsize = NumberField(40, 4, 1000, 0, " px", "", scrub=1.0); self.fsize.changed.connect(lambda v: self.on_text("fsize", int(v)))
        self.tcol = ColorButton(); self.tcol.changed.connect(lambda c: self.on_text("tcolor", c))
        self.bold = Toggle("Bold"); self.bold.toggled.connect(lambda v: self.on_text("bold", v))
        self.stroke = NumberField(0, 0, 80, 0, " px", "", scrub=0.5); self.stroke.changed.connect(lambda v: self.on_text("stroke", int(v)))
        self.scol = ColorButton("#000000"); self.scol.changed.connect(lambda c: self.on_text("scolor", c))
        def line(txt, *ws):
            r = QHBoxLayout(); r.setSpacing(8); l = label_w(txt); l.setFixedWidth(62); r.addWidget(l)
            for i, w in enumerate(ws): r.addWidget(w, 1 if i == 0 else 0)
            sec.body.addLayout(r)
        line("Font", self.font_cb); line("Size", self.fsize, self.tcol); line("Style", self.bold); line("Outline", self.stroke, self.scol)
        f.addWidget(sec); f.addStretch(); self.tabs.addTab(sa, "Text", "text", "Text and font")
        # ---- Audio: hear it, set the volume, add sound effects ----
        sa, f = page(); self.sound = SoundPreview(app); f.addWidget(self.sound)
        sec = Section("Volume", "volume"); r = PropRow(self, "volume", "Volume", 0, 1000, 0, 200, 0, "%", "slider", "Vol"); r.layout().itemAt(0).widget().setFixedWidth(26); self.rows["volume"] = r; sec.body.addWidget(r); f.addWidget(sec)
        self.afx_panel = AudioFxPanel(self.app); f.addWidget(self.afx_panel); f.addStretch(); self.tabs.addTab(sa, "Audio", "sound", "Sound: listen, volume, filters")
        # ---- Speed: play the media faster or slower (constant, or keyframed with the diamond) ----
        sa, f = page(); sec = Section("Speed", "speed")
        r = PropRow(self, "speed", "Speed", SPEED_MIN, SPEED_MAX, 10, 400, 0, "%", "slider", ""); self.rows["speed"] = r; sec.body.addWidget(r)
        q = QHBoxLayout(); q.setSpacing(4)
        for txt, v in (("0.5\u00d7", 50), ("1\u00d7", 100), ("2\u00d7", 200), ("4\u00d7", 400)): q.addWidget(Btn(txt, None, "soft", "Set the speed to " + txt, lambda _=False, v=v: self.on_prop("speed", v), h=26))
        sec.body.addLayout(q); f.addWidget(sec)
        sec = Section("Pitch", "sound"); self.pitch_tg = Toggle("Pitch follows speed", False, "On: faster = higher, slower = deeper (like a tape). Off: the pitch stays the same."); self.pitch_tg.toggled.connect(self.on_pitch); sec.body.addWidget(self.pitch_tg); f.addWidget(sec)
        f.addStretch(); self.tabs.addTab(sa, "Speed", "speed", "Make the media faster or slower")
        # ---- Keys: the motion curve between two keyframes ----
        sa, f = page(); self.checked = set(); self._toggle_cid = None; self._more = False; self._presets_key = None
        self.kprop = Dropdown([(lab, k) for k, lab in KEY_PROPS]); self.kprop.hide(); self.kprop.changed.connect(lambda *_: self.refresh())
        sec = Section("Motion curve", "keys"); self.ease = EaseEditor(); self.ease.changed.connect(self.on_ease); self.ease.setMinimumHeight(190); sec.body.addWidget(self.ease)
        self.kinfo = label_w(""); self.kinfo.setWordWrap(True); sec.body.addWidget(self.kinfo); f.addWidget(sec)
        sec = Section("Apply the curve to", "layers"); self.toggle_row = QGridLayout(); self.toggle_row.setSpacing(6); sec.body.addLayout(self.toggle_row); self.toggles = {}
        for i, (k, name) in enumerate(KEY_PROPS):
            b = Btn(name, None, "soft", "", None, True, 28); b.toggled.connect(lambda v, k=k: self.on_toggle(k, v)); self.toggles[k] = b; self.toggle_row.addWidget(b, i // 2, i % 2)
        acts = QGridLayout(); acts.setSpacing(6)
        for i, (txt, ic, kind, tip, cb) in enumerate((
                ("Apply", "done", "accent", "Copy the curve to every segment of the checked properties", self.apply_checked),
                ("All segments", "layers", "soft", "Copy the curve to every segment of this property", self.apply_all),
                ("Clear", "close", "soft", "Delete the keyframes of this property", self.clear_keys),
                ("Clear all", "delete", "danger", "Delete the keyframes of every property of this clip", self.clear_all_keys))):
            acts.addWidget(Btn(txt, ic, kind, tip, cb), i // 2, i % 2)
        sec.body.addLayout(acts); f.addWidget(sec)
        self.more_btn = Btn("More", "expand_more", "ghost", "Show all presets", self._toggle_more, h=26)
        sec = Section("Curve presets", "timeline"); sec.addRight(Btn("Save", "save", "ghost", "Keep the curve above as a preset of your own", self._save_preset, h=26)); sec.addRight(self.more_btn)
        self.preset_grid = QGridLayout(); self.preset_grid.setSpacing(8); sec.body.addLayout(self.preset_grid); f.addWidget(sec)
        f.addStretch(); self.tabs.addTab(sa, "Keys", "keys", "Keyframes and motion curves")
    # ---- refresh ----
    def _refresh_core(self, full=False):
        c = self.app.sel_clip(); self.empty.setVisible(c is None); self.tabs.setVisible(c is not None)
        if not c: return
        self.loading = True; k = c["kind"]; vis = is_visual(k)
        for i, ok in enumerate((vis, vis, k == "text", k in ("video", "audio", "compound"), k in SPEED_KINDS, True)): self.tabs.setTabVisible(i, ok)
        lt = self.app.t - c["start"]
        for n, row in self.rows.items(): row.set(prop_at(c, n, lt), key_at(c, n, lt) is not None, bool(c["props"][n]["k"]))
        self.blend.setCurrentIndex(BLENDS.index(c["blend"]) if c["blend"] in BLENDS else 0)
        self.afx_panel.setVisible(k != "compound"); self.sound.load(c)
        self.fx_panel.load(c, force=full)
        self.afx_panel.load(c, force=full)
        self.pitch_tg.blockSignals(True); self.pitch_tg.setChecked(bool(c.get("pitch_follow", False))); self.pitch_tg.blockSignals(False)
        if full:
            if self.txt.toPlainText() != c["text"]: self.txt.setPlainText(c["text"])
            if self.font_cb.findData(c["font"]) >= 0: self.font_cb.setCurrentData(c["font"])
            self.fsize.setValue(int(c["fsize"])); self.tcol.set(c["tcolor"])
            self.bold.setChecked(bool(c["bold"])); self.stroke.setValue(int(c["stroke"])); self.scol.set(c["scolor"])
        self._sync_toggles(c)
        name = self.kprop.currentData(); ks = c["props"][name]["k"]; self._seg = None
        for i in range(len(ks) - 1):
            if ks[i]["t"] - 1e-6 <= lt < ks[i + 1]["t"]: self._seg = i
        if self._seg is None:
            self.kinfo.setText(f"{len(ks)} keyframe(s). Put the playhead between two keyframes to shape the motion."); self.ease.setEnabled(False)
        else:
            e = ks[self._seg]["e"]; self.kinfo.setText(f"Segment {self._seg + 1} → {self._seg + 2} of {len(ks)} keyframes")
            self.ease.setEnabled(True); self.ease.set_e(e)
        self.loading = False
    # ---- edits ----
    def _c(self):
        return None if self.loading else self.app.sel_clip()
    def on_prop(self, name, v):
        c = self._c()
        if not c: return
        self.app.checkpoint(("prop", c["id"], name)); lt = self.app.t - c["start"]
        if name == "speed" and c["kind"] in SPEED_KINDS: self._on_speed(c, lt, v); return
        if name in ("sx", "sy") and self.uniform.isChecked():
            # Uniform scale keeps the shape (ratio Y / X). The ratio is remembered while both sides are not 0, so when one
            # side is 0 (or is dragged back up from 0) the other side still follows with the right proportion.
            other = "sy" if name == "sx" else "sx"; sx0, sy0 = prop_at(c, "sx", lt), prop_at(c, "sy", lt)
            if abs(sx0) > 1e-6 and abs(sy0) > 1e-6: self._ratio[c["id"]] = sy0 / sx0
            r = self._ratio.get(c["id"], 1.0)
            if abs(r) < 1e-6: r = 1.0
            set_prop(c, other, lt, round(v * r if name == "sx" else v / r, 2))
        set_prop(c, name, lt, v); self.app.on_changed(insp=False); self.refresh()
    def _on_speed(self, c, lt, v):
        p = c["props"]["speed"]; v = max(SPEED_MIN, min(SPEED_MAX, float(v)))
        if not p["k"]:
            old = max(SPEED_MIN, float(p["v"])); p["v"] = v; r = old / v
            if abs(r - 1.0) > 1e-9:
                c["dur"] = max(1.0 / self.app.proj.fps, c["dur"] * r)          # the same part of the media stays: the clip gets shorter / longer
                for pr in c["props"].values():
                    for k in pr["k"]: k["t"] *= r                              # keyframes stay on the same moment of the picture
                self.app.place_free(c)
        else:
            set_prop(c, "speed", lt, v)
            if c["kind"] in ("video", "audio") and c.get("src_dur", 0) > 0 and src_time(c, c["dur"]) > c["src_dur"]:
                c["dur"] = max(1.0 / self.app.proj.fps, local_of_src(c, c["src_dur"] - c["inp"]))      # never run past the end of the file
        self.app.on_changed(insp=False); self.refresh()
    def on_pitch(self, v):
        c = self._c()
        if not c: return
        self.app.checkpoint(); c["pitch_follow"] = bool(v); self.app.on_changed(insp=False)
    # ---- keyframe tab helpers: curve toggles, presets, apply / clear ----
    def _curve_props(self, c):
        if c is None: return []
        return [k for k, _ in KEY_PROPS if k in c["props"] and ((k in ("speed",) and c["kind"] in SPEED_KINDS) or (k != "speed" and (k == "volume") == (c["kind"] == "audio")))]
    def _sync_toggles(self, c):
        cid = c["id"] if c else None
        if getattr(self, "_toggle_cid", None) != cid: self._toggle_cid = cid; self.checked = set(); self._presets_key = None
        avail = self._curve_props(c)
        for k, b in self.toggles.items():
            b.setVisible(k in avail); b.blockSignals(True); b.setChecked(k in self.checked); b.blockSignals(False)
        key = (cid, len(self.app.settings["curve_presets"] or {}), self._more)
        if self._presets_key != key: self._rebuild_presets()
    def on_toggle(self, k, on):
        if on: self.checked.add(k); self.kprop.setCurrentIndex(self.kprop.findData(k))
        else: self.checked.discard(k)
    def apply_checked(self):
        c = self.app.sel_clip()
        if not c: return
        curve = self._curve_to_copy(); names = list(self.checked) or [self.kprop.currentData()]
        targets = [kf for n in names for kf in c["props"].get(n, {}).get("k", [])[:-1]]
        if not targets:
            if hasattr(self.app, "toast"): self.app.toast.show_msg("Add at least 2 keyframes to the checked properties first")
            return
        self.app.checkpoint()
        for kf in targets: kf["e"] = list(curve)
        self.app.on_changed(insp=False); self.refresh()
    def clear_all_keys(self):
        c = self.app.sel_clip()
        if not c: return
        self.app.checkpoint(); t = self.app.t - c["start"]
        for n in self._curve_props(c): c["props"][n]["v"] = prop_at(c, n, t); c["props"][n]["k"] = []
        self.app.on_changed(insp=False); self.refresh()
    def apply_curve(self, curve):
        self.ease.set_e(curve)
        if self._seg is not None: self.on_ease(curve)
    def _toggle_more(self):
        self._more = not self._more; self._rebuild_presets()
    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save curve", "Name for this curve:")
        name = (name or "").strip()
        if not ok or not name: return
        if not isinstance(self.app.settings["curve_presets"], dict): self.app.settings["curve_presets"] = {}
        self.app.settings["curve_presets"][name] = [float(v) for v in self.ease.e]; self.app.settings.save(); self._rebuild_presets()
    def _rebuild_presets(self):
        c = self.app.sel_clip(); cid = c["id"] if c else None
        self._presets_key = (cid, len(self.app.settings["curve_presets"] or {}), self._more)
        while self.preset_grid.count():
            w = self.preset_grid.takeAt(0).widget()
            if w: w.deleteLater()
        items = list(all_presets(self.app.settings).items())
        shown = items if self._more else items[:6]
        for i, (name, curve) in enumerate(shown):
            tile = PresetTile(name, curve, selected=[round(v, 3) for v in curve] == [round(float(v), 3) for v in self.ease.e])
            tile.clicked.connect(self.apply_curve); self.preset_grid.addWidget(tile, i // 3, i % 3)
        self.more_btn.label = "Less" if self._more else "More"; self.more_btn.setIconName("expand_less" if self._more else "expand_more"); self.more_btn.setVisible(len(items) > 6); self.more_btn.update()
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
        self.app.on_changed(insp=False)
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
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.setWidget(self.mask_panel)
        self._mask_tab = self.tabs.addTab(sc, "Mask", "mask", "Mask: show only a part")
    def refresh(self, full=False):
        self._refresh_core(full)
        c = self.app.sel_clip()
        self.tabs.setTabVisible(self._mask_tab, bool(c) and c["kind"] != "audio")
        self.mask_panel.load(c, force=full)

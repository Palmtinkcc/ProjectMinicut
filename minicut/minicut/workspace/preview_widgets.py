"""Previews, so nothing has to be tried blind: the effect gallery shows every effect applied to the picture on screen, and the
sound card shows the waveform of the clip and plays just that clip (with its effects) when you press Listen."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.ui import *
from ..render.effects import FX, FX_CATS, new_effect, apply_effects
import hashlib
from ..render import fxcache



def sample_frame(app, w=200):
    """A small BGRA picture to try effects on: what the viewport shows now, or a test card when it shows nothing."""
    img = getattr(getattr(app, "viewport", None), "img", None); arr = None
    if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[0] > 4: arr = img
    elif isinstance(img, QImage) and not img.isNull():
        q = img.convertToFormat(QImage.Format_RGBA8888); a = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine() // 4, 4)[:, :q.width()]
        arr = cv2.cvtColor(a.copy(), cv2.COLOR_RGBA2BGRA)
    if arr is None:
        h = int(w * 9 / 16); arr = np.zeros((h, w, 4), np.uint8); xs = np.linspace(0, 255, w, dtype=np.uint8)
        arr[..., 0] = xs[None, :]; arr[..., 1] = np.linspace(255, 40, h, dtype=np.uint8)[:, None]; arr[..., 2] = 255 - xs[None, :]; arr[..., 3] = 255
        cv2.circle(arr, (w // 2, h // 2), h // 3, (255, 255, 255, 255), -1); cv2.rectangle(arr, (8, 8), (w // 4, h // 3), (30, 30, 30, 255), -1)
    h0, w0 = arr.shape[:2]; s = w / float(w0); arr = cv2.resize(arr, (w, max(2, int(h0 * s))), interpolation=cv2.INTER_AREA)
    if arr.shape[2] == 3: arr = np.dstack([arr, np.full(arr.shape[:2], 255, np.uint8)])
    return np.ascontiguousarray(arr)


def bgra_pixmap(arr):
    rgba = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA); h, w = rgba.shape[:2]
    return QPixmap.fromImage(QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy())


def fx_preview(app, effects, base=None, w=200):
    """The sample picture with a list of effect layers applied."""
    base = sample_frame(app, w) if base is None else base; pw = app.proj.w if app.proj else 1920
    c = {"effects": effects, "kind": "video"}
    try: out = apply_effects(c, base.copy(), k=base.shape[1] / float(pw), lt=0.0, fast=True)
    except Exception as ex: print("[preview]", ex); out = base
    return bgra_pixmap(out)


# ========================================================= effect gallery ===============================================
class _Tile(QWidget):
    clicked = Signal(str)
    def __init__(self, typ, title, pm=None):
        super().__init__(); self.typ, self.title, self.pm = typ, title, pm; self.setFixedSize(148, 112); self.setCursor(Qt.PointingHandCursor); self._h = False; self.setMouseTracking(True)
        self.setToolTip(title)
    def setPixmap(self, pm): self.pm = pm; self.update()
    def enterEvent(self, e): self._h = True; self.update()
    def leaveEvent(self, e): self._h = False; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(c["accent"] if self._h else c["line"]), 1.5 if self._h else 1)); p.setBrush(QColor(c["field_h"] if self._h else c["field"])); p.drawRoundedRect(r, 9, 9)
        clip = QPainterPath(); clip.addRoundedRect(QRectF(5, 5, 138, 78), 6, 6); p.save(); p.setClipPath(clip)
        if self.pm is not None:
            pm = self.pm.scaled(138, 78, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation); p.drawPixmap(5, 5, pm, (pm.width() - 138) // 2, (pm.height() - 78) // 2, 138, 78)
        else: p.fillRect(QRectF(5, 5, 138, 78), QColor(255, 255, 255, 14))        # the picture is made when the tile is on screen
        p.restore()
        p.setPen(QColor(c["text"])); p.setFont(_f(12, True)); p.drawText(QRectF(8, 86, 132, 22), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.title, Qt.ElideRight, 130))
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.typ)


def _clamp(v, lo, hi): return max(lo, min(hi, v))


def _f(px, bold=False):
    f = QFont(QApplication.font()); f.setPixelSize(px); f.setBold(bold); return f


_PREVIEW_CACHE = OrderedDict()          # (effect, picture) -> pixmap: opening the gallery again is instant
_PREVIEW_CACHE_VERSION = 1               # bump when effect preview rendering semantics change
_PREVIEW_DISK_MAX_FILES = 256
_PREVIEW_DISK_MAX_BYTES = 128 * 1024 * 1024
_PREVIEW_DISK_WRITES = 0


def _preview_cache_dir():
    """A shared, per-user disk cache; it lives outside project folders and is safe to delete."""
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(root, "MiniCut", "cache", "effect_previews")


def _preview_disk_path(typ, sig):
    # Include the effect definition/default parameters so changed defaults get a fresh cache entry.
    effect = new_effect(typ)
    meta = repr((typ, FX.get(typ, {}), effect.get("p", {}), _PREVIEW_CACHE_VERSION, sig)).encode("utf-8", "replace")
    return os.path.join(_preview_cache_dir(), hashlib.sha256(meta).hexdigest() + ".png")


def _trim_preview_disk_cache():
    """Bound disk use and evict least-recently-used preview images first."""
    root = _preview_cache_dir()
    try:
        files = [(os.path.getmtime(os.path.join(root, n)), os.path.getsize(os.path.join(root, n)), os.path.join(root, n))
                 for n in os.listdir(root) if n.endswith(".png")]
        total = sum(x[1] for x in files)
        files.sort()  # oldest access first; hits refresh mtime
        while files and (len(files) > _PREVIEW_DISK_MAX_FILES or total > _PREVIEW_DISK_MAX_BYTES):
            _, size, path = files.pop(0)
            try: os.remove(path); total -= size
            except OSError: pass
    except OSError:
        pass


def _load_disk_preview(typ, sig):
    path = _preview_disk_path(typ, sig)
    try:
        pm = QPixmap(path)
        if pm.isNull():
            try: os.remove(path)
            except OSError: pass
            return None
        try: os.utime(path, None)
        except OSError: pass
        return pm
    except Exception:
        return None


def _save_disk_preview(typ, sig, pm):
    global _PREVIEW_DISK_WRITES
    try:
        path = _preview_disk_path(typ, sig)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write to a temporary file first so a crash cannot leave a partial PNG at the cache key.
        tmp = path + ".tmp.png"
        if pm.save(tmp, "PNG"):
            os.replace(tmp, path)
            _PREVIEW_DISK_WRITES += 1
            if _PREVIEW_DISK_WRITES % 8 == 0: _trim_preview_disk_cache()
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as ex:
        print("[effect-preview-cache] disk write skipped:", ex)


class EffectPicker(QFrame):
    """Popup with the effects as pictures of themselves on your current frame: categories on the left, a search box on top,
    three effects per row. The pictures are made only for the tiles on screen. Click one to add it."""
    picked = Signal(str)
    COLS = 3
    def __init__(self, app, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint); self.setAttribute(Qt.WA_DeleteOnClose); c = pal(); self.app = app
        self.setStyleSheet("QFrame#Pick{background:%s;border:1px solid %s;border-radius:12px;}" % (c["card"], c["line"])); self.setObjectName("Pick")
        # Use a stable test card rather than the live timeline frame, allowing previews to be reused across projects.
        self.base = sample_frame(None, 200); self.sig = hashlib.sha256(self.base[::3, ::3].tobytes()).hexdigest(); self.cat = "All"; fxcache.prune()
        self.cats = [x for x in FX_CATS if any(sp["cat"] == x for sp in FX.values())] + sorted({sp["cat"] for sp in FX.values()} - set(FX_CATS))
        v = QVBoxLayout(self); v.setContentsMargins(12, 12, 12, 12); v.setSpacing(8); head = QHBoxLayout(); head.setSpacing(10)
        t = label("Choose an effect", False, 14); t.setStyleSheet(t.styleSheet() + "font-weight:700;"); head.addWidget(t)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search effects\u2026"); self.search.setClearButtonEnabled(True); self.search.setFixedHeight(30)
        self.search.setStyleSheet("QLineEdit{background:%s;border:1px solid %s;border-radius:8px;padding:0 10px;color:%s;font-size:13px;}QLineEdit:focus{border:1px solid %s;}" % (c["field"], c["line"], c["text"], c["accent"]))
        head.addWidget(self.search, 1); v.addLayout(head); body = QHBoxLayout(); body.setSpacing(10)
        self.catlist = QListWidget(); self.catlist.setFixedWidth(166); self.catlist.setFocusPolicy(Qt.NoFocus); self.catlist.setFrameShape(QFrame.NoFrame)
        self.catlist.setStyleSheet("QListWidget{background:transparent;border:none;outline:none;}QListWidget::item{padding:7px 10px;border-radius:7px;color:%s;font-size:13px;}"
                                   "QListWidget::item:hover{background:%s;}QListWidget::item:selected{background:%s;color:#06121a;}" % (c["text"], c["field_h"], c["accent"]))
        self.catlist.addItem("All")
        for x in self.cats: self.catlist.addItem(x)
        self.catlist.setCurrentRow(0); body.addWidget(self.catlist)
        self.sa = QScrollArea(); self.sa.setWidgetResizable(True); self.sa.setFrameShape(QFrame.NoFrame); self.sa.setStyleSheet("background:transparent;")
        self.host = QWidget(); self.host.setStyleSheet("background:transparent;"); self.grid = QGridLayout(self.host); self.grid.setSpacing(8); self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft); self.sa.setWidget(self.host); body.addWidget(self.sa, 1); v.addLayout(body, 1)
        self.none = label("No effect matches", True, 12); self.none.hide(); v.addWidget(self.none)
        self.tiles = {}
        for typ, sp in FX.items():
            tl = _Tile(typ, sp["title"]); tl.setToolTip(sp["title"] + (("\n" + sp["help"]) if sp.get("help") else "")); tl.clicked.connect(self._pick); tl.setParent(self.host); tl.hide(); self.tiles[typ] = tl
        self.shown = []; self._lt = QTimer(self); self._lt.setSingleShot(True); self._lt.timeout.connect(self._load_some)
        self.search.textChanged.connect(self._filter); self.catlist.currentRowChanged.connect(self._filter); self.sa.verticalScrollBar().valueChanged.connect(self._queue)
        self.setFixedSize(724, 620); self._filter(); self.search.setFocus()
    def _count(self, cat): return sum(1 for sp in FX.values() if cat == "All" or sp["cat"] == cat)
    def _match(self, sp, q):
        hay = (sp["title"] + " " + sp["cat"] + " " + sp.get("kw", "") + " " + sp.get("help", "")).lower()
        return all(w in hay for w in q.split())
    def _filter(self, *_):
        row = self.catlist.currentRow(); self.cat = "All" if row <= 0 else self.cats[row - 1]; q = self.search.text().strip().lower()
        for i in range(self.catlist.count()):
            name = "All" if i == 0 else self.cats[i - 1]; self.catlist.item(i).setText("%s  (%d)" % (name, self._count(name)))
        while self.grid.count(): self.grid.takeAt(0)
        order = {x: i for i, x in enumerate(self.cats)}
        vis = [(order.get(sp["cat"], 99), n, typ) for n, (typ, sp) in enumerate(FX.items()) if (self.cat == "All" or sp["cat"] == self.cat) and self._match(sp, q)]
        vis.sort(); self.shown = [typ for _, _, typ in vis]
        for typ, tl in self.tiles.items(): tl.setVisible(typ in self.shown)
        for i, typ in enumerate(self.shown): self.grid.addWidget(self.tiles[typ], i // self.COLS, i % self.COLS)
        self.none.setVisible(not self.shown); self.sa.verticalScrollBar().setValue(0); self._queue()
    def _queue(self, *_):
        if not self._lt.isActive(): self._lt.start(0)
    def _load_some(self):
        top = self.sa.verticalScrollBar().value() - 120; bottom = top + self.sa.viewport().height() + 240; made = 0; more = False
        for typ in self.shown:
            tl = self.tiles[typ]
            if tl.pm is not None: continue
            y = tl.y()
            if y + tl.height() < top or y > bottom: continue
            if made >= 3: more = True; break
            key = typ; pm = _PREVIEW_CACHE.get(key)
            if pm is not None:
                _PREVIEW_CACHE.move_to_end(key)
            else:
                # Patch 38: a stable key (effect + defaults + test card + size + effect source code); the old key held a memory
                # address, so the disk cache never matched in the next run. A failing effect shows the plain test card.
                arr, _hit = fxcache.get_preview(typ)
                if arr is not None:
                    pm = bgra_pixmap(arr); _PREVIEW_CACHE[key] = pm
                    while len(_PREVIEW_CACHE) > 256: _PREVIEW_CACHE.popitem(last=False)
                else: pm = bgra_pixmap(self.base)
            tl.setPixmap(pm); made += 1
        if more: self._lt.start(1)
    def _pick(self, typ): self.picked.emit(typ); self.close()


# ========================================================= sound ========================================================
class WaveView(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self.cid = None; self.pos = None; self.setFixedHeight(84)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); r = QRectF(self.rect())
        p.setPen(Qt.NoPen); p.setBrush(QColor("#17171b")); p.drawRoundedRect(r, 9, 9)
        clip = self.app.sel_clip()
        if not clip: return
        gain = float(self.app.settings["waveform_gain"]); n = max(8, int(r.width() / 3)); mid = r.center().y(); amp = r.height() / 2 - 8; lines = []
        peaks = None
        if clip["kind"] in ("audio", "video") and clip.get("path"): peaks = self.app.thumbs.wave(clip["path"])
        for i in range(n):
            lt = src_time(clip, clip["dur"] * (i + .5) / n)
            if clip["kind"] == "compound": a = self.app.timeline._compound_amp(clip, lt, gain)
            elif peaks is not None and len(peaks):
                idx = int(lt * 100); a = min(1.0, peaks[idx] * gain) if 0 <= idx < len(peaks) else 0.0
            else: a = 0.0
            a = max(1.0, a * amp); x = r.left() + 6 + (r.width() - 12) * i / n; lines.append(QLineF(x, mid - a, x, mid + a))
        p.setPen(QPen(QColor(c["accent"]), 2, Qt.SolidLine, Qt.RoundCap)); p.drawLines(lines)
        if peaks is None and clip["kind"] != "compound": p.setPen(QColor(c["dim"])); p.setFont(_f(12)); p.drawText(r, Qt.AlignCenter, "Reading the sound…")
        if self.pos is not None:
            x = r.left() + 6 + (r.width() - 12) * _clamp(self.pos, 0, 1); p.setPen(QPen(QColor("#ffffff"), 2)); p.drawLine(QPointF(x, r.top() + 4), QPointF(x, r.bottom() - 4))


class SoundPreview(Section):
    """The sound of the selected clip: its waveform, and a Listen button that plays only this clip (effects included)."""
    def __init__(self, app):
        super().__init__("Sound", "sound"); self.app = app; self.cid = None; self.listening = False
        self.wave = WaveView(app); self.body.addWidget(self.wave)
        r = QHBoxLayout(); self.btn = Btn("Listen", "play", "accent", "Play only this clip, with its sound effects", self.toggle); r.addWidget(self.btn); r.addStretch(); self.body.addLayout(r)
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._tick); self._wt = QTimer(self); self._wt.setInterval(500); self._wt.timeout.connect(self.wave.update)
    def load(self, c):
        self.setVisible(c is not None and c.get("kind") in ("audio", "video", "compound"))
        if c is None or c["id"] != self.cid:
            self.stop(); self.cid = c["id"] if c else None
        self.wave.update()
        if self.isVisible() and not self._wt.isActive(): self._wt.start()
    def toggle(self):
        if self.listening: self.stop(); return
        c = self.app.sel_clip()
        if c is None: return
        if self.app.playing: self.app.stop_play()
        shim = copy.copy(self.app.proj); shim.clips = [c]; t0 = c["start"] if not (c["start"] <= self.app.t < c["start"] + c["dur"] - 0.1) else self.app.t
        self._end = c["start"] + c["dur"]; self._t0 = t0; self.app.audio.start(shim, t0); self.listening = True; self.btn.label = "Stop"; self.btn.setIconName("stop"); self.btn.update(); self.timer.start()
    def stop(self):
        if self.listening:
            self.app.audio.stop()
        self.listening = False; self.timer.stop(); self.wave.pos = None; self.btn.label = "Listen"; self.btn.setIconName("play"); self.btn.update(); self.wave.update()
    def _tick(self):
        c = self.app.sel_clip()
        if c is None: self.stop(); return
        now = self.app.audio.clock()
        if now >= self._end: self.stop(); return
        self.wave.pos = (now - c["start"]) / max(0.01, c["dur"]); self.wave.update()

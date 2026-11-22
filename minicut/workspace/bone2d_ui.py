"""Bone2D mode: a full page to build a puppet (pictures joined by bones, with joint points) and animate it, a config dialog,
and the Inspector panel of a Bone2D clip. The rig itself (file format, drawing) is in render/bone2d.py."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.ui import *
from ..shared.ui import _font
from PySide6.QtGui import QShortcut, QIcon, QPainterPath, QPolygonF, QImage, QPixmap
from PySide6.QtCore import QSizeF, QEvent, QSize, QLineF
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QColorDialog, QMenu, QInputDialog, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QStackedWidget, QScrollArea, QToolButton, QSplitter, QFrame, QPushButton, QFileDialog, QMessageBox
from ..shared.widgets import *
from ..render import bone2d as B
from ..render import bone2d_gl as G
from .. import errors as _errors
from ..render import rigaudio as RA
from ..shared import marks as MK
from ..shared import marks_ui as MKU
from .bone2d_sync import CurveBox, SyncMixin


def _toast(app, msg, ms=2200):
    try: app.toast.show_msg(msg, ms)
    except Exception: pass


def rig_dir(app):
    """Folder for the rig files of this project."""
    P = app.proj
    if P.path: base = os.path.join(os.path.dirname(os.path.abspath(P.path)), os.path.splitext(os.path.basename(P.path))[0] + "_bone2d")
    else: base = os.path.join(app.settings["project_folder"], safe_name(P.name) + "_bone2d")
    os.makedirs(base, exist_ok=True); return base


def unique_path(folder, name):
    n = safe_name(name); p = os.path.join(folder, n + B.EXT); i = 2
    while os.path.exists(p): p = os.path.join(folder, "%s %d%s" % (n, i, B.EXT)); i += 1
    return p


def wrap180(a): return (a + 180.0) % 360.0 - 180.0


# ───────────────────────── the document (rig + undo) ─────────────────────────
class RigDoc:
    KEYS = ("name", "w", "h", "parts", "bones", "anims", "cfg", "groups")
    def __init__(self, path, rig):
        self.path = path; self.rig = rig; self.undo = []; self.redo = []; self.dirty = False; self.rev = 0; self.grev = 0
    def snap(self): return copy.deepcopy({k: self.rig[k] for k in self.KEYS})
    def checkpoint(self):
        s = self.snap()
        if not self.undo or self.undo[-1] != s: self.undo.append(s); self.undo = self.undo[-100:]
        self.redo.clear(); self.dirty = True
    def _restore(self, s): self.rig.update(copy.deepcopy(s)); self.touch()
    def do_undo(self):
        if not self.undo: return False
        self.redo.append(self.snap()); self._restore(self.undo.pop()); self.dirty = True; return True
    def do_redo(self):
        if not self.redo: return False
        self.undo.append(self.snap()); self._restore(self.redo.pop()); self.dirty = True; return True
    def touch(self, geom=True):
        """Something changed. geom=False when only bones / the pose changed (the meshes and the picture layout did not), so the GPU vertex data is kept."""
        self.rev += 1
        if geom: self.grev += 1
    def save(self):
        B.save_file(self.path, self.rig); self.dirty = False
    # ---- keys
    def set_key(self, bid, ch, t, v, part=False):
        a = self.anim; tr = (a["ptracks"] if part else a["tracks"]).setdefault(bid, {}).setdefault(ch, [])
        tol = 0.5 / max(1, self.rig["cfg"].get("fps", 30))
        for k in tr:
            if abs(k["t"] - t) < tol: k["v"] = float(v); return k
        k = {"t": float(t), "v": float(v), "e": [0, 0, 1, 1]}; tr.append(k); tr.sort(key=lambda k: k["t"]); return k
    def drop_key(self, bid, ch, k, part=False):
        a = self.anim; trs = (a["ptracks"] if part else a["tracks"]); tr = trs.get(bid, {}).get(ch)
        if tr:
            for j, x in enumerate(tr):
                if x is k: del tr[j]; break
        if tr is not None and not tr: trs[bid].pop(ch, None)
        if bid in trs and not trs[bid]: trs.pop(bid, None)
    anim = None


# ───────────────────────── tool icons ─────────────────────────
TOOLS = [("mesh", "Auto mesh", "Auto mesh: click a picture to cut it into triangles so it can bend. Click it again to add a vertex, right-click a vertex to delete it, drag a vertex to move it."),
         ("vadd", "Pencil", "Pencil (add a vertex): select a picture, then click (or click and drag) on it to put a new mesh point there. The triangles join up by themselves."),
         ("vdel", "Eraser", "Eraser (delete a vertex): click a mesh point to remove it, or drag a box around several. The hole is filled by the points around it."),
         ("vedit", "Edit vertex", "Edit vertex: click or drag a box to select mesh points (Shift = add), drag to move them, Delete removes them. The triangles join up by themselves."),
         ("bone", "Bone", "Bone: select a picture first, then drag to draw a bone for it. Start on the tip of a bone to continue the chain (the new head joins the tip). A bone moves only its own picture."),
         ("select", "Select", "Select: click, or drag a box around several pictures / bones and edit them together (Shift = add). Hold Ctrl and drag a bone to place it without moving the picture."),
         ("link", "Link", "Link: drag from a picture to a bone to glue it. Bone to bone = Link (drag FROM the child TO the mother: the child follows the mother, turning the child moves only the child; a dashed line joins their heads) or Parent (the head joins the tail of the mother) — pick it in the card. Drop on empty space to unlink."),
         ("line", "Line", "Line deform: select a picture, click points along a tail / hair / sleeve, then Enter (or double-click, or the Finish button) — a chain of bones is made for that picture and weighted so it bends smoothly."),
         ("solo", "Solo", "Solo: show only the selected picture"),
         ("lasso", "Lasso", "Lasso: draw around vertices of the selected picture, then give them to the selected bone (weights)."),
         ("physic", "Physic", "Physic: make the selected bone swing like hair / a tail (springs + gravity). Press play to see it."),
         ("weight", "Weight paint", "Weight paint: select a bone, then paint on its picture — red = this bone fully moves it, blue = not at all. Shift (or the Subtract switch) erases.   [ ] = brush size")]


def tool_icon(kind, size=34, col="#e8e8ee"):
    dpr = 2; pm = QPixmap(size * dpr, size * dpr); pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); s = size / 100.0; p.scale(s, s); pen = QPen(QColor(col), 5.5); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin); p.setPen(pen); p.setBrush(Qt.NoBrush)
    def circ(x, y, r): p.drawEllipse(QPointF(x, y), r, r)
    if kind == "mesh":
        p.drawPolygon(QPolygonF([QPointF(50, 14), QPointF(12, 82), QPointF(88, 82)])); p.drawLine(QPointF(50, 14), QPointF(50, 82)); p.setBrush(QColor(col))
        for x, y in ((50, 14), (12, 82), (88, 82)): circ(x, y, 7)
    elif kind == "bone":                                                                                                                   # the same bone as on the canvas: a kite with a ring on its head
        p.drawPolygon(QPolygonF([QPointF(22, 78), QPointF(41, 80), QPointF(84, 18), QPointF(21, 59)])); circ(22, 78, 10)
    elif kind == "vadd":                                                                                                                   # pencil
        p.save(); p.translate(50, 50); p.rotate(45); p.drawRoundedRect(QRectF(-9, -42, 18, 56), 3, 3); p.drawPolygon(QPolygonF([QPointF(-9, 14), QPointF(9, 14), QPointF(0, 40)])); p.drawLine(QPointF(-9, -28), QPointF(9, -28)); p.restore()
    elif kind == "vdel":                                                                                                                   # eraser
        p.save(); p.translate(50, 46); p.rotate(-40); p.drawRoundedRect(QRectF(-36, -16, 72, 32), 6, 6); p.drawLine(QPointF(-4, -16), QPointF(-4, 16)); p.restore(); p.drawLine(QPointF(30, 88), QPointF(84, 88))
    elif kind in ("vedit",):
        p.drawPolygon(QPolygonF([QPointF(50, 14), QPointF(10, 80), QPointF(90, 80)])); p.setBrush(QColor(col))
        for x, y in ((50, 14), (10, 80), (90, 80)): circ(x, y, 6)
        p.setBrush(Qt.NoBrush)
        if kind == "vadd": circ(66, 60, 15); p.drawLine(QPointF(66, 52), QPointF(66, 68)); p.drawLine(QPointF(58, 60), QPointF(74, 60))
        elif kind == "vdel": circ(66, 60, 15); p.drawLine(QPointF(58, 60), QPointF(74, 60))
        else:
            circ(66, 60, 15); p.drawLine(QPointF(66, 50), QPointF(66, 70)); p.drawLine(QPointF(56, 60), QPointF(76, 60))
            p.drawLine(QPointF(66, 50), QPointF(62, 55)); p.drawLine(QPointF(66, 50), QPointF(70, 55)); p.drawLine(QPointF(66, 70), QPointF(62, 65)); p.drawLine(QPointF(66, 70), QPointF(70, 65))
    elif kind == "select":
        p.setBrush(Qt.NoBrush); p.drawPolygon(QPolygonF([QPointF(26, 12), QPointF(26, 82), QPointF(44, 66), QPointF(58, 92), QPointF(68, 86), QPointF(54, 62), QPointF(78, 60)]))
    elif kind == "link":
        circ(18, 50, 8)
        for y in (20, 50, 80): p.drawLine(QPointF(26, 50), QPointF(70, y)); circ(78, y, 6)
    elif kind == "line":
        circ(16, 76, 8); circ(48, 50, 8); circ(82, 22, 8); p.drawLine(QPointF(22, 70), QPointF(42, 56)); p.drawLine(QPointF(55, 44), QPointF(76, 28))
    elif kind == "solo":
        circ(50, 28, 15); path = QPainterPath(); path.moveTo(24, 90); path.lineTo(24, 66); path.quadTo(24, 50, 50, 50); path.quadTo(76, 50, 76, 66); path.lineTo(76, 90); path.closeSubpath(); p.drawPath(path)
    elif kind == "lasso":
        p.drawEllipse(QPointF(48, 40), 36, 26); path = QPainterPath(); path.moveTo(34, 62); path.cubicTo(30, 80, 56, 76, 52, 92); p.drawPath(path); circ(34, 62, 4)
    elif kind == "physic":
        circ(60, 50, 24)
        for y in (34, 50, 66): p.drawLine(QPointF(8, y), QPointF(28 if y == 50 else 24, y))
    elif kind == "weight":
        path = QPainterPath(); path.moveTo(70, 12); path.lineTo(88, 30); path.lineTo(52, 66); path.lineTo(34, 48); path.closeSubpath(); p.drawPath(path)
        path = QPainterPath(); path.moveTo(30, 52); path.cubicTo(16, 54, 14, 72, 6, 82); path.cubicTo(22, 90, 42, 84, 48, 70); p.setBrush(QColor(col)); p.drawPath(path)
    p.end(); return QIcon(pm)


def bone_qcolor(b):
    """Every bone has its own colour (kept in b['color'] if set, else made from its id, so it never changes); its keyframes use the same colour."""
    c = b.get("color")
    if c: return QColor(c)
    import zlib
    h = (zlib.crc32(str(b.get("id", "")).encode("utf-8")) % 997) / 997.0
    return QColor.fromHsvF(h, 0.72, 1.0)


def heat(w):
    """Weight colour like in Blender / Live2D: 0 = blue, 0.5 = green, 1 = red."""
    w = max(0.0, min(1.0, float(w))); return QColor.fromHsvF((1.0 - w) * 0.667, 1.0, 1.0)


_HEAT_LUT = None


def heat_rgba(w, alpha=0.6):
    """(n, 4) premultiplied colours of the weights w (numpy)."""
    global _HEAT_LUT
    if _HEAT_LUT is None:
        _HEAT_LUT = np.array([[heat(i / 255.0).redF(), heat(i / 255.0).greenF(), heat(i / 255.0).blueF()] for i in range(256)], np.float32)
    c = _HEAT_LUT[np.clip((np.asarray(w, np.float32) * 255).astype(np.int32), 0, 255)] * alpha
    return np.concatenate([c, np.full((len(c), 1), alpha, np.float32)], 1)


class _Sig:
    """A tiny signal (the canvas is a plain mixin, so no Qt Signal)."""
    def __init__(self): self.fns = []
    def connect(self, fn): self.fns.append(fn)
    def emit(self, *a):
        for fn in list(self.fns): fn(*a)


class Card(QFrame):
    """A tool card laid over the canvas. It eats every mouse event so that a click on it never reaches the canvas (which would deselect / add points)."""
    def mousePressEvent(self, e): e.accept()
    def mouseReleaseEvent(self, e): e.accept()
    def mouseMoveEvent(self, e): e.accept()
    def mouseDoubleClickEvent(self, e): e.accept()
    def wheelEvent(self, e): e.accept()


_GL_OK = [None]


def gl_ok(app=None):
    """Can the editor draw with OpenGL (and is it allowed)? Decided once."""
    if os.environ.get("BONE2D_CPU"): return False
    if _GL_OK[0] is None:
        try:
            from ..render import bone2d_gl as G
            from PySide6.QtGui import QOpenGLContext
            G.init(); c = QOpenGLContext(); c.setFormat(G.surface_format()); _GL_OK[0] = bool(c.create())
        except Exception as ex:
            print("bone2d: no OpenGL:", ex); _GL_OK[0] = False
    return _GL_OK[0]


# ───────────────────────── the canvas ─────────────────────────
class _CanvasBase:
    """The editing surface. Mixed into RigCanvasGL (QOpenGLWidget: the pictures are drawn by the graphics card as one textured triangle mesh,
    the way Live2D does) and RigCanvasCPU (plain QWidget fallback)."""
    HIT = 9.0

    def __init__(self, page):
        super().__init__(); self.page = page; self.doc = page.doc; self.changed = _Sig(); self.selected = _Sig(); self.setMouseTracking(True); self.setAcceptDrops(True); self.setFocusPolicy(Qt.StrongFocus)
        self.z = 0.5; self.pan = QPointF(0, 0); self.sel = None; self.msel = []; self.last_part = None; self.wbone = None; self.sel_verts = set(); self.tool = "select"; self.solo = False
        self.drag = None; self._space = False; self.line_pts = []; self.lasso = []; self.cur = QPointF(); self.link_to = None; self.box = None; self.brush_pos = None
        self._pm = None; self._pm_key = None; self.setMinimumSize(320, 240); self._chk = None; self.cards = []; self._fitted = False; self._memo = {}; self._ph_memo = None
        self.zbox = []
        for txt, tip, f in (("+", "Zoom in", lambda: self.zoom_by(1.25)), ("=", "Fit the page to the window", self.fit), ("−", "Zoom out", lambda: self.zoom_by(1 / 1.25))):
            b = QPushButton(txt, self); b.setToolTip(tip); b.setFixedSize(34, 34); b.setFocusPolicy(Qt.NoFocus); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:rgba(34,34,40,225);color:#e8e8ee;border:1px solid #3d3d46;border-radius:9px;font-size:18px;font-weight:700}QPushButton:hover{background:rgba(60,60,70,235)}"); b.clicked.connect(f); self.zbox.append(b)
    # ---- state
    @property
    def rig(self): return self.doc.rig
    def mode(self): return self.page.mode
    def ctrl(self): return bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
    def rest_view(self):
        """The bind pose is shown while a bone is being placed (Ctrl held, or any setup work), so the picture does not seem to move."""
        return self.mode() == "setup" or (self.mode() == "animate" and (self.ctrl() or (self.drag is not None and self.drag.get("rest"))))
    def sel_obj(self):
        if not self.sel: return None
        return B.get({"bone": self.rig["bones"], "part": self.rig["parts"], "group": self.rig["groups"]}[self.sel[0]], self.sel[1])
    def sel_items(self):
        """Selected pictures and bones (a folder stands for its pictures), without repeats."""
        out = []
        for k, i in (self.msel or ([self.sel] if self.sel else [])):
            if k == "group": out += [("part", p["id"]) for p in self.rig["parts"] if p.get("group") == i]
            else: out.append((k, i))
        seen = set(); return [x for x in out if not (x in seen or seen.add(x))]
    def cur_part(self):
        """The picture being worked on: the selected picture, or the picture the selected bone belongs to. Nothing selected = none."""
        if not self.sel: return None
        if self.sel[0] == "part": return B.get(self.rig["parts"], self.sel[1])
        if self.sel[0] == "bone":
            b = B.get(self.rig["bones"], self.sel[1]); return B.get(self.rig["parts"], b.get("owner")) if b and b.get("owner") else None
        return None
    def part_locked(self, pt):
        g = B.get(self.rig["groups"], pt.get("group")) if pt.get("group") else None
        return bool(pt.get("lock") or (g and g.get("lock")))
    def pose_now(self):
        r = self.rig; rv = self.rest_view(); key = (self.doc.rev, rv, self.doc.anim["id"], round(self.page.t, 5), self.drag is None)
        if self._memo.get("k") == key: return self._memo["v"]
        rest = B.rest_world(r)
        if rv: v = (rest, rest)
        else:
            ex = None
            if self.drag is None and B.phys_bones(r):
                pk = (self.doc.rev, self.doc.anim["id"], round(self.page.t, 5))
                if self._ph_memo is None or self._ph_memo[0] != pk: self._ph_memo = (pk, B.physics_offsets(r, self.doc.anim, self.page.t))
                ex = self._ph_memo[1]
            v = (B.pose_world(r, self.doc.anim, self.page.t, rest, ex), rest)
        self._memo = {"k": key, "v": v}; return v
    def fit(self):
        r = self.rig; self.z = max(0.05, min((self.width() - 60) / r["w"], (self.height() - 60) / r["h"])); self.pan = QPointF(0, 0); self.update()
    def zoom_by(self, f, pos=None):
        pos = pos or QPointF(self.width() / 2, self.height() / 2); w0 = self.s2w(pos); self.z = max(0.05, min(10.0, self.z * f)); c = self.w2s(*w0); self.pan += QPointF(pos.x() - c.x(), pos.y() - c.y()); self.update()
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._fitted and self.width() > 100: self._fitted = True; self.fit()
        y = self.height() - 12
        for b in reversed(self.zbox): y -= 34; b.move(self.width() - 46, y); y -= 6
        self.on_cards()
    def on_cards(self):
        for c in self.cards: c.adjustSize(); c.move(12, 12) if getattr(c, "_top", False) else c.move(12, self.height() - c.height() - 12)
    def add_card(self, c, top=False): c._top = top; self.cards.append(c); c.setParent(self); c.hide()
    def w2s(self, x, y): return QPointF(self.width() / 2 + self.pan.x() + x * self.z, self.height() / 2 + self.pan.y() + y * self.z)
    def s2w(self, p): return ((p.x() - self.width() / 2 - self.pan.x()) / self.z, (p.y() - self.height() / 2 - self.pan.y()) / self.z)
    def _over_card(self, pos):
        return any(c.isVisible() and c.geometry().contains(pos.toPoint()) for c in self.cards)
    # ---- selection
    def _focus_from(self, s):
        if not s: return
        if s[0] == "bone":
            self.wbone = s[1]; b = B.get(self.rig["bones"], s[1]); self.last_part = b.get("owner") if b else None
        elif s[0] == "part": self.last_part = s[1]
    def select(self, kind, i, add=False):
        s = (kind, i) if kind and i else None; old = (self.sel, list(self.msel))
        if add and s:
            if s in self.msel: self.msel.remove(s); self.sel = self.msel[-1] if self.msel else None
            else: self.msel.append(s); self.sel = s
        else: self.msel = [s] if s else []; self.sel = s
        self._focus_from(self.sel)
        if not (self.sel and self.sel[0] == "part") and not (s and s[0] == "part"): pass
        else: self.sel_verts = set() if (old[0] != self.sel) else self.sel_verts
        if old != (self.sel, self.msel): self.selected.emit()
        self.update()
    def select_many(self, items):
        old = (self.sel, list(self.msel)); self.msel = list(items); self.sel = self.msel[-1] if self.msel else None; self._focus_from(self.sel); self.sel_verts = set()
        if old != (self.sel, self.msel): self.selected.emit()
        self.update()
    # ---- painting helpers
    def _checker(self):
        if self._chk is None:
            pm = QPixmap(20, 20); pm.fill(QColor("#2b2b31")); q = QPainter(pm); q.fillRect(0, 0, 10, 10, QColor("#34343b")); q.fillRect(10, 10, 10, 10, QColor("#34343b")); q.end(); self._chk = QBrush(pm)
        return self._chk
    def solo_set(self):
        if not self.solo: return None
        p = self.cur_part(); return {p["id"]} if p else set()
    def _image(self):
        ds = max(0.1, min(1.0, round(self.z * (self.devicePixelRatioF() or 1.0), 2)))
        if self.drag is not None: ds = min(ds, 0.6)
        rv = self.rest_view(); solo = self.solo_set(); ph = (not rv) and self.drag is None and bool(B.phys_bones(self.rig))
        key = (self.doc.rev, rv, self.doc.anim["id"], round(self.page.t, 4), ds, None if solo is None else tuple(sorted(solo)), ph)
        if key != self._pm_key:
            r = self.rig; arr = B.render_at(r, None if rv else self.doc.anim, self.page.t, ds, None, None, None, solo, ph); h, w = arr.shape[:2]
            self._pm = QImage(arr.data, w, h, arr.strides[0], QImage.Format_ARGB32).copy(); self._pm_key = key
        return self._pm
    def paper_color(self):
        paper = self.rig["cfg"].get("paper", "white"); return QColor("#ffffff") if paper == "white" else QColor("#16161a") if paper == "dark" else None
    def page_box(self):
        r = self.rig; return QRectF(self.w2s(-r["w"] / 2, -r["h"] / 2), QSizeF(r["w"] * self.z, r["h"] * self.z))
    def paint_overlays(self, p):
        """Everything drawn on top of the picture (outlines, mesh, weights, bones, tool state)."""
        p.setRenderHint(QPainter.Antialiasing); r = self.rig; box = self.page_box(); cfg = r["cfg"]
        p.setPen(QPen(QColor("#5a5a66"), 1)); p.setBrush(Qt.NoBrush); p.drawRect(box)
        pose, rest = self.pose_now()
        for k, i in self.sel_items():
            if k == "part":
                pt = B.get(r["parts"], i)
                if pt is not None and cfg.get("show_parts", True): self._draw_part_box(p, pt, pose, rest, main=(self.sel == ("part", i)))
        cp = self.cur_part(); show_dots = self.tool in ("mesh", "vadd", "vdel", "vedit", "lasso", "line", "weight")
        if cp is not None and cp.get("mesh") and (show_dots or self.heat_on()): self._draw_mesh(p, cp, pose, rest, show_dots)
        self._draw_links(p, pose); self._draw_bones(p, pose); self._draw_tool_state(p, pose)
        p.setPen(QColor("#a9a9b6")); p.setFont(_font(11)); tip = next(t[2] for t in TOOLS if t[0] == self.tool)
        if self.mode() == "animate" and self.tool == "select": tip = "Animate: drag a bone tip to rotate it, drag the pivot to move it — keyframes are made at the playhead. Hold Ctrl to place the bone without moving the picture."
        ty = 56 if self.tool in ("mesh", "vadd", "vdel", "vedit", "bone", "line") else 8; p.drawText(QRectF(14, ty, self.width() - 80, 34), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, tip)
        if self.solo: p.setBrush(QColor("#fbbf24")); p.setPen(Qt.NoPen); p.drawRoundedRect(QRectF(self.width() - 70, 8, 56, 20), 6, 6); p.setPen(QColor("#222")); p.drawText(QRectF(self.width() - 70, 8, 56, 20), Qt.AlignCenter, "SOLO")
        if self.ctrl() and self.mode() == "animate": p.setPen(QColor("#22d3ee")); p.drawText(QRectF(14, self.height() - 26, 400, 18), Qt.AlignLeft, "Ctrl: placing bones on the bind pose — the picture does not change")
    def heat_on(self):
        return self.mode() == "setup" and self.wbone is not None and B.get(self.rig["bones"], self.wbone) is not None and ((self.sel and self.sel[0] == "bone") or self.tool == "weight")
    def heat_weights(self, cp):
        m = cp["mesh"]; w = np.zeros(len(m["uv"]), np.float32)
        for i, ws in enumerate(m["w"]):
            for b, x in ws:
                if b == self.wbone: w[i] = x
        return w
    def _part_quad(self, pt, pose, rest):
        sz = B.part_image_size(self.rig, pt)
        if not sz[0]: return None
        M = B.part_matrix(pt, pose, rest); hw, hh = sz[0] / 2, sz[1] / 2
        return [self.w2s(*B.apply_pt(M, x, y)) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
    def _draw_part_box(self, p, pt, pose, rest, main=True):
        q = self._part_quad(pt, pose, rest)
        if not q: return
        p.setPen(QPen(QColor("#2f6bff") if main else QColor("#7aa2ff"), 1.6 if main else 1.2, Qt.SolidLine if main else Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawPolygon(QPolygonF(q))
        if main and self.mode() == "setup" and not self.part_locked(pt) and self.tool == "select" and len(self.msel) <= 1:
            p.setBrush(QColor("#2f6bff")); p.setPen(QPen(QColor("#ffffff"), 1))
            for c in q: p.drawRect(QRectF(c.x() - 4, c.y() - 4, 8, 8))
    def _mesh_world(self, pt, pose, rest):
        m = pt["mesh"]
        return B.vertex_world_rest(pt, m) if self.rest_view() else B._skinned_points(self.rig, pt, pose, rest)
    def _mesh_screen(self, pt, pose, rest):
        P = self._mesh_world(pt, pose, rest); return [self.w2s(float(x), float(y)) for x, y in P]
    def _draw_mesh(self, p, pt, pose, rest, dots):
        m = pt["mesh"]; S = self._mesh_screen(pt, pose, rest)
        if self.heat_on() and not self.is_gl:                              # the GL canvas draws the weight colours on the GPU
            w = self.heat_weights(pt); p.setPen(Qt.NoPen)
            for a, b, c in m["t"]:
                col = heat((w[a] + w[b] + w[c]) / 3.0); col.setAlpha(150); p.setBrush(col); p.drawPolygon(QPolygonF([S[a], S[b], S[c]]))
        p.setPen(QPen(QColor(20, 20, 40, 110), 1)); p.setBrush(Qt.NoBrush); lines = []
        for a, b, c in m["t"]: lines += [QLineF(S[a], S[b]), QLineF(S[b], S[c]), QLineF(S[c], S[a])]
        p.drawLines(lines)
        if dots:
            p.setPen(Qt.NoPen)
            for i, s in enumerate(S):
                if i in self.sel_verts: p.setBrush(QColor("#fbbf24")); p.drawEllipse(s, 5.0, 5.0)
                else: p.setBrush(QColor("#ffffff")); p.drawEllipse(s, 3.0, 3.0)
    def bone_pts(self, b, pose):
        W = pose.get(b["id"])
        if W is None: return None
        return self.w2s(*B.apply_pt(W, 0, 0)), self.w2s(*B.apply_pt(W, b["len"], 0)), W
    def _draw_links(self, p, pose):
        r = self.rig; p.setPen(QPen(QColor(251, 191, 36, 200), 1.6, Qt.DashLine)); p.setBrush(Qt.NoBrush); done = set()
        for b in r["bones"]:
            if b.get("hidden"): continue
            for q in b.get("links", []):
                if (q, b["id"]) in done: continue
                done.add((b["id"], q)); o = B.get(r["bones"], q); a = self.bone_pts(b, pose); c = self.bone_pts(o, pose) if o else None
                if a and c and not o.get("hidden"): p.drawLine(QPointF(a[0].x(), a[0].y()), QPointF(c[0].x(), c[0].y()))                    # Patch 48: head to head
        for k, i in self.sel_items():                                     # a picture glued to a bone: dashed line to the bone's pivot
            if k != "part": continue
            pt = B.get(r["parts"], i); bb = B.get(r["bones"], pt.get("bone")) if pt else None
            if bb is None: continue
            a = self.bone_pts(bb, pose); q = self._part_quad(pt, pose, pose)
            if a and q: p.setPen(QPen(QColor(150, 170, 255, 170), 1.2, Qt.DashLine)); p.drawLine(QPointF(sum(c.x() for c in q) / 4, sum(c.y() for c in q) / 4), a[0])
    def _draw_bones(self, p, pose):
        cfg = self.rig["cfg"]; wd = float(cfg.get("bone_width", 1.0)); chosen = set(i for k, i in self.sel_items() if k == "bone")
        for b in self.rig["bones"]:
            if b.get("hidden"): continue
            bp = self.bone_pts(b, pose)
            if not bp: continue
            h, t, _ = bp; on = b["id"] in chosen; d = QPointF(t.x() - h.x(), t.y() - h.y()); L = math.hypot(d.x(), d.y())
            if L < 1e-3: continue
            n = QPointF(-d.y() / L, d.x() / L); wdt = min(9.0, max(2.5, L * 0.10)) * wd
            poly = QPolygonF([h, QPointF(h.x() + d.x() * 0.15 + n.x() * wdt, h.y() + d.y() * 0.15 + n.y() * wdt), t, QPointF(h.x() + d.x() * 0.15 - n.x() * wdt, h.y() + d.y() * 0.15 - n.y() * wdt)])
            c = bone_qcolor(b); fill = QColor(c); fill.setAlpha(150 if on else 60)
            p.setPen(QPen(QColor("#ffffff") if on else c, 2.4 if on else 1.5)); p.setBrush(fill); p.drawPolygon(poly)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(c, 2.2)); p.drawEllipse(h, 7.0 if not b.get("parent") else 4.0, 7.0 if not b.get("parent") else 4.0)
            if on: p.setBrush(c); p.setPen(Qt.NoPen); p.drawEllipse(t, 4.0, 4.0)
            if self.link_to == b["id"]: p.setPen(QPen(QColor("#fbbf24"), 3)); p.setBrush(Qt.NoBrush); p.drawEllipse(h, 11.0, 11.0)
            if cfg.get("show_names", True): p.setPen(c); p.setFont(_font(10)); p.drawText(QPointF((h.x() + t.x()) / 2 + 8, (h.y() + t.y()) / 2 - 6), b["name"])
    def _draw_tool_state(self, p, pose):
        d = self.drag
        if d and d.get("mode") == "newbone": p.setPen(QPen(QColor("#fbbf24"), 2, Qt.DashLine)); p.drawLine(self.w2s(*d["head"]), self.w2s(*d["tail"]))
        if d and d.get("mode") == "link":
            a = d["src_pt"]; p.setPen(QPen(QColor("#fbbf24"), 2, Qt.DashLine)); p.drawLine(a, self.cur); p.setBrush(QColor("#fbbf24")); p.drawEllipse(self.cur, 4.0, 4.0)
        if self.line_pts:
            p.setPen(QPen(QColor("#fbbf24"), 2)); pts = [self.w2s(*q) for q in self.line_pts]; show = [*pts] + ([self.cur] if not self._over_card(self.cur) else [])
            for a, b in zip(show, show[1:]): p.drawLine(a, b)
            p.setBrush(QColor("#fbbf24"))
            for q in pts: p.drawEllipse(q, 5.0, 5.0)
        if self.lasso: p.setPen(QPen(QColor("#fbbf24"), 1.6, Qt.DashLine)); p.setBrush(QColor(251, 191, 36, 40)); p.drawPolygon(QPolygonF(self.lasso))
        if self.box: p.setPen(QPen(QColor("#2f6bff"), 1.2)); p.setBrush(QColor(47, 107, 255, 40)); p.drawRect(self.box)
        if self.tool == "weight" and self.brush_pos is not None and not self._over_card(self.brush_pos):
            rr = float(self.page.brush_r); sub = bool(self.page.brush_sub or (QApplication.keyboardModifiers() & Qt.ShiftModifier))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#ff6b6b") if sub else QColor("#ffffff"), 1.6)); p.drawEllipse(self.brush_pos, rr, rr); p.setPen(QPen(QColor(0, 0, 0, 120), 1)); p.drawEllipse(self.brush_pos, rr + 1.5, rr + 1.5)
    # ---- hit tests
    def hit(self, pos, parts=True):
        pose, rest = self.pose_now(); chosen = set(self.msel)
        order = sorted([b for b in self.rig["bones"] if not b.get("hidden")], key=lambda b: 0 if ("bone", b["id"]) in chosen else 1)
        sp = self.sel_obj() if (self.sel and self.sel[0] == "part") else None
        if sp is not None and self.tool == "select" and self.mode() == "setup" and not self.part_locked(sp) and len(self.msel) <= 1:
            q = self._part_quad(sp, pose, rest)
            for i, c in enumerate(q or []):
                if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= 7: return ("corner", sp["id"], i)
        for b in order:
            bp = self.bone_pts(b, pose)
            if bp and math.hypot(pos.x() - bp[1].x(), pos.y() - bp[1].y()) <= self.HIT: return ("tail", b["id"])
        for b in order:
            bp = self.bone_pts(b, pose)
            if bp and math.hypot(pos.x() - bp[0].x(), pos.y() - bp[0].y()) <= self.HIT: return (("bone" if b.get("parent") else "head"), b["id"])
        for b in order:
            bp = self.bone_pts(b, pose)
            if bp and self._seg_dist(pos, bp[0], bp[1]) <= 6.0: return ("bone", b["id"])
        if not parts: return None
        for pt in sorted(self.rig["parts"], key=lambda q: -q.get("z", 0)):
            if not pt.get("visible", True) or self.part_locked(pt): continue
            g = B.get(self.rig["groups"], pt.get("group")) if pt.get("group") else None
            if g and g.get("hidden"): continue
            if self.solo and pt["id"] != (self.cur_part() or {}).get("id"): continue
            if self._part_hit(pt, pos, pose, rest): return ("part", pt["id"])
        return None
    @staticmethod
    def _seg_dist(p, a, b):
        ax, ay, bx, by = a.x(), a.y(), b.x(), b.y(); dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        u = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((p.x() - ax) * dx + (p.y() - ay) * dy) / L2))
        return math.hypot(p.x() - (ax + u * dx), p.y() - (ay + u * dy))
    def _part_hit(self, pt, pos, pose, rest):
        im = self.rig["images"].get(pt.get("img"))
        if not im: return False
        img = B._decode(im)
        if img is None: return False
        M = B.part_matrix(pt, pose, rest); x, y = self.s2w(pos)
        try: lx, ly = B.apply_pt(B.inv(M), x, y)
        except Exception: return False
        u, v = int(lx + img.shape[1] / 2), int(ly + img.shape[0] / 2)
        return 0 <= u < img.shape[1] and 0 <= v < img.shape[0] and img[v, u, 3] > 12
    def vertex_at(self, pos, pt):
        pose, rest = self.pose_now(); S = self._mesh_screen(pt, pose, rest); best = None; bd = 9.0
        for i, s in enumerate(S):
            d = math.hypot(pos.x() - s.x(), pos.y() - s.y())
            if d < bd: bd = d; best = i
        return best
    def items_in_box(self, rect):
        """Pictures and bones touched by a screen rectangle."""
        pose, rest = self.pose_now(); out = []
        for pt in self.rig["parts"]:
            if not pt.get("visible", True) or self.part_locked(pt): continue
            g = B.get(self.rig["groups"], pt.get("group")) if pt.get("group") else None
            if g and g.get("hidden"): continue
            q = self._part_quad(pt, pose, rest)
            if q and QPolygonF(q).boundingRect().intersects(rect): out.append(("part", pt["id"]))
        for b in self.rig["bones"]:
            if b.get("hidden"): continue
            bp = self.bone_pts(b, pose)
            if bp and (rect.contains(bp[0]) or rect.contains(bp[1]) or rect.contains(QPointF((bp[0].x() + bp[1].x()) / 2, (bp[0].y() + bp[1].y()) / 2))): out.append(("bone", b["id"]))
        return out
    # ---- editing helpers
    def world_of(self, bid, pose=None):
        pose = pose or self.pose_now()[0]; W = pose.get(bid); return (W[0, 2], W[1, 2]) if W is not None else (0.0, 0.0)
    def link_partners(self, bid):
        """Bones that follow bid through Link (all of the chain below it), not bid itself. Patch 48: a Link has a direction (mother -> child):
        turning or moving the mother takes its children along, turning a child moves only that child. A Link made before Patch 48 has no direction and stays two-way."""
        by = {b["id"]: b for b in self.rig["bones"]}; seen = {bid}; stack = [bid]
        while stack:
            x = stack.pop(); bx = by.get(x)
            if bx is None: continue
            for q in bx.get("links", []):
                if q not in by or q in seen: continue
                directed = q in bx.get("lkids", []) or x in by[q].get("lkids", [])
                if (not directed) or q in bx.get("lkids", []): seen.add(q); stack.append(q)
        seen.discard(bid); return [by[q] for q in seen]
    def _link_down(self, bid):
        """The bones below bid in the DIRECTED links only (used to refuse a loop)."""
        by = {b["id"]: b for b in self.rig["bones"]}; seen = set(); stack = [bid]
        while stack:
            x = stack.pop()
            for q in by.get(x, {}).get("lkids", []):
                if q in by and q not in seen: seen.add(q); stack.append(q)
        return seen
    def set_bone_rest(self, b, head=None, angle=None, length=None, keep_children=False):
        """Change the rest pose of bone b (head = world point, angle = world degrees, length). The child bones follow it, unless keep_children."""
        r = self.rig; rest = B.rest_world(r); kids = B.children_of(r, b["id"]); old = {k["id"]: rest[k["id"]] for k in kids}
        par = rest.get(b.get("parent")) if b.get("parent") else None; cur = rest[b["id"]]
        hx, hy = head if head else (cur[0, 2], cur[1, 2]); ang = angle if angle is not None else B.mat_angle(cur)
        loc = (B.inv(par) if par is not None else np.eye(3)) @ B.mat(hx, hy, ang); old_len = b["len"]
        b["x"], b["y"], b["rot"] = float(loc[0, 2]), float(loc[1, 2]), float(B.mat_angle(loc))
        if length is not None: b["len"] = max(1.0, float(length))
        if keep_children:
            nb = B.rest_world(r)[b["id"]]
            for k in kids: l2 = B.inv(nb) @ old[k["id"]]; k["x"], k["y"], k["rot"] = float(l2[0, 2]), float(l2[1, 2]), float(B.mat_angle(l2))
    def key_bone(self, b, ch, v): self.doc.set_key(b["id"], ch, self.page.t, v)
    def rotate_bone_to(self, b, wp):
        pose, rest = self.pose_now(); hx, hy = self.world_of(b["id"], pose); th_w = math.degrees(math.atan2(wp[1] - hy, wp[0] - hx))
        par = pose.get(b.get("parent")) if b.get("parent") else None; th_p = B.mat_angle(par) if par is not None else 0.0
        cur = B.bone_channels(self.doc.anim, b["id"], self.page.t)["rot"]; v = (th_w - th_p) - b["rot"]; v = cur + wrap180(v - cur)
        sn = float(self.rig["cfg"].get("snap_deg", 0) or 0)
        if sn > 0: v = round(v / sn) * sn
        self.key_bone(b, "rot", v)
    def move_bone_to(self, b, wp):
        if b.get("parent"): return                                        # the head of a child sits on the tail of its mother
        pose, rest = self.pose_now(); self.key_bone(b, "x", wp[0] - b["x"]); self.key_bone(b, "y", wp[1] - b["y"])
    def end_at(self, pos, bid):
        """Which end of bone bid is nearer to the screen point: 'head' or 'tail'."""
        b = B.get(self.rig["bones"], bid); bp = self.bone_pts(b, self.pose_now()[0]) if b else None
        if not bp: return "head"
        return "tail" if math.hypot(pos.x() - bp[1].x(), pos.y() - bp[1].y()) < math.hypot(pos.x() - bp[0].x(), pos.y() - bp[0].y()) else "head"
    def link(self, src, target, src_end="head", tgt_end="tail"):
        """src = ('part'|'bone', id); target = bone id or None (unlink). A picture is glued to a bone; bones are Linked or Parented (page.link_mode)."""
        r = self.rig; kind, i = src
        if kind == "part":
            pt = B.get(r["parts"], i)
            if pt is None: return
            pt["bone"] = target
            if pt.get("mesh") and not any(pt["mesh"]["w"]): pt["mesh"]["w"] = [([[target, 1.0]] if target else []) for _ in pt["mesh"]["uv"]]
            return
        b = B.get(r["bones"], i)
        if b is None: return
        if self.page.link_mode == "parent":
            # the end you grab decides the roles: grab a HEAD = this bone is the child, its head joins the tail (or the head) of the bone you drop on;
            # grab a TAIL = this bone is the mother, the bone you drop on becomes its child and its head joins this tail.
            child, mother, pat = i, target, ("head" if (src_end == "head" and tgt_end == "head") else "tail")
            if target and src_end == "tail": child, mother, pat = target, i, "tail"
            if mother is not None and (child == mother or mother in B.descendants(r, child)): return
            cb = B.get(r["bones"], child)
            if cb is None: return
            rest = B.rest_world(r); w = rest[child]; cb["parent"] = mother; cb["pat"] = pat if mother else None; par = rest.get(mother) if mother else None
            loc = (B.inv(par) if par is not None else np.eye(3)) @ w; cb["x"], cb["y"], cb["rot"] = float(loc[0, 2]), float(loc[1, 2]), float(B.mat_angle(loc))
        else:
            o = B.get(r["bones"], target) if target else None
            if o is None:
                b["links"] = []; b["lkids"] = []
                for x in r["bones"]:
                    if i in x["links"]: x["links"].remove(i)
                    x["lkids"] = [q for q in x.get("lkids", []) if q != i]
                return
            if o["id"] == i: return
            self._set_link(o, b)                                                          # Patch 49: drag FROM the child TO the mother (like a picture -> bone): the bone you drag follows the bone you drop on
    def _set_link(self, mom, kid):
        """Make `mom` the mother and `kid` the child of a Link. The same pair in the same direction = unlink; the other direction (or an old two-way Link) = flips it; a loop is refused."""
        mom.setdefault("lkids", []); kid.setdefault("lkids", []); mi, ki = mom["id"], kid["id"]
        if ki in mom["links"] or mi in kid["links"]:
            if ki in mom["lkids"]: mom["links"] = [x for x in mom["links"] if x != ki]; kid["links"] = [x for x in kid["links"] if x != mi]; mom["lkids"].remove(ki)          # same pair, same direction again = unlink
            else:
                was = mi in kid["lkids"]; kid["lkids"] = [x for x in kid["lkids"] if x != mi]
                if mi in self._link_down(ki):
                    if was: kid["lkids"].append(mi)
                    return
                if ki not in mom["links"]: mom["links"].append(ki)
                if mi not in kid["links"]: kid["links"].append(mi)
                mom["lkids"].append(ki)
        else:
            if mi in self._link_down(ki): return                                          # would make a loop
            mom["links"].append(ki); kid["links"].append(mi); mom["lkids"].append(ki)
    def flip_links(self, bid):
        """Turn the direction of every Link of bone bid round (mother <-> child). A Link without a direction becomes: bid is the child."""
        r = self.rig; b = B.get(r["bones"], bid)
        if b is None: return
        for q in list(b.get("links", [])):
            o = B.get(r["bones"], q)
            if o is None: continue
            b.setdefault("lkids", []); o.setdefault("lkids", [])
            b_mother = q in b["lkids"]; b_child = bid in o["lkids"]
            b["lkids"] = [x for x in b["lkids"] if x != q]; o["lkids"] = [x for x in o["lkids"] if x != bid]
            if b_mother or not b_child:                                       # bid was the mother (or there was no direction): bid becomes the child
                o["lkids"].append(bid)
            else: b["lkids"].append(q)                                        # bid was the child: bid becomes the mother
    def _new_bone(self, name, parent, owner, head, tail):
        r = self.rig; L = max(4.0, math.hypot(tail[0] - head[0], tail[1] - head[1]))
        nb = {"id": new_id(), "name": name, "parent": parent, "x": 0.0, "y": 0.0, "rot": 0.0, "len": float(L), "owner": owner, "links": [], "hidden": False}
        r["bones"].append(nb); par = B.rest_world(r).get(parent) if parent else None
        loc = (B.inv(par) if par is not None else np.eye(3)) @ B.mat(head[0], head[1], math.degrees(math.atan2(tail[1] - head[1], tail[0] - head[0])))
        nb["x"], nb["y"], nb["rot"] = float(loc[0, 2]), float(loc[1, 2]), float(B.mat_angle(loc)); return nb
    def _bone_added(self, part):
        """The picture got a bone: it follows it (glue) and, if it has a mesh without weights, gets weights from its bones."""
        if part is None: return
        mine = [b for b in self.rig["bones"] if b.get("owner") == part["id"]]
        if not part.get("bone") and mine: part["bone"] = mine[0]["id"]
        m = part.get("mesh")
        if m and not m.get("painted"): B.auto_weights(self.rig, part, {b["id"] for b in mine}, self.page.sharp)       # until the weights are painted by hand they follow the bones
    def finish_line(self):
        pts = list(self.line_pts); self.line_pts = []
        if len(pts) < 2: self.update(); return
        part = self.cur_part()
        if part is None: self.page.toast("Select a picture first — the bones belong to it"); self.update(); return
        r = self.rig; n = max(1, int(self.page.line_n)); P = np.array(pts, float); seg = np.hypot(*np.diff(P, axis=0).T); cum = np.r_[0, np.cumsum(seg)]; tot = cum[-1]
        if tot < 4: self.update(); return
        ss = np.linspace(0, tot, n + 1); Q = np.c_[np.interp(ss, cum, P[:, 0]), np.interp(ss, cum, P[:, 1])]
        self.doc.checkpoint(); parent = None; ids = []
        for k in range(n):
            nb = self._new_bone("Line %d" % (len([b for b in r["bones"] if b["name"].startswith("Line")]) + 1), parent, part["id"], Q[k], Q[k + 1]); ids.append(nb["id"]); parent = nb["id"]
        if self.page.line_weight:
            self.page.ensure_mesh(part, quiet=True); B.auto_weights(r, part, set(ids) | {b["id"] for b in r["bones"] if b.get("owner") == part["id"]}, self.page.sharp)
        self._bone_added(part); self.doc.touch(); self.select("bone", ids[0]); self.changed.emit(); self.update()
    def paint_at(self, pos, erase):
        cp = self.cur_part(); b = B.get(self.rig["bones"], self.wbone) if self.wbone else None
        if cp is None or b is None: return
        if not cp.get("mesh"): self.page.ensure_mesh(cp, quiet=True)
        if not cp.get("mesh"): self.update(); return
        pose, rest = self.pose_now(); W = self._mesh_world(cp, pose, rest); sx = self.width() / 2 + self.pan.x() + W[:, 0] * self.z; sy = self.height() / 2 + self.pan.y() + W[:, 1] * self.z
        d = np.hypot(sx - pos.x(), sy - pos.y()); rr = float(self.page.brush_r); idx = np.nonzero(d < rr)[0]
        if not len(idx): self.update(); return                              # nothing under the brush: still redraw, or the brush ring stays behind and the canvas looks frozen
        hits = [(int(i), float((1.0 - d[i] / rr) ** 1.3)) for i in idx]
        B.paint_weights(cp["mesh"], hits, b["id"], (-1 if erase else 1) * float(self.page.brush_str) / 100.0 * 0.5, normalize=bool(getattr(self.page, "auto_norm", False))); cp["mesh"]["painted"] = True; self.doc.touch(); self.page.doc.dirty = True; self.update()
    # ---- mesh point tools (Add / Delete / Edit vertex)
    def _mesh_ok(self, m):
        n = len(m.get("uv", [])); t = m.get("t") or []
        return n >= 4 and len(t) > 0 and all(len(x) == 3 and 0 <= min(x) and max(x) < n for x in t) and len(m.get("v", [])) == n and len(m.get("w", [])) == n
    def _retri_checked(self, cp, old_mesh):
        """Join the vertices into triangles again; if that gives no usable mesh, go back to the mesh as it was."""
        try: B.retriangulate(self.rig, cp)
        except Exception as ex: print("bone2d: retriangulate failed:", ex)
        if not self._mesh_ok(cp["mesh"]): cp["mesh"] = old_mesh; self.sel_verts = set(); self.page.toast("Could not join those points into triangles — undone")
    def _delete_verts(self, cp, idx):
        idx = set(idx)
        if not idx: return False
        if len(cp["mesh"]["uv"]) - len(idx) < 4: self.page.toast("A mesh needs at least 4 points"); return False
        old = copy.deepcopy(cp["mesh"]); self.doc.checkpoint(); B.mesh_del_vertices(self.rig, cp, idx); self.sel_verts = set()
        if not self._mesh_ok(cp["mesh"]): cp["mesh"] = old; self.page.toast("Could not join the rest into triangles — nothing deleted")
        self.doc.touch(); self.doc.dirty = True; self.page.update_title(); self.changed.emit(); self.page.verts_changed(); self.update(); return True
    def delete_selected_verts(self):
        cp = self.cur_part()
        if cp is None or not cp.get("mesh"): return
        if not self.sel_verts: self.page.toast("Select mesh points first"); return
        self._delete_verts(cp, set(self.sel_verts))
    def _vertex_press(self, pos, wp, mods):
        r = self.rig; tool = self.tool; shift = bool(mods & Qt.ShiftModifier); cp = self.cur_part()
        if cp is None or not cp.get("mesh") or self.sel != ("part", cp["id"]):
            h = self.hit(pos)
            if h and h[0] == "part":
                self.select("part", h[1]); pt = B.get(r["parts"], h[1]); self.page.ensure_mesh(pt); self.sel_verts = set(); self.update()
            else: self.page.toast("Click a picture first")
            return
        i = self.vertex_at(pos, cp)
        if tool == "vdel":
            if i is not None: self._delete_verts(cp, {i})
            else: self.drag = {"mode": "vbox", "p0": pos, "moved": False, "act": "del", "add": False}; self.box = None
            return
        if tool == "vedit":
            if i is None: self.drag = {"mode": "vbox", "p0": pos, "moved": False, "act": "sel", "add": shift}; self.box = None; return
            if shift:
                self.sel_verts ^= {i}; self.page.verts_changed(); self.update()
                if i not in self.sel_verts: return
            elif i not in self.sel_verts: self.sel_verts = {i}
        else:                                                                           # vadd
            if i is None:
                pose, rest = self.pose_now(); lx, ly = B.apply_pt(B.inv(B.part_matrix(cp, rest, rest)), wp[0], wp[1]); iw, ih = B.part_image_size(r, cp); gx, gy = iw * 0.03 + 3, ih * 0.03 + 3
                if abs(lx) > iw / 2.0 + gx or abs(ly) > ih / 2.0 + gy: self.page.toast("Click on the picture to add a point"); return
                old = copy.deepcopy(cp["mesh"]); self.doc.checkpoint(); B.mesh_add_vertex(r, cp, lx, ly)
                if not self._mesh_ok(cp["mesh"]): cp["mesh"] = old; self.page.toast("Could not add a point there"); return
                i = len(cp["mesh"]["uv"]) - 1
            else: self.doc.checkpoint()                                              # moving a point that is already there
            self.sel_verts = {i}
        self.page.verts_changed(); m = cp["mesh"]; old = copy.deepcopy(m)
        if tool == "vedit": self.doc.checkpoint()
        self.drag = {"mode": "vert", "i": i, "w0": wp, "retri": True, "old_mesh": old, "moved": False, "orig": {j: (list(m["uv"][j]), list(m["v"][j])) for j in (self.sel_verts or {i})}}; self.doc.touch(); self.changed.emit(); self.update()
    # ---- mouse
    def mousePressEvent(self, e):
        self.setFocus(); pos = e.position(); self.cur = pos
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self.drag = {"mode": "pan", "p0": pos, "pan0": QPointF(self.pan)}; self.setCursor(Qt.ClosedHandCursor); return
        r = self.rig; wp = self.s2w(pos); tool = self.tool; ctrl = self.ctrl(); setup = self.mode() == "setup"; mods = e.modifiers()
        if e.button() == Qt.RightButton:
            if tool == "mesh":
                cp = self.cur_part()
                if cp is not None and cp.get("mesh"):
                    i = self.vertex_at(pos, cp)
                    if i is not None: self.doc.checkpoint(); B.mesh_del_vertices(r, cp, {i}); self.doc.touch(); self.changed.emit(); self.update()
            elif tool == "line" and self.line_pts: self.line_pts.pop(); self.update()
            return
        if e.button() != Qt.LeftButton: return
        if tool == "bone":
            cp = self.cur_part()
            if cp is None: self.page.toast("Select a picture first — a bone belongs to one picture and moves only that picture"); return
            parent = None; head = wp; pose = B.rest_world(r)
            for b in r["bones"]:                                  # start on the tip of a bone: the new bone continues it (its head joins the tip)
                bp = self.bone_pts(b, pose)
                if bp and math.hypot(pos.x() - bp[1].x(), pos.y() - bp[1].y()) <= 12 and not b.get("hidden"): head = B.apply_pt(bp[2], b["len"], 0); parent = b["id"]; break
            self.doc.checkpoint(); self.drag = {"mode": "newbone", "head": head, "tail": head, "parent": parent, "part": cp["id"]}; return
        if tool == "line":
            if self.cur_part() is None: self.page.toast("Select a picture first — the bones belong to it"); return
            if e.type() == QEvent.MouseButtonDblClick and self.line_pts: self.finish_line(); return
            self.line_pts.append(wp); self.update(); return
        if tool == "weight":
            if self.cur_part() is None or not self.wbone: self.page.toast("Select a bone first (Select tool) — then paint its weights"); return
            self.doc.checkpoint(); self.drag = {"mode": "paint", "erase": bool(self.page.brush_sub or (mods & Qt.ShiftModifier))}; self.paint_at(pos, self.drag["erase"]); return
        if tool in ("vadd", "vdel", "vedit"): self._vertex_press(pos, wp, mods); return
        if tool == "lasso":
            if self.cur_part() is None: self.page.toast("Select a picture first"); return
            self.page.ensure_mesh(self.cur_part()); self.lasso = [pos]; self.drag = {"mode": "lasso", "mods": mods}; return
        if tool == "mesh":
            cp = self.cur_part(); h = self.hit(pos)
            if cp is not None and cp.get("mesh") and self.sel and self.sel == ("part", cp["id"]):
                i = self.vertex_at(pos, cp)
                if i is not None:
                    if i not in self.sel_verts and not (mods & Qt.ShiftModifier): self.sel_verts = {i}
                    elif mods & Qt.ShiftModifier: self.sel_verts ^= {i}
                    self.doc.checkpoint(); self.drag = {"mode": "vert", "i": i, "w0": wp, "orig": {j: (list(cp["mesh"]["uv"][j]), list(cp["mesh"]["v"][j])) for j in (self.sel_verts or {i})}}; self.update(); return
                if h and h[0] == "part" and h[1] == cp["id"]:      # click on the picture, away from vertices: add one
                    pose, rest = self.pose_now(); lx, ly = B.apply_pt(B.inv(B.part_matrix(cp, rest, rest)), wp[0], wp[1])
                    self.doc.checkpoint(); B.mesh_add_vertex(r, cp, lx, ly); self.doc.touch(); self.changed.emit(); self.update(); return
            if h and h[0] == "part":
                self.select("part", h[1]); self.page.ensure_mesh(B.get(r["parts"], h[1])); self.update()
            return
        # select / link / physic: pick things
        h = self.hit(pos)
        if tool == "link":
            if h is None: return
            kind = "part" if h[0] == "part" else "bone"; self.select(kind, h[1]); pose, rest = self.pose_now()
            if kind == "part": q = self._part_quad(B.get(r["parts"], h[1]), pose, rest); sp = QPointF(sum(c.x() for c in q) / 4, sum(c.y() for c in q) / 4) if q else pos
            else:
                bp = self.bone_pts(B.get(r["bones"], h[1]), pose); end = self.end_at(pos, h[1]); sp = (bp[1] if end == "tail" else bp[0]) if bp else pos
            self.drag = {"mode": "link", "src": (kind, h[1]), "src_pt": sp, "src_end": (self.end_at(pos, h[1]) if kind == "bone" else "head")}; return
        add = bool(mods & Qt.ShiftModifier)
        if h is None:
            if tool == "select": self.drag = {"mode": "box", "p0": pos, "add": add, "moved": False}; self.box = None
            return
        kind, i = h[0], h[1]; item = ("part" if kind in ("corner", "part") else "bone", i)
        if add: self.select(item[0], i, add=True); return
        if item not in self.msel or len(self.sel_items()) <= 1: self.select(item[0], i)
        elif item != self.sel: self.sel = item; self._focus_from(item); self.selected.emit()
        if tool == "physic": return
        rest_edit = setup or ctrl; self.doc.checkpoint(); items = self.sel_items()
        if len(items) > 1 and kind in ("part", "bone", "head"):
            pose0, rest0 = self.pose_now(); orig = []
            for k2, i2 in items:
                if k2 == "part": pt = B.get(r["parts"], i2); orig.append((k2, i2, (pt["x"], pt["y"])))
                else: orig.append((k2, i2, self.world_of(i2, B.rest_world(r) if rest_edit else None)))
            self.drag = {"mode": "multi", "w0": wp, "items": orig, "rest": rest_edit and not setup, "moved": False}; return
        self.drag = {"mode": kind, "id": i, "w0": wp, "moved": False, "rest": rest_edit and not setup, "alt": bool(mods & Qt.AltModifier), "shift": bool(mods & Qt.ShiftModifier)}
        if kind == "part":
            pt = B.get(r["parts"], i); self.drag["p0"] = (pt["x"], pt["y"])
            if not setup and not pt.get("bone"): self.drag = None
        if kind == "corner":
            pt = B.get(r["parts"], i); self.drag.update(c0=(pt["x"], pt["y"]), s0=(pt["sx"], pt["sy"]), d0=max(8.0, math.hypot(wp[0] - pt["x"], wp[1] - pt["y"])))
        if kind in ("head", "tail", "bone"):
            b = B.get(r["bones"], i); base = B.rest_world(r) if rest_edit else None; self.drag["h0"] = self.world_of(i, base)
            pose0 = base or self.pose_now()[0]; W0 = pose0[i]; self.drag["a0"] = B.mat_angle(W0); self.drag["rot0"] = B.bone_channels(self.doc.anim, i, self.page.t)["rot"]
            self.drag["pt"] = {q["id"]: (self.world_of(q["id"], base), B.mat_angle((base or self.pose_now()[0])[q["id"]])) for q in self.link_partners(i)}
    def mouseMoveEvent(self, e):
        pos = e.position(); self.cur = pos; d = self.drag
        if d is None:
            self.brush_pos = pos
            if self.tool in ("line", "weight"): self.update()
            h = self.hit(pos) if (not self._space and self.tool in ("select", "link", "physic") and not self._over_card(pos)) else None
            self.setCursor(Qt.OpenHandCursor if self._space else Qt.BlankCursor if self.tool == "weight" else Qt.CrossCursor if self.tool in ("bone", "line", "lasso", "mesh", "vadd", "vdel", "vedit") else (Qt.PointingHandCursor if h else Qt.ArrowCursor)); return
        if d["mode"] == "pan": self.pan = QPointF(d["pan0"].x() + pos.x() - d["p0"].x(), d["pan0"].y() + pos.y() - d["p0"].y()); self.update(); return
        wp = self.s2w(pos); r = self.rig
        if d["mode"] == "newbone": d["tail"] = wp; self.update(); return
        if d["mode"] == "lasso": self.lasso.append(pos); self.update(); return
        if d["mode"] == "paint": self.brush_pos = pos; self.paint_at(pos, d["erase"]); return
        if d["mode"] == "box":
            if not d["moved"] and math.hypot(pos.x() - d["p0"].x(), pos.y() - d["p0"].y()) < 4: return
            d["moved"] = True; self.box = QRectF(d["p0"], pos).normalized(); self.update(); return
        if d["mode"] == "vbox":
            if not d["moved"] and math.hypot(pos.x() - d["p0"].x(), pos.y() - d["p0"].y()) < 4: return
            d["moved"] = True; self.box = QRectF(d["p0"], pos).normalized(); self.update(); return
        if d["mode"] == "link":
            h = self.hit(pos, parts=False); nt = h[1] if h else None; self.link_to = nt if (nt and nt != d["src"][1]) else None; self.update(); return
        d["moved"] = True; animate = self.mode() == "animate" and not d.get("rest"); geom = True
        if d["mode"] == "vert":
            cp = self.cur_part(); pose, rest = self.pose_now(); M = B.inv(B.part_matrix(cp, rest, rest)); a = B.apply_pt(M, *d["w0"]); b = B.apply_pt(M, *wp); dx, dy = b[0] - a[0], b[1] - a[1]
            for j, (uv0, v0) in d["orig"].items(): cp["mesh"]["uv"][j] = [uv0[0] + dx, uv0[1] + dy]; cp["mesh"]["v"][j] = [v0[0] + dx, v0[1] + dy]
        elif d["mode"] == "multi":
            dx, dy = wp[0] - d["w0"][0], wp[1] - d["w0"][1]
            if QApplication.keyboardModifiers() & Qt.ShiftModifier: dx, dy = (dx, 0) if abs(dx) >= abs(dy) else (0, dy)
            for k, i, o in d["items"]:
                if k == "part":
                    if not animate: pt = B.get(r["parts"], i); pt["x"], pt["y"] = o[0] + dx, o[1] + dy
                else:
                    b = B.get(r["bones"], i)
                    if b is None or b.get("parent"): continue
                    if animate: self.move_bone_to(b, (o[0] + dx, o[1] + dy)); geom = False
                    else: self.set_bone_rest(b, head=(o[0] + dx, o[1] + dy)); geom = False
            if not animate and any(k == "part" for k, _i, _o in d["items"]): geom = True
        elif d["mode"] == "corner":
            pt = B.get(r["parts"], d["id"]); k = max(0.05, math.hypot(wp[0] - d["c0"][0], wp[1] - d["c0"][1]) / d["d0"]); pt["sx"], pt["sy"] = d["s0"][0] * k, d["s0"][1] * k
        elif d["mode"] == "part":
            pt = B.get(r["parts"], d["id"]); dx, dy = wp[0] - d["w0"][0], wp[1] - d["w0"][1]
            if animate:
                b = B.get(r["bones"], pt["bone"]); h0 = d.setdefault("h0", self.world_of(b["id"])); self.move_bone_to(b, (h0[0] + dx, h0[1] + dy)); geom = False
            else:
                if QApplication.keyboardModifiers() & Qt.ShiftModifier: dx, dy = (dx, 0) if abs(dx) >= abs(dy) else (0, dy)
                pt["x"], pt["y"] = d["p0"][0] + dx, d["p0"][1] + dy
        else:
            b = B.get(r["bones"], d["id"]); geom = False
            if b is None: return
            if animate:
                if d["mode"] == "tail":
                    self.rotate_bone_to(b, wp); dv = B.bone_channels(self.doc.anim, b["id"], self.page.t)["rot"] - d["rot0"]
                    px, py = d["h0"]; c, s_ = math.cos(math.radians(dv)), math.sin(math.radians(dv))
                    for q in self.link_partners(b["id"]):                              # like a Blender parent: every linked bone swings round the pivot of the bone you turn, not round its own
                        self.key_bone(q, "rot", d.setdefault("qrot", {}).setdefault(q["id"], B.bone_channels(self.doc.anim, q["id"], self.page.t)["rot"]) + dv)
                        if not q.get("parent"): (qx, qy), _qa = d["pt"][q["id"]]; self.move_bone_to(q, (px + (qx - px) * c - (qy - py) * s_, py + (qx - px) * s_ + (qy - py) * c))
                elif not b.get("parent"):
                    h0 = d["h0"]; tx, ty = h0[0] + wp[0] - d["w0"][0], h0[1] + wp[1] - d["w0"][1]; self.move_bone_to(b, (tx, ty))
                    for q in self.link_partners(b["id"]): self.move_bone_to(q, (d["pt"][q["id"]][0][0] + tx - h0[0], d["pt"][q["id"]][0][1] + ty - h0[1]))
            elif d["mode"] == "tail":
                hx, hy = self.world_of(b["id"], B.rest_world(r)); ang = math.degrees(math.atan2(wp[1] - hy, wp[0] - hx)); L = math.hypot(wp[0] - hx, wp[1] - hy)
                sn = float(r["cfg"].get("snap_deg", 0) or 0)
                if sn > 0: ang = round(ang / sn) * sn
                self.set_bone_rest(b, angle=ang, length=(None if d["shift"] else L)); da = ang - d["a0"]; c, s_ = math.cos(math.radians(da)), math.sin(math.radians(da)); px, py = d["h0"]
                for q in self.link_partners(b["id"]):
                    (qx, qy), qa = d["pt"][q["id"]]; self.set_bone_rest(q, head=((px + (qx - px) * c - (qy - py) * s_), (py + (qx - px) * s_ + (qy - py) * c)), angle=qa + da)
            elif not b.get("parent"):
                h0 = d["h0"]; tx, ty = h0[0] + wp[0] - d["w0"][0], h0[1] + wp[1] - d["w0"][1]; self.set_bone_rest(b, head=(tx, ty), keep_children=(d["mode"] == "head" and d["alt"]))
                for q in self.link_partners(b["id"]): self.set_bone_rest(q, head=(d["pt"][q["id"]][0][0] + tx - h0[0], d["pt"][q["id"]][0][1] + ty - h0[1]))
        self.doc.touch(geom=geom); self.changed.emit(); self.update()
    def mouseReleaseEvent(self, e):
        d = self.drag; self.drag = None; self.unsetCursor(); self.link_to = None
        if d is None: return
        pos = e.position(); r = self.rig
        if d["mode"] == "newbone":
            h, t = d["head"], d["tail"]; L = math.hypot(t[0] - h[0], t[1] - h[1])
            if L < 6: L = 100.0; t = (h[0] + L, h[1])
            part = B.get(r["parts"], d.get("part")); nb = self._new_bone("Bone %d" % (len(r["bones"]) + 1), d["parent"], d.get("part"), h, t); self._bone_added(part)
            self.doc.touch(); self.select("bone", nb["id"]); self.changed.emit(); self.update(); return
        if d["mode"] == "box":
            self.box = None
            if d["moved"]:
                found = self.items_in_box(QRectF(d["p0"], pos).normalized())
                self.select_many(list(dict.fromkeys(self.msel + found)) if d["add"] else found)
            elif not d["add"]: self.select(None, None)
            self.update(); return
        if d["mode"] == "vbox":
            rect = self.box; self.box = None; cp = self.cur_part()
            if cp is not None and cp.get("mesh"):
                if d["moved"] and rect is not None:
                    pose, rest = self.pose_now(); S = self._mesh_screen(cp, pose, rest); inside = {i for i, q in enumerate(S) if rect.contains(q)}
                    if d["act"] == "del":
                        if inside: self._delete_verts(cp, inside)
                    else: self.sel_verts = (self.sel_verts | inside) if d["add"] else inside
                elif d["act"] == "sel" and not d["add"]: self.sel_verts = set()
                self.page.verts_changed()
            self.update(); return
        if d["mode"] == "paint": self.doc.touch(); self.changed.emit(); self.update(); return
        if d["mode"] == "link":
            h = self.hit(pos, parts=False); tgt = h[1] if h else None
            if tgt != d["src"][1]: self.doc.checkpoint(); self.link(d["src"], tgt, d.get("src_end", "head"), self.end_at(pos, tgt) if tgt else "tail"); self.doc.touch(); self.changed.emit(); self.page.toast("Unlinked" if tgt is None else "Linked")
            self.update(); return
        if d["mode"] == "lasso":
            poly = QPolygonF(self.lasso); self.lasso = []; cp = self.cur_part()
            if cp is not None and cp.get("mesh") and len(poly) > 2:
                pose, rest = self.pose_now(); S = self._mesh_screen(cp, pose, rest); inside = {i for i, s in enumerate(S) if poly.containsPoint(s, Qt.OddEvenFill)}
                if d["mods"] & Qt.ShiftModifier: self.sel_verts |= inside
                elif d["mods"] & Qt.AltModifier: self.sel_verts -= inside
                else: self.sel_verts = inside
            self.page.verts_changed(); self.update(); return
        if d["mode"] == "vert" and d.get("retri") and d.get("moved"):
            cp = self.cur_part()
            if cp is not None and cp.get("mesh"): self._retri_checked(cp, d["old_mesh"])
        if d["mode"] == "vert": self.doc.touch(); self.changed.emit()
        if d.get("moved"): self.doc.touch(); self.changed.emit()
        self.update()
    def mouseDoubleClickEvent(self, e):
        if self.tool == "line" and self.line_pts and e.button() == Qt.LeftButton: self.finish_line()
        else: self.mousePressEvent(e)
    def leaveEvent(self, e):
        self.brush_pos = None; self.update(); super().leaveEvent(e)
    touch_ok = True                                                     # Touch: pinch = zoom, two fingers = pan
    def touch_pinch(self, f, pos): self.zoom_by(f, pos)
    def touch_pan(self, dx, dy): self.pan += QPointF(dx, dy); self.update()
    def wheelEvent(self, e): self.zoom_by(1.15 ** (e.angleDelta().y() / 120.0), e.position())
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space and not e.isAutoRepeat(): self._space = True; self.setCursor(Qt.OpenHandCursor); return
        if k == Qt.Key_Control: self.update()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "line": self.finish_line()
        elif k == Qt.Key_Escape: self.line_pts = []; self.lasso = []; self.sel_verts = set(); self.page.verts_changed(); self.update()
        elif k in (Qt.Key_Plus, Qt.Key_Equal): self.zoom_by(1.25)
        elif k == Qt.Key_Minus: self.zoom_by(1 / 1.25)
        elif k == Qt.Key_BracketLeft: self.page.set_brush(self.page.brush_r * 0.85)
        elif k == Qt.Key_BracketRight: self.page.set_brush(self.page.brush_r * 1.18)
        else: super().keyPressEvent(e)
    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat(): self._space = False; self.unsetCursor(); return
        if e.key() == Qt.Key_Control: self.update()
        super().keyReleaseEvent(e)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        self.page.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]); e.acceptProposedAction()


class RigCanvasCPU(_CanvasBase, QWidget):
    """Fallback when OpenGL is not available: the picture is made by the CPU renderer."""
    is_gl = False
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), QColor("#2a2a2f")); box = self.page_box(); pc = self.paper_color()
        p.fillRect(box, pc if pc is not None else self._checker())
        p.setRenderHint(QPainter.SmoothPixmapTransform); p.drawImage(box, self._image()); p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.paint_overlays(p)


class RigCanvasGL(_CanvasBase, QOpenGLWidget):
    """The graphics card draws the puppet: every picture is a textured triangle mesh, all pictures share one texture atlas, and the whole rig is
    one draw call (Live2D's method). The mesh vertices are moved by the bones with one numpy pass; no pixel is touched by the CPU."""
    is_gl = True
    def __init__(self, page):
        super().__init__(page); self.setFormat(self._fmt()); self.scene = G.Scene(); self._gp = None; self._ctx_id = None; self.gl_error = None
        import weakref as _wr; _me = _wr.ref(self); _errors.HUB.on_trip("bone2d.canvas", lambda rep, _me=_me: (_me() is not None) and _me()._on_canvas_trip_safe(rep))      # weak: the hub must not keep a closed canvas alive
    @staticmethod
    def _fmt():
        f = G.surface_format(); f.setSamples(4); return f
    def _painter(self):
        ctx = self.context()
        if self._gp is None or self._ctx_id != id(ctx):
            self._gp = G.GLPainter(ctx); self._ctx_id = id(ctx); self.scene = G.Scene()
        return self._gp
    def initializeGL(self): pass
    def _gl_tripped(self):
        """Patch 57: the canvas failed again and again: no GL drawing (and no playback) until the breaker's cooldown ends; the overlays are still drawn."""
        try: return _errors.tripped("bone2d.canvas")
        except Exception: return False
    def _on_canvas_trip_safe(self, rep):
        """Never touch a deleted widget from the hub callback."""
        try:
            pg = self.page
            if getattr(pg, "playing", False): pg.toggle_play()
            _errors.note_fix("bone2d.canvas", "playback paused; GL drawing of the canvas is off for a while")
        except RuntimeError: pass
        except Exception: pass
    def paintGL(self):
        if self._gl_tripped(): self.gl_error = "stopped after repeated errors"; p = QPainter(self); self.paint_overlays(p); p.end(); return
        try:
            gp = self._painter(); r = self.rig; W, H = self.width(), self.height(); dpr = self.devicePixelRatioF() or 1.0; sc = (2.0 * self.z / W, -2.0 * self.z / H); off = (2.0 * self.pan.x() / W, -2.0 * self.pan.y() / H)
            gp.begin(W * dpr, H * dpr, (42 / 255.0, 42 / 255.0, 47 / 255.0, 1.0))
            hw, hh = r["w"] / 2.0, r["h"] / 2.0; pc = self.paper_color(); quad = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]], np.float32)
            if pc is not None: gp.draw_colored(quad, np.tile([pc.redF(), pc.greenF(), pc.blueF(), 1.0], (4, 1)), np.array([0, 1, 2, 0, 2, 3]), sc, off)
            else:                                                                   # transparent paper: a checker
                cell = 16.0 / max(self.z, 1e-3); nx, ny = int(math.ceil(r["w"] / cell)), int(math.ceil(r["h"] / cell)); xs, ys = np.meshgrid(np.arange(nx), np.arange(ny)); keep = ((xs + ys) % 2 == 0).ravel(); xs = xs.ravel()[keep]; ys = ys.ravel()[keep]
                base = np.stack([xs * cell - hw, ys * cell - hh], 1); x1 = np.minimum(base[:, 0] + cell, hw); y1 = np.minimum(base[:, 1] + cell, hh); v = np.zeros((len(base), 4, 2), np.float32)
                v[:, 0] = base; v[:, 1, 0] = x1; v[:, 1, 1] = base[:, 1]; v[:, 2, 0] = x1; v[:, 2, 1] = y1; v[:, 3, 0] = base[:, 0]; v[:, 3, 1] = y1
                gp.draw_colored(quad, np.tile([0.17, 0.17, 0.19, 1.0], (4, 1)), np.array([0, 1, 2, 0, 2, 3]), sc, off)
                if len(v): gp.draw_colored(v.reshape(-1, 2), np.tile([0.21, 0.21, 0.23, 1.0], (len(v) * 4, 1)), G.quad_indices(len(v)), sc, off)
            s = self.scene; s.build_atlas(r, gp.max_tex); s.build_geom(r, (self.doc.grev, id(r["parts"])))
            pose, rest = self.pose_now(); pa = None; an = None if self.rest_view() else self.doc.anim
            if an and an["ptracks"]: pa = {pid: B.track_value((tr.get("alpha") or []), self.page.t, 100.0) / 100.0 for pid, tr in an["ptracks"].items()}
            verts, idx = s.frame(r, pose, rest, pa, self.solo_set()); fx_view = B.uses_layer_fx(r) and not self.heat_on()                      # Patch 48
            if not fx_view: gp.draw_scene(s, verts, idx, sc, off, bool(r["cfg"].get("smooth", True)))
            cp = self.cur_part()
            if cp is not None and cp.get("mesh") and self.heat_on() and cp["id"] in s.parts:                                        # weight colours of the selected bone
                k = s.parts.index(cp["id"]); a0 = int(s.starts[k]); n = s.counts[k]; pos = verts[a0:a0 + n, :2]; w = self.heat_weights(cp)
                if len(w) == n:
                    tri = np.asarray(cp["mesh"]["t"], np.int64).ravel(); gp.draw_colored(pos, heat_rgba(w), tri, sc, off)
            self.gl_error = None; _errors.success("bone2d.canvas")
        except Exception as ex:
            self.gl_error = str(ex); _errors.report("bone2d.canvas", ex, fix="this frame is drawn without GL; after 5 failures in 2 s the canvas stops retrying")
        p = QPainter(self)
        if B.uses_layer_fx(self.rig) and not self.heat_on(): p.setRenderHint(QPainter.SmoothPixmapTransform); p.drawImage(self.page_box(), self._image()); p.setRenderHint(QPainter.SmoothPixmapTransform, False)          # Patch 48: blend / clipping / layer mask come from the CPU renderer
        self.paint_overlays(p); p.end()


# ───────────────────────── the layer list (right side): pictures, their bones and folders in ONE list ─────────────────────────
class LayerPanel(QWidget):
    """One list for everything. Folders hold pictures; the bones of a picture sit right above its card, joined to it by a line.
    Click selects (Ctrl / Shift add), drag a picture to reorder it or drop it on a folder, the red button deletes."""
    PART_H = 58; BONE_H = 30; GROUP_H = 44; GAP = 6; PAD = 8; IND = 18
    FAST_DBL = (0.025, 0.05)          # Patch 48: rename by a FAST double click: the 2nd click comes this many seconds (min, max) after the 1st on the same row. (The normal double click does not rename any more; F2 does.)

    def __init__(self, page):
        super().__init__(); self.page = page; self.rows = []; self.drag = None; self._pm = {}; self._last_click = None; self.setMouseTracking(True); self.build()
    @property
    def rig(self): return self.page.rig
    def build(self):
        r = self.rig; parts = sorted(r["parts"], key=lambda p: -p.get("z", 0)); gs = {g["id"]: g for g in r.get("groups", [])}; pids = {p["id"] for p in parts}; rows = []; done = set(); y = [self.PAD]
        owned = {}; order = B.bone_order(r); depth = {}
        for b in order:
            par = b.get("parent"); depth[b["id"]] = depth.get(par, -1) + 1 if (par in depth and B.get(r["bones"], par).get("owner") == b.get("owner")) else 0
            if b.get("owner") in pids: owned.setdefault(b["owner"], []).append(b)
        def add(kind, oid, ind, h, **kw):
            rows.append(dict(kind=kind, id=oid, ind=ind, y=y[0], h=h, **kw)); y[0] += h + self.GAP
        def add_part(p, ind):
            for b in owned.get(p["id"], []): add("bone", b["id"], ind, self.BONE_H, depth=depth.get(b["id"], 0), owner=p["id"])
            add("part", p["id"], ind, self.PART_H, nbones=len(owned.get(p["id"], [])))
        for p in parts:
            g = p.get("group") if p.get("group") in gs else None
            if g is None: add_part(p, 0)
            elif g not in done:
                done.add(g); add("group", g, 0, self.GROUP_H)
                if gs[g].get("open", True):
                    for q in parts:
                        if q.get("group") == g: add_part(q, 1)
        for g in r.get("groups", []):
            if g["id"] not in done: add("group", g["id"], 0, self.GROUP_H)
        for b in order:                                                            # bones that belong to no picture (older rigs)
            if b.get("owner") not in pids: add("bone", b["id"], 0, self.BONE_H, depth=depth.get(b["id"], 0), owner=None)
        self.rows = rows; self.setMinimumHeight(y[0] + self.PAD); self.update()
    # ---- geometry
    def card(self, row):
        x = self.PAD + row["ind"] * self.IND + (18 + row.get("depth", 0) * 12 if row["kind"] == "bone" and row.get("owner") else row.get("depth", 0) * 12 if row["kind"] == "bone" else 0)
        return QRectF(x, row["y"], self.width() - self.PAD - x, row["h"])
    def icons(self, row, c):
        k = row["kind"]
        if k == "part": return {"eye": QRectF(c.right() - 32, c.top() + 6, 26, 18), "lock": QRectF(c.right() - 62, c.bottom() - 24, 22, 18), "del": QRectF(c.right() - 30, c.bottom() - 24, 22, 18)}
        if k == "group": return {"eye": QRectF(c.right() - 92, c.top() + 13, 26, 18), "lock": QRectF(c.right() - 62, c.top() + 13, 22, 18), "del": QRectF(c.right() - 30, c.top() + 13, 22, 18), "arrow": QRectF(c.left(), c.top(), 34, c.height())}
        return {"eye": QRectF(c.right() - 62, c.top() + 6, 26, 18), "del": QRectF(c.right() - 30, c.top() + 6, 22, 18)}
    def thumb(self, p):
        im = self.rig["images"].get(p.get("img"))
        if not im: return None
        k = (im.get("_k"), p.get("img"))
        if k not in self._pm:
            img = B._decode(im)
            if img is None: return None
            q = QImage(np.ascontiguousarray(img).data, img.shape[1], img.shape[0], img.shape[1] * 4, QImage.Format_ARGB32_Premultiplied).copy(); self._pm[k] = QPixmap.fromImage(q.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if len(self._pm) > 300: self._pm.pop(next(iter(self._pm)))
        return self._pm[k]
    def _eye(self, p, r, on):
        p.setPen(QPen(QColor("#e8e8ee" if on else "#5a5a66"), 2)); p.setBrush(Qt.NoBrush); p.drawEllipse(r.adjusted(2, 2, -2, -2)); p.setBrush(QColor("#e8e8ee" if on else "#5a5a66")); p.drawEllipse(r.center(), 3, 3)
        if not on: p.drawLine(r.topLeft(), r.bottomRight())
    def _lock(self, p, r, on):
        col = QColor("#e8e8ee" if on else "#5a5a66"); p.setPen(QPen(col, 2)); p.setBrush(col if on else Qt.NoBrush); b = QRectF(r.left() + 3, r.top() + 7, r.width() - 6, r.height() - 8); p.drawRoundedRect(b, 3, 3)
        p.setBrush(Qt.NoBrush); p.drawArc(QRectF(r.left() + 6, r.top() + 1, r.width() - 12, 12), 0, 180 * 16)
    def _del(self, p, r):
        """The red button = delete."""
        p.setPen(Qt.NoPen); p.setBrush(QColor("#e5484d")); p.drawRoundedRect(r, 5, 5); p.setPen(QPen(QColor("#ffffff"), 1.8)); c = r.center()
        p.drawLine(QPointF(c.x() - 5, c.y() - 3.5), QPointF(c.x() + 5, c.y() - 3.5)); p.drawLine(QPointF(c.x() - 1.8, c.y() - 5.5), QPointF(c.x() + 1.8, c.y() - 5.5)); p.setBrush(Qt.NoBrush); p.drawRect(QRectF(c.x() - 3.8, c.y() - 2.5, 7.6, 7.5))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = self.rig; msel = set(self.page.canvas.msel); gs = {g["id"]: g for g in r.get("groups", [])}; rowof = {}
        for row in self.rows:
            c = self.card(row); rowof[(row["kind"], row["id"])] = c; k = row["kind"]; on = (k, row["id"]) in msel
            if k == "bone":
                continue
            p.setPen(QPen(QColor("#2f6bff") if on else QColor("#3a3a44"), 2 if on else 1)); p.setBrush(QColor("#2a2a31" if k == "part" else "#33333b")); p.drawRoundedRect(c, 9, 9)
            ic = self.icons(row, c)
            if k == "group":
                g = gs[row["id"]]; p.setPen(QPen(QColor("#c9c9d3"), 2)); p.setBrush(Qt.NoBrush); fr = QRectF(c.left() + 30, c.top() + 14, 24, 18); p.drawRoundedRect(fr, 3, 3); p.drawLine(QPointF(fr.left() + 2, fr.top()), QPointF(fr.left() + 10, fr.top() - 4))
                p.setPen(QColor("#e8e8ee")); p.setFont(_font(12, True)); p.drawText(QRectF(c.left() + 62, c.top(), c.width() - 170, c.height()), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(g["name"], Qt.ElideRight, int(c.width() - 170)))
                p.setPen(QColor("#c9c9d3")); p.setFont(_font(14)); p.drawText(QRectF(c.left() + 8, c.top(), 22, c.height()), Qt.AlignCenter, "▾" if g.get("open", True) else "▸")
                self._eye(p, ic["eye"], not g.get("hidden", False)); self._lock(p, ic["lock"], g.get("lock", False)); self._del(p, ic["del"]); continue
            part = B.get(r["parts"], row["id"]); tp = self.thumb(part)
            p.setPen(Qt.NoPen); p.setBrush(QColor("#1d1d22")); p.drawRoundedRect(QRectF(c.left() + 6, c.top() + 6, 46, 46), 6, 6)
            if tp: p.drawPixmap(int(c.left() + 7), int(c.top() + 7), tp)
            p.setPen(QColor("#e8e8ee" if part.get("visible", True) else "#6b6b75")); p.setFont(_font(12, True)); p.drawText(QRectF(c.left() + 60, c.top() + 5, c.width() - 100, 20), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(part["name"], Qt.ElideRight, int(c.width() - 100)))
            bn = B.get(r["bones"], part.get("bone")); p.setPen(QColor("#8e8e9b")); p.setFont(_font(10))
            p.drawText(QRectF(c.left() + 60, c.bottom() - 26, c.width() - 130, 20), Qt.AlignVCenter | Qt.AlignLeft, ("⛓ " + bn["name"] if bn else "no bone") + ("   ▲ mesh" if part.get("mesh") else "") + ("   · clip" if part.get("clip") else "") + ("   · mask" if part.get("mask_part") else "") + ("   · " + part["blend"] if part.get("blend", "normal") != "normal" else ""))
            self._eye(p, ic["eye"], part.get("visible", True)); self._lock(p, ic["lock"], part.get("lock", False) or bool(B.get(r["groups"], part.get("group")) and B.get(r["groups"], part.get("group")).get("lock"))); self._del(p, ic["del"])
        # bones: slim cards above their picture, joined to it by a line
        for row in self.rows:
            if row["kind"] != "bone": continue
            c = self.card(row); b = B.get(r["bones"], row["id"]); on = ("bone", row["id"]) in msel; ic = self.icons(row, c)
            owner = rowof.get(("part", row.get("owner")))
            if owner is not None:
                lx = owner.left() + 8; p.setPen(QPen(QColor("#6b6b88"), 1.6)); p.drawLine(QPointF(lx, c.center().y()), QPointF(c.left(), c.center().y())); p.drawLine(QPointF(lx, row["y"] - 1), QPointF(lx, owner.top() + 2 if True else 0))
                p.setBrush(QColor("#6b6b88")); p.drawEllipse(QPointF(lx, owner.top() + 1), 2.6, 2.6)
            p.setPen(QPen(QColor("#2f6bff") if on else QColor("#34343d"), 2 if on else 1)); p.setBrush(QColor("#25252b")); p.drawRoundedRect(c, 7, 7)
            p.setPen(QPen(QColor("#ff6b5e" if not on else "#7aa2ff"), 2)); p.drawLine(QPointF(c.left() + 9, c.bottom() - 7), QPointF(c.left() + 21, c.top() + 8)); p.setBrush(QColor("#ff6b5e" if not on else "#7aa2ff")); p.drawEllipse(QPointF(c.left() + 21, c.top() + 8), 2.6, 2.6)
            p.setPen(QColor("#e8e8ee" if not b.get("hidden") else "#6b6b75")); p.setFont(_font(11, True)); txt = b["name"] + ("   ⛓" if b.get("links") else "") + ("   ↳" if b.get("parent") else "")
            p.drawText(QRectF(c.left() + 30, c.top(), c.width() - 100, c.height()), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(txt, Qt.ElideRight, int(c.width() - 100)))
            self._eye(p, ic["eye"], not b.get("hidden", False)); self._del(p, ic["del"])
        if self.drag and self.drag.get("on"):
            y = self.drag["liney"]; p.setPen(QPen(QColor("#fbbf24"), 3)); p.drawLine(QPointF(self.PAD, y), QPointF(self.width() - self.PAD, y))
            if self.drag.get("into"): c = rowof.get(("group", self.drag["into"])); p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#fbbf24"), 2.5)); p.drawRoundedRect(c, 9, 9) if c else None
    def row_at(self, pos):
        for i, row in enumerate(self.rows):
            if row["y"] - self.GAP / 2 <= pos.y() < row["y"] + row["h"] + self.GAP / 2: return i
        return None
    def _slot(self, y):
        """Where a dragged picture would go: (index of the row it goes before, line y, folder to drop into)."""
        for i, row in enumerate(self.rows):
            if y < row["y"] + row["h"] / 2:
                if row["kind"] == "group" and y > row["y"] + row["h"] * 0.25: return i, row["y"] + row["h"] / 2, row["id"]
                return i, row["y"] - self.GAP / 2, None
        return len(self.rows), (self.rows[-1]["y"] + self.rows[-1]["h"] + self.GAP / 2 if self.rows else self.PAD), None
    def mousePressEvent(self, e):
        pos = e.position(); i = self.row_at(pos); pg = self.page; cv = pg.canvas; r = self.rig
        if i is None:
            if e.button() == Qt.LeftButton: cv.select(None, None)
            return
        row = self.rows[i]; kind, oid = row["kind"], row["id"]; c = self.card(row); ic = self.icons(row, c); mod = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        o = B.get({"part": r["parts"], "group": r["groups"], "bone": r["bones"]}[kind], oid)
        if o is None: return
        if e.button() == Qt.RightButton:
            if (kind, oid) not in cv.msel: cv.select(kind, oid)
            return
        if ic["del"].contains(pos): pg.delete_items([(kind, oid)]); return
        if ic["eye"].contains(pos):
            pg.doc.checkpoint(); key = "visible" if kind == "part" else "hidden"; o[key] = not o.get(key, kind == "part"); pg.layers_changed(geom=(kind == "part")); return
        if kind != "bone" and ic.get("lock") and ic["lock"].contains(pos): pg.doc.checkpoint(); o["lock"] = not o.get("lock", False); pg.layers_changed(geom=False); return
        if e.button() == Qt.LeftButton and not mod and self._fast_click((kind, oid)): self._rename_row(i); return
        if kind == "group":
            if ic["arrow"].contains(pos): o["open"] = not o.get("open", True); self.build(); return
            cv.select_many([("group", oid)] + [("part", p["id"]) for p in r["parts"] if p.get("group") == oid]) if not mod else cv.select("group", oid, add=True)
            self.update(); return
        cv.select(kind, oid, add=mod)
        if kind == "part" and not mod: self.drag = {"i": i, "p0": pos, "on": False, "slot": i, "liney": 0, "into": None}
        self.update()
    def mouseMoveEvent(self, e):
        d = self.drag
        if not d: return
        pos = e.position()
        if not d["on"] and abs(pos.y() - d["p0"].y()) > 6: d["on"] = True
        if d["on"]: d["slot"], d["liney"], d["into"] = self._slot(pos.y()); self.update()
    def mouseReleaseEvent(self, e):
        d = self.drag; self.drag = None
        if not d or not d["on"]: self.update(); return
        row = self.rows[d["i"]]; slot = d["slot"]; pg = self.page; r = self.rig; part = B.get(r["parts"], row["id"])
        if part is None: return
        tgt = self.rows[slot] if slot < len(self.rows) else None
        while tgt is not None and tgt["kind"] == "bone": tgt = next((x for x in self.rows if x["kind"] == "part" and x["id"] == tgt.get("owner")), None) if tgt.get("owner") else (self.rows[self.rows.index(tgt) + 1] if self.rows.index(tgt) + 1 < len(self.rows) else None)
        if tgt is not None and tgt["kind"] == "part" and tgt["id"] == part["id"]: self.update(); return
        pg.doc.checkpoint()
        if d["into"]: part["group"] = d["into"]
        elif tgt is not None and tgt["kind"] == "part": part["group"] = B.get(r["parts"], tgt["id"]).get("group")
        elif tgt is not None and tgt["kind"] == "group": part["group"] = None
        else:
            prev = next((x for x in reversed(self.rows[:slot]) if x["kind"] == "part"), None); part["group"] = B.get(r["parts"], prev["id"]).get("group") if prev else None
        order = [x for x in sorted(r["parts"], key=lambda q: -q.get("z", 0)) if x is not part]; at = len(order)
        if d["into"]:
            mem = [k for k, x in enumerate(order) if x.get("group") == d["into"]]; at = mem[0] if mem else len(order)
        elif tgt is not None and tgt["kind"] == "part": at = order.index(B.get(r["parts"], tgt["id"]))
        order.insert(at, part)
        for n, x in enumerate(reversed(order)): x["z"] = n
        pg.layers_changed()
    def _fast_click(self, key):
        """True when this click is the 2nd click on the same row within FAST_DBL seconds of the 1st."""
        now = time.monotonic(); last = self._last_click; self._last_click = (key, now)
        return last is not None and last[0] == key and self.FAST_DBL[0] <= now - last[1] <= self.FAST_DBL[1]
    def mouseDoubleClickEvent(self, e):
        self.mousePressEvent(e)           # Patch 48: no rename here any more; the 2nd click of a double click is just a click (it is also how the fast double click is seen)
    def _rename_row(self, i):
        if i is None or i >= len(self.rows): return
        row = self.rows[i]; r = self.rig; o = B.get({"part": r["parts"], "group": r["groups"], "bone": r["bones"]}[row["kind"]], row["id"])
        if o is None: return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=o["name"])
        if ok and name.strip(): self.page.doc.checkpoint(); o["name"] = name.strip(); self.page.layers_changed(geom=False)
    touch_ok = True; touch_menu = True                                  # Touch: long press = the right-click menu
    def contextMenuEvent(self, e):
        i = self.row_at(QPointF(e.pos()))
        if i is None: return
        row = self.rows[i]; kind, oid = row["kind"], row["id"]; m = QMenu(self); pg = self.page; r = self.rig
        m.addAction("Rename…  (F2)", lambda: self._rename_row(i))
        if kind == "part":
            pt = B.get(r["parts"], oid)
            if pt.get("group"): m.addAction("Take out of folder", lambda: (pg.doc.checkpoint(), pt.update(group=None), pg.layers_changed()))
            m.addAction("Duplicate", lambda: (pg.canvas.select("part", oid), pg.dup_part()))
        if kind == "bone":
            b = B.get(r["bones"], oid)
            if b.get("links"): m.addAction("Flip link direction (mother <-> child)", lambda: (pg.doc.checkpoint(), pg.canvas.flip_links(oid), pg.layers_changed(geom=False), pg.canvas.update()))
            if b.get("links"): m.addAction("Remove links", lambda: (pg.doc.checkpoint(), pg.canvas.link(("bone", oid), None) if False else self._unlink(oid), pg.layers_changed(geom=False)))
            if b.get("parent"): m.addAction("Detach from parent", lambda: (pg.doc.checkpoint(), self._detach(oid), pg.layers_changed(geom=False)))
        m.addAction("New folder from the selection", pg.new_group)
        m.addSeparator(); m.addAction("Delete", lambda: pg.delete_items(self.page.canvas.sel_items() if (kind, oid) in self.page.canvas.msel else [(kind, oid)]) if kind != "group" else pg.delete_group(oid))
        m.exec(e.globalPos())
    def _unlink(self, oid):
        r = self.rig
        for x in r["bones"]:
            if oid in x["links"]: x["links"].remove(oid)
            x["lkids"] = [q for q in x.get("lkids", []) if q != oid]
        B.get(r["bones"], oid)["links"] = []; B.get(r["bones"], oid)["lkids"] = []
    def _detach(self, oid):
        r = self.rig; b = B.get(r["bones"], oid); w = B.rest_world(r)[oid]; b["parent"] = None; b["x"], b["y"], b["rot"] = float(w[0, 2]), float(w[1, 2]), float(B.mat_angle(w))


class _Fake:
    def __init__(self, p): self._p = p
    def position(self): return self._p


def card_frame(title, w=262):
    f = Card(); f.setFixedWidth(w); f.setStyleSheet("QFrame#card{background:rgba(30,30,36,238);border:1px solid #3d3d46;border-radius:12px}"); f.setObjectName("card")
    v = QVBoxLayout(f); v.setContentsMargins(12, 10, 12, 12); v.setSpacing(7); t = QLabel(title); t.setStyleSheet("color:#f2f2f6;font-size:15px;font-weight:700;background:transparent"); v.addWidget(t); return f, v



def slider_row(v, txt, sl, fmt="%d"):
    r = QHBoxLayout(); r.setSpacing(6); l = QLabel(txt); l.setFixedWidth(78); l.setStyleSheet("color:#a9a9b6;font-size:12px;background:transparent"); r.addWidget(l); r.addWidget(sl, 1)
    val = QLabel(fmt % sl.value()); val.setFixedWidth(30); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter); val.setStyleSheet("color:#e8e8ee;font-size:12px;background:transparent"); r.addWidget(val)
    sl.changed.connect(lambda x: val.setText(fmt % x)); v.addLayout(r); return val


# ───────────────────────── the dope sheet ─────────────────────────
class DopeSheet(QWidget):
    seek = Signal(float)
    changed = Signal()
    HEAD = 150; RH = 20; TOP = 34; MARKH = 14; WAVE = 32; FOC = 12          # TOP = ruler + focus bar, MARKH = the strip of marks, WAVE = the guide sound (when the animation has one)
    @property
    def RULER(self): return self.TOP + self.MARKH + (self.WAVE if RA.audio_of(self.doc.anim) else 0)

    def __init__(self, page):
        super().__init__(); self.page = page; self.doc = page.doc; self.setMinimumHeight(110); self.setMouseTracking(True); self.scroll = 0; self.sel_keys = []; self.drag = None; self.f0 = 0.0; self.f1 = None; self.box = None; self._wave_key = None; self._wave_cols = []; self.setFocusPolicy(Qt.ClickFocus)
    def rows(self):
        """[(label, owner id, channel or None, is_part, [keys])]; a bone row shows every key of the bone, the selected bone also shows its channels."""
        r = self.doc.rig; a = self.doc.anim; out = []; sel = self.page.canvas.sel
        for b in r["bones"]:
            tr = a["tracks"].get(b["id"], {}); allk = [k for ch in B.CHANNELS for k in tr.get(ch, [])]
            out.append((b["name"], b["id"], None, False, allk))
            if sel == ("bone", b["id"]):
                for ch in B.CHANNELS: out.append(("    " + B.CH_LABEL[ch], b["id"], ch, False, tr.get(ch, [])))
        for p in r["parts"]:
            ks = (a["ptracks"].get(p["id"]) or {}).get("alpha")
            if ks: out.append((p["name"] + " · opacity", p["id"], "alpha", True, ks))
        return out
    def focus(self):
        """The part of the clip shown (Focus): (start, end) in seconds. Default = the whole animation."""
        d = float(self.doc.anim["dur"]); f1 = d if self.f1 is None else self.f1; f0 = max(0.0, min(self.f0, d)); f1 = max(0.0, min(f1, d))
        return (0.0, d) if f1 - f0 < 0.05 else (f0, f1)
    def pps(self): f0, f1 = self.focus(); return max(10.0, (self.width() - self.HEAD - 24) / max(0.05, f1 - f0))
    def t2x(self, t): return self.HEAD + 8 + (t - self.focus()[0]) * self.pps()
    def x2t(self, x): return (x - self.HEAD - 8) / self.pps() + self.focus()[0]
    def snap(self, t):
        fps = max(1, self.doc.rig["cfg"].get("fps", 30)); return max(0.0, min(self.doc.anim["dur"], round(t * fps) / fps))
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); c = pal(); p.fillRect(self.rect(), QColor("#1c1c20")); a = self.doc.anim
        p.fillRect(QRectF(0, 0, self.HEAD, self.height()), QColor("#202024")); p.fillRect(QRectF(0, 0, self.width(), self.RULER), QColor("#26262c"))
        step = 0.1
        for s in (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0):
            step = s
            if s * self.pps() >= 46: break
        f0, f1 = self.focus(); t = int(f0 / step) * step; p.setFont(_font(10)); p.setClipRect(QRectF(self.HEAD, 0, self.width() - self.HEAD, self.height()))
        while t <= f1 + 1e-6:
            if t >= f0 - 1e-6: x = self.t2x(t); p.setPen(QColor("#3a3a43")); p.drawLine(QPointF(x, self.TOP - 6), QPointF(x, self.height())); p.setPen(QColor("#8e8e9b")); p.drawText(QPointF(x + 3, 13), "%.2fs" % t)
            t += step
        p.setClipping(False)
        lane = QRectF(self.HEAD + 8, self.TOP - self.FOC - 1, self.width() - self.HEAD - 24, self.FOC - 2); full = self.focus() == (0.0, float(a["dur"]))        # the Focus bar: drag it, or its ends, to work on one part of the clip
        p.setPen(Qt.NoPen); p.setBrush(QColor("#1c1c20")); p.drawRoundedRect(lane, 3, 3); d_ = max(0.05, float(a["dur"])); lx = lambda tt: lane.left() + lane.width() * tt / d_
        p.setBrush(QColor("#4d7cff") if not full else QColor("#3a3a43")); p.drawRoundedRect(QRectF(lx(f0), lane.top(), max(6.0, lx(f1) - lx(f0)), lane.height()), 3, 3)
        self._draw_wave(p); y = self.RULER - self.scroll; rows = self.rows()
        p.save(); p.setClipRect(QRectF(0, self.RULER, self.width(), self.height() - self.RULER))
        for i, (lab, oid, ch, is_part, ks) in enumerate(rows):
            ry = self.RULER + i * self.RH - self.scroll
            if ch is None: p.fillRect(QRectF(0, ry, self.width(), self.RH), QColor("#24242a" if self.page.canvas.sel != ("bone", oid) else "#2a3a40"))
            p.setPen(QColor("#c9c9d3" if ch is None else "#8e8e9b")); p.setFont(_font(11)); p.drawText(QRectF(8, ry, self.HEAD - 12, self.RH), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(lab, Qt.ElideRight, self.HEAD - 14))
            bone = B.get(self.doc.rig["bones"], oid) if not is_part else None; kc = bone_qcolor(bone) if bone else QColor("#fbbf24")             # a key has the colour of its bone
            for k in ks:
                if k["t"] < f0 - 0.5 / max(1.0, self.pps()) or k["t"] > f1 + 0.5 / max(1.0, self.pps()): continue
                on = any(k is s[0] for s in self.sel_keys); cx, cy = self.t2x(k["t"]), ry + self.RH / 2
                poly = QPolygonF([QPointF(cx, cy - 6), QPointF(cx + 6, cy), QPointF(cx, cy + 6), QPointF(cx - 6, cy)])
                p.setPen(QPen(QColor("#ffffff") if on else kc.darker(140), 1.8 if on else 1.2)); p.setBrush(kc.lighter(125) if on else kc); p.drawPolygon(poly)
        p.restore()
        self._draw_marks(p); x = self.t2x(self.page.t)
        if x >= self.HEAD: p.setPen(QPen(QColor("#ff5a6a"), 2)); p.drawLine(QPointF(x, 0), QPointF(x, self.height())); p.setBrush(QColor("#ff5a6a")); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 10)]))
        x = self.t2x(a["dur"]); p.setPen(QPen(QColor("#5a5a66"), 1, Qt.DashLine)); p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        if self.box is not None: p.setPen(QPen(QColor("#2f6bff"), 1.2)); p.setBrush(QColor(47, 107, 255, 40)); p.drawRect(self.box)
    def _draw_wave(self, p):
        """The guide sound (taken from the main video) as a waveform under the ruler."""
        au = RA.audio_of(self.doc.anim)
        if au is None: return
        y0 = self.TOP + self.MARKH; lane = QRectF(self.HEAD, y0, self.width() - self.HEAD, self.WAVE); p.fillRect(lane, QColor("#182027")); p.fillRect(QRectF(0, y0, self.HEAD, self.WAVE), QColor("#1b2229"))
        p.setPen(QColor("#6f8da0")); p.setFont(_font(10)); p.drawText(QRectF(8, y0, self.HEAD - 12, self.WAVE), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText("\u266a " + au.get("name", "sound"), Qt.ElideRight, self.HEAD - 14))
        ld = RA.load(self.page.path, au)
        if ld is None: p.setPen(QColor("#c06060")); p.drawText(lane.adjusted(10, 0, 0, 0), Qt.AlignVCenter, "sound file missing"); return
        peaks = ld[1]; off = float(au.get("offset", 0.0)); gain = float(au.get("gain", 100.0)) / 100.0; f0, f1 = self.focus(); x0 = int(self.HEAD + 8); x1 = int(self.width() - 16)
        key = (x0, x1, round(f0, 4), round(f1, 4), round(off, 4), round(gain, 3), id(peaks), len(peaks))
        if key != self._wave_key:
            cols = []
            for x in range(x0, max(x0, x1)):
                i0 = int((self.x2t(x) - off) * RA.PEAK_RATE); i1 = max(i0 + 1, int((self.x2t(x + 1) - off) * RA.PEAK_RATE))
                cols.append(min(1.0, float(peaks[max(0, i0):min(len(peaks), i1)].max()) * gain) if i1 > 0 and i0 < len(peaks) else 0.0)
            self._wave_key = key; self._wave_cols = cols
        mid = lane.center().y(); amp = lane.height() / 2 - 2; p.save(); p.setClipRect(QRectF(self.HEAD, y0, self.width() - self.HEAD, self.WAVE)); p.setPen(QPen(QColor("#555d66") if au.get("mute") else QColor("#4d9fb8"), 1))
        for i, v in enumerate(self._wave_cols):
            if v > 0.003: h = max(0.5, v * amp); p.drawLine(QPointF(x0 + i + 0.5, mid - h), QPointF(x0 + i + 0.5, mid + h))
        p.restore()
    def _draw_marks(self, p):
        """Marks (flags in their colour on the strip under the ruler, a thin line down through the rows) and the beat lines."""
        m = self.page.marks(); f0, f1 = self.focus(); bottom = self.TOP + self.MARKH; p.save(); p.setClipRect(QRectF(self.HEAD, 0, self.width() - self.HEAD, self.height())); p.setFont(_font(10))
        if m.beat_grid.get("show"): MKU.draw_beat_ticks(p, m.beat_grid, f0, f1, self.t2x, bottom, self.HEAD, self.width())
        for t in m.markers:
            x = self.t2x(t)
            if self.HEAD - 6 <= x <= self.width() + 6: MKU.draw_mark_flag(p, x, 0, bottom, MK.color_of(m, t), m.marker_names.get("%.3f" % t, ""), line_to=self.height(), selected=bool(self.drag and self.drag.get("mode") == "markdrag" and abs(self.drag.get("cur", -9) - t) < 1e-3))
        p.restore()
    def mark_hit(self, x):
        ms = self.page.marks().markers
        if not ms: return None
        best = min(ms, key=lambda v: abs(self.t2x(v) - x)); return best if abs(self.t2x(best) - x) <= 7 else None
    def snap_mag(self, t):
        """snap() plus a magnet: marks (and the beat lines when Lock to beat is on) pull within 8 px. Hold Alt to switch the magnet off."""
        if QApplication.keyboardModifiers() & Qt.AltModifier: return self.snap(t)
        m = self.page.marks(); thr = 8.0 / self.pps(); pts = list(m.markers) + MK.beat_snap_points(m, t, thr); best = min(pts, key=lambda s_: abs(s_ - t)) if pts else None
        return max(0.0, min(float(self.doc.anim["dur"]), best)) if best is not None and abs(best - t) <= thr else self.snap(t)
    def key_at(self, pos):
        for i, (lab, oid, ch, is_part, ks) in enumerate(self.rows()):
            ry = self.RULER + i * self.RH - self.scroll
            if ry <= pos.y() <= ry + self.RH:
                for k in ks:
                    if abs(self.t2x(k["t"]) - pos.x()) <= 7: return (k, oid, ch, is_part, i)
        return None
    def mousePressEvent(self, e):
        pos = e.position()
        if pos.x() < self.HEAD:
            i = int((pos.y() - self.RULER + self.scroll) // self.RH); rows = self.rows()
            if 0 <= i < len(rows) and not rows[i][3]: self.page.canvas.select("bone", rows[i][1])
            return
        if e.button() == Qt.RightButton and pos.y() < self.RULER:
            self.page.mark_menu(self.x2t(pos.x()), self.pps(), e.globalPosition().toPoint()); return
        if e.button() == Qt.RightButton:
            hit = self.key_at(pos)
            if hit: self.sel_keys = self._group(hit); self.page.delete_keys(self.sel_keys); self.sel_keys = []
            return
        if self.TOP <= pos.y() < self.TOP + self.MARKH and e.button() == Qt.LeftButton:       # a mark: drag it along (it locks to the beat when that is on)
            hit = self.mark_hit(pos.x())
            if hit is not None: self.drag = {"mode": "markdrag", "cur": hit, "moved": False}; self.page.goto(hit); return
        if pos.y() >= self.TOP - self.FOC - 1 and pos.y() < self.TOP:                  # the Focus bar
            f0, f1 = self.focus(); d_ = max(0.05, float(self.doc.anim["dur"])); lw = self.width() - self.HEAD - 24; tx = (pos.x() - self.HEAD - 8) / max(1.0, lw) * d_
            if e.type() == QEvent.MouseButtonDblClick: self.f0, self.f1 = 0.0, None; self.update(); return
            edge = 6.0 / max(1.0, lw) * d_; m = "l" if abs(tx - f0) <= edge else "r" if abs(tx - f1) <= edge else "move" if f0 < tx < f1 else "new"
            self.drag = {"mode": "focus", "m": m, "tx0": tx, "f0": f0, "f1": f1}
            if m == "new": self.f0 = max(0.0, tx - (f1 - f0) / 2); self.f1 = self.f0 + (f1 - f0); self.drag.update(m="move", tx0=tx, f0=self.f0, f1=self.f1)
            self.update(); return
        if pos.y() < self.RULER: self.drag = {"mode": "seek"}; self.seek.emit(self.snap_mag(self.x2t(pos.x()))); return
        hit = self.key_at(pos); shift = bool(e.modifiers() & Qt.ShiftModifier)
        if hit and shift:
            g = self._group(hit); have = [s for s in self.sel_keys if any(s[0] is q[0] for q in g)]
            self.sel_keys = [s for s in self.sel_keys if s not in have] if have else self.sel_keys + g; self.page.on_key_selection(self.sel_keys); self.update(); return
        if hit:
            if not any(hit[0] is s[0] for s in self.sel_keys): self.sel_keys = self._group(hit)
            self.doc.checkpoint(); self.drag = {"mode": "keys", "t0": self.x2t(pos.x()), "orig": [(s[0], s[0]["t"]) for s in self.sel_keys]}
            self.page.on_key_selection(self.sel_keys); self.update()
        else:                                                                               # empty space: a click moves the playhead, dragging draws a box that selects keys
            self.drag = {"mode": "box", "p0": pos, "moved": False, "add": shift, "base": list(self.sel_keys) if shift else []}
            if not shift: self.sel_keys = []; self.seek.emit(self.snap_mag(self.x2t(pos.x()))); self.page.on_key_selection([])
            self.update()
    def _group(self, hit):
        """A click on a bone row moves every channel key of that bone at that time; on a channel row just that key."""
        k, oid, ch, is_part, i = hit
        if ch is not None: return [(k, oid, ch, is_part)]
        a = self.doc.anim; out = []
        for c2 in B.CHANNELS:
            for k2 in (a["tracks"].get(oid, {}).get(c2) or []):
                if abs(k2["t"] - k["t"]) < 1e-6: out.append((k2, oid, c2, False))
        return out
    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            pos = e.position(); self.setCursor(Qt.SizeHorCursor if (self.TOP <= pos.y() < self.TOP + self.MARKH and pos.x() > self.HEAD and self.mark_hit(pos.x()) is not None) else Qt.ArrowCursor); return
        t = self.x2t(e.position().x())
        if d["mode"] == "markdrag":
            if not d["moved"]: self.doc.checkpoint(); d["moved"] = True
            d["cur"] = MK.move_mark(self.page.marks(), d["cur"], max(0.0, min(float(self.doc.anim["dur"]), t)), self.doc.rig["cfg"].get("fps", 30)); self.page.model_dirty(); return
        if d["mode"] == "seek": self.seek.emit(self.snap_mag(t)); return
        if d["mode"] == "focus":
            dur = float(self.doc.anim["dur"]); lw = self.width() - self.HEAD - 24; tx = (e.position().x() - self.HEAD - 8) / max(1.0, lw) * dur; dd = tx - d["tx0"]; mn = max(0.1, 1.0 / max(1, self.doc.rig["cfg"].get("fps", 30)) * 3)
            if d["m"] == "move": ln = d["f1"] - d["f0"]; a0 = max(0.0, min(dur - ln, d["f0"] + dd)); self.f0, self.f1 = a0, a0 + ln
            elif d["m"] == "l": self.f0 = max(0.0, min(d["f1"] - mn, d["f0"] + dd)); self.f1 = d["f1"]
            else: self.f0 = d["f0"]; self.f1 = min(dur, max(d["f0"] + mn, d["f1"] + dd))
            self.update(); return
        if d["mode"] == "box":
            p0 = d["p0"]; pos = e.position()
            if not d["moved"] and math.hypot(pos.x() - p0.x(), pos.y() - p0.y()) < 4: return
            d["moved"] = True; self.box = QRectF(p0, pos).normalized(); self.update(); return
        dt = t - d["t0"]
        for (k, t0) in d["orig"]: k["t"] = self.snap_mag(t0 + dt)
        a = self.doc.anim
        for trs in (a["tracks"], a["ptracks"]):
            for tr in trs.values():
                for ks in tr.values(): ks.sort(key=lambda k: k["t"])
        self.doc.touch(); self.changed.emit(); self.update()
    def mouseReleaseEvent(self, e):
        d = self.drag; self.drag = None
        if d and d["mode"] == "box":
            rect = self.box; self.box = None
            if d["moved"] and rect is not None:
                found = []
                for i, (lab, oid, ch, is_part, ks) in enumerate(self.rows()):
                    ry = self.RULER + i * self.RH - self.scroll
                    if ry + self.RH < rect.top() or ry > rect.bottom(): continue
                    for k in ks:
                        if rect.left() <= self.t2x(k["t"]) <= rect.right():
                            for g in (self._group((k, oid, ch, is_part, i))): found.append(g)
                seen = set(); out = list(d["base"])
                for s_ in found + []:
                    if id(s_[0]) not in seen and not any(s_[0] is q[0] for q in out): seen.add(id(s_[0])); out.append(s_)
                self.sel_keys = out; self.page.on_key_selection(self.sel_keys)
            self.update()
    def wheelEvent(self, e):
        n = len(self.rows()); mx = max(0, n * self.RH - (self.height() - self.RULER)); self.scroll = max(0, min(mx, self.scroll - e.angleDelta().y() / 4)); self.update()


# ───────────────────────── config dialog ─────────────────────────
class Bone2DConfigDialog(AnimatedDialog):
    """Settings of the rig (size, smoothing, background, bones on screen ...) and, when a timeline clip is given, how that clip plays it."""
    def __init__(self, parent, rig, clip=None):
        super().__init__(parent, "Bone2D settings", 460); self.rig = rig; self.clip = clip; cfg = rig["cfg"]
        def row(txt, *ws, sec=None):
            r = QHBoxLayout(); r.setSpacing(8); l = label(txt, True, 12); l.setFixedWidth(128); r.addWidget(l)
            for i, w in enumerate(ws): r.addWidget(w, 1 if i == 0 else 0)
            (sec or self.sec).body.addLayout(r)
        if clip is not None:
            self.sec = Section("This clip", "play"); cc = dict(B.DEFAULT_CLIP); cc.update(clip.get("b2d") or {})
            self.c_anim = Dropdown([(a["name"], a["id"]) for a in rig["anims"]]); self.c_anim.setCurrentIndex(max(0, self.c_anim.findData(cc["anim"] or cfg["default_anim"])))
            self.c_loop = Dropdown([(n, v) for n, v in B.CLIP_LOOPS]); self.c_loop.setCurrentIndex(max(0, self.c_loop.findData(cc["loop"])))
            self.c_speed = NumberField(cc["speed"], 5, 1000, 0, " %", "", 1.0); self.c_off = NumberField(cc["offset"], -3600, 3600, 2, " s", "", 0.05)
            row("Animation", self.c_anim); row("Loop", self.c_loop); row("Speed", self.c_speed); row("Start offset", self.c_off); self.body.addWidget(self.sec)
        self.sec = Section("Rig", "settings")
        self.name = TextField(rig.get("name", "")); self.w = NumberField(rig["w"], 8, 8192, 0, " px", "W", 1.0); self.h = NumberField(rig["h"], 8, 8192, 0, " px", "H", 1.0)
        wh = QWidget(); l = QHBoxLayout(wh); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(6); l.addWidget(self.w); l.addWidget(self.h)
        self.fps = NumberField(cfg["fps"], 1, 120, 0, " fps", "", 0.2); self.smooth = Toggle("Smooth edges (off = pixel art)", bool(cfg["smooth"])); self.gpu = Toggle("Draw with the graphics card (OpenGL, much faster)", bool(cfg.get("gpu", True)))
        self.bg_on = Toggle("Fill background", bool(cfg["bg"])); self.bg = ColorButton(cfg["bg"] or "#000000")
        self.paper = Dropdown([("White page", "white"), ("Checkerboard", "checker"), ("Dark", "dark")]); self.paper.setCurrentIndex(max(0, self.paper.findData(cfg.get("paper", "white"))))
        self.def_anim = Dropdown([(a["name"], a["id"]) for a in rig["anims"]]); self.def_anim.setCurrentIndex(max(0, self.def_anim.findData(cfg["default_anim"])))
        row("Name", self.name); row("Picture size", wh); row("Frame rate", self.fps); row("Smoothing", self.smooth); row("Renderer", self.gpu); row("Background", self.bg_on, self.bg); row("Default animation", self.def_anim); row("Editor page", self.paper)
        self.body.addWidget(self.sec)
        self.sec = Section("Editor", "tune")
        self.snap = NumberField(cfg["snap_deg"], 0, 90, 0, " °", "", 0.2); self.names = Toggle("Show bone names", bool(cfg["show_names"])); self.parts = Toggle("Outline the selected part", bool(cfg["show_parts"]))
        self.bcol = ColorButton(cfg["bone_color"]); self.bw = NumberField(cfg["bone_width"], 0.4, 3.0, 1, " ×", "", 0.05)
        row("Snap rotation", self.snap); row("Bone colour", self.bcol); row("Bone thickness", self.bw); row("", self.names); row("", self.parts); self.body.addWidget(self.sec)
        r = QHBoxLayout(); r.addStretch(); c = QPushButton("Cancel"); c.clicked.connect(self.reject); ok = QPushButton("Apply"); ok.setObjectName("Accent"); ok.clicked.connect(self.accept); r.addWidget(c); r.addWidget(ok); self.body.addLayout(r)
    def apply(self):
        """Write the choices into the rig / the clip. Returns (rig changed, clip changed)."""
        r = self.rig; cfg = r["cfg"]; before = copy.deepcopy((r["name"], r["w"], r["h"], cfg)); name = self.name.text().strip() or r.get("name", "Rig")
        r["name"] = name; r["w"] = int(self.w.value()); r["h"] = int(self.h.value())
        cfg.update(fps=int(self.fps.value()), smooth=self.smooth.on, gpu=self.gpu.on, bg=self.bg.c if self.bg_on.on else "", default_anim=self.def_anim.currentData(), paper=self.paper.currentData(),
                   snap_deg=float(self.snap.value()), show_names=self.names.on, show_parts=self.parts.on, bone_color=self.bcol.c, bone_width=float(self.bw.value()))
        rc = before != (r["name"], r["w"], r["h"], cfg); cc = False
        if self.clip is not None:
            new = {"anim": self.c_anim.currentData(), "loop": self.c_loop.currentData(), "speed": float(self.c_speed.value()), "offset": float(self.c_off.value())}
            if new["anim"] == cfg["default_anim"]: new["anim"] = ""
            cc = new != (self.clip.get("b2d") or {}); self.clip["b2d"] = new
        return rc, cc


# ───────────────────────── the page (the Bone2D mode) ─────────────────────────
class Bone2DPage(SyncMixin, QWidget):
    closed = Signal()

    def __init__(self, app, path):
        super().__init__(); self.app = app; self.path = path
        rig = B.load_file(path); self.doc = RigDoc(path, rig); self.doc.anim = B.anim_of(rig, rig["cfg"]["default_anim"])
        self.mode = "setup"; self.t = 0.0; self.playing = False; self._loading = False; self._edit_open = False; self._tick = QTimer(self); self._tick.setTimerType(Qt.PreciseTimer); self._tick.setInterval(16); self._tick.timeout.connect(self._step)
        self._last = time.monotonic(); self.line_n = 4; self.line_weight = True; self.auto_norm = False; self.sharp = 3.0; self.vweight = 100.0; self.link_mode = "link"; self.brush_r = 40.0; self.brush_str = 50.0; self.brush_sub = False
        self.audio = RA.RigAudioPlayer(); self.canvas = (RigCanvasGL if (gl_ok() and rig["cfg"].get("gpu", True)) else RigCanvasCPU)(self); self.sheet = DopeSheet(self)
        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 10); root.setSpacing(8)
        # ---- top bar
        top = QHBoxLayout(); top.setSpacing(4); top.addWidget(Btn("Back to editor", "home", "ghost", "Save the rig and go back to the timeline", self.close_page, h=32))
        self.title = QLabel(); self.title.setObjectName("ProjTitle"); top.addSpacing(8); top.addWidget(self.title); top.addSpacing(14)
        self.modes = Segmented([("Setup", "setup"), ("Animate", "animate")], "setup"); self.modes.setFixedSize(190, 30); self.modes.setToolTip("Setup: pictures, mesh, bones and weights · Animate: pose the bones and make keyframes"); self.modes.changed.connect(self.set_mode); top.addWidget(self.modes); top.addStretch()
        top.addWidget(Btn("", "undo", "ghost", "Undo (Ctrl+Z)", self.undo, h=32)); top.addWidget(Btn("", "redo", "ghost", "Redo (Ctrl+Shift+Z)", self.redo, h=32))
        top.addWidget(Btn("Settings", "settings", "ghost", "Size, frame rate, smoothing, bone display …", self.open_config, h=32)); top.addWidget(Btn("Save", "save", "soft", "Save the rig (Ctrl+S)", self.save, h=32))
        top.addWidget(Btn("Add to timeline", "plus", "accent", "Put this rig on the timeline at the playhead", self.add_to_timeline, h=32)); root.addLayout(top)
        # ---- middle: tools | canvas | layers
        mid = QWidget(); ml = QHBoxLayout(mid); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(8)
        bar = QFrame(); bar.setObjectName("toolbar"); bar.setStyleSheet("QFrame#toolbar{background:#232328;border:1px solid #34343b;border-radius:12px}"); bl = QVBoxLayout(bar); bl.setContentsMargins(6, 8, 6, 8); bl.setSpacing(4); self.tool_btns = {}
        self.group_last = {"mesh": "mesh", "bone": "bone"}
        for key, name, tip in TOOLS:
            if key in ("vadd", "vdel", "vedit", "line"): continue                                  # these are modes of the Mesh editor / Bone tool (bar at the top left of the canvas)
            if key == "mesh": name, tip = "Mesh editor", "Mesh editor: pick the mode at the top left — Auto mesh, Pencil (add points), Eraser (delete points), Edit (select / move points)."
            if key == "bone": name, tip = "Bone", "Bone: pick the mode at the top left — Drag (drag to draw one bone) or Line (click points along a tail / hair, then Enter)."
            b = QToolButton(); b.setCheckable(True); b.setIcon(tool_icon(key, 34)); b.setIconSize(QSize(34, 34)); b.setFixedSize(58, 58); b.setToolTip("<b>%s</b><br>%s" % (name, tip)); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("QToolButton{background:transparent;border:1px solid transparent;border-radius:10px}QToolButton:hover{background:#2f2f37}QToolButton:checked{background:#1e3a8a;border:1px solid #2f6bff}")
            b.clicked.connect(lambda _=False, k=key: self.pick_tool(self.group_last.get(k, k))); bl.addWidget(b); self.tool_btns[key] = b
        bl.addStretch(); hs = QSplitter(Qt.Horizontal); hs.setChildrenCollapsible(False); hs.setHandleWidth(6); ml.addWidget(hs, 1); bar.setFixedWidth(bar.sizeHint().width() + 2); hs.addWidget(bar); hs.addWidget(self.canvas)       # drag the thin bars between the panels to resize them
        self.dock = QWidget(); self.dock.setMinimumWidth(220); self.dock.setMaximumWidth(700); dl = QVBoxLayout(self.dock); dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(6)
        self.dock_tabs = Segmented([("Layers", "l"), ("Props", "p")], "l"); self.dock_tabs.changed.connect(self.pick_dock); dl.addWidget(self.dock_tabs); self.dock_stack = FadeStack(); dl.addWidget(self.dock_stack, 1)
        lw = QWidget(); lv = QVBoxLayout(lw); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6); self.layers = LayerPanel(self)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setWidget(self.layers); lv.addWidget(sa, 1)
        row = QHBoxLayout(); row.setSpacing(4)
        for tip, ic, fn in (("New folder (the selected pictures go into it)", "folder", self.new_group), ("Add pictures", "plus", self.pick_images), ("Import a Photoshop file (.psd): every layer becomes a picture, folders are kept", "image", self.pick_psd), ("Duplicate picture", "duplicate", self.dup_part), ("Delete the selected pictures / bones (Del)", "delete", self.delete_sel)):
            row.addWidget(tool("", tip, fn, icon=ic, isize=20))
        row.addStretch(); lv.addLayout(row)
        orow = QHBoxLayout(); orow.setSpacing(6); ol = QLabel("0%"); ol.setStyleSheet("color:#8e8e9b"); self.op_slider = Slider(0, 100, 100, 100, 0); self.op_slider.changed.connect(self._set_opacity); self.op_slider.pressed.connect(self.begin_edit); self.op_slider.released.connect(self.end_edit)
        self.op_lbl = QLabel("100%"); self.op_lbl.setFixedWidth(40); self.op_lbl.setStyleSheet("color:#e8e8ee"); orow.addWidget(ol); orow.addWidget(self.op_slider, 1); orow.addWidget(self.op_lbl); lv.addLayout(orow)
        self.dock_stack.addWidget(lw)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setIndentation(14); self.tree.itemSelectionChanged.connect(self._tree_pick); self.tree.itemChanged.connect(self._tree_edit); self.dock_stack.addWidget(self.tree)
        self.props = Panel("Properties"); self._build_props(); self.dock_stack.addWidget(self.props); hs.addWidget(self.dock); hs.setStretchFactor(0, 0); hs.setStretchFactor(1, 1); hs.setStretchFactor(2, 0); hs.setSizes([bar.width(), 900, 300])
        self._build_cards()
        # ---- bottom: animation (only in Animate mode)
        self.bot = Panel("Animation"); self._build_anim_bar(self.bot); self.build_sync_row(self.bot)
        self.curve = CurveBox(self); self.bsplit = QSplitter(Qt.Horizontal); self.bsplit.setChildrenCollapsible(False); self.bsplit.setHandleWidth(6); self.bsplit.addWidget(self.sheet); self.bsplit.addWidget(self.curve)    # Patch 44: the key sheet and, smaller, the motion curve editor of the main program
        self.bsplit.setStretchFactor(0, 1); self.bsplit.setStretchFactor(1, 0); self.bsplit.setSizes([820, 300]); self.bot.body.addWidget(self.bsplit, 1); self.bot.setMinimumHeight(290); self.bot.hide()
        v = QSplitter(Qt.Vertical); v.setChildrenCollapsible(False); v.addWidget(mid); v.addWidget(self.bot); v.setSizes([600, 300]); v.setStretchFactor(0, 1); root.addWidget(v, 1)
        self.canvas.changed.connect(self._model_changed); self.canvas.selected.connect(self._sel_changed); self.sheet.seek.connect(self.goto); self.sheet.changed.connect(self._model_changed)
        self._shortcuts(); self.pick_tool("select")
        self.rebuild_tree(); self.refresh_anims(); self.refresh_props(); self.update_title()
    # ---- shortcuts
    def _shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self); s.setContext(Qt.WidgetWithChildrenShortcut); s.activated.connect(fn); return s
        sc("Ctrl+S", self.save); sc("Ctrl+Z", self.undo); sc("Ctrl+Shift+Z", self.redo); sc("Ctrl+Y", self.redo); sc("Delete", self.delete_sel)
        sc("F2", self.rename_selected); sc("Space", self.toggle_play); sc("K", self.key_selected); self.build_sync_shortcuts(sc); sc("Left", lambda: self.step_frame(-1)); sc("Right", lambda: self.step_frame(1))
        for k, key in (("M", "mesh"), ("B", "bone"), ("V", "select"), ("L", "link"), ("D", "line"), ("S", "solo"), ("A", "lasso"), ("P", "physic"), ("W", "weight"), ("I", "vadd"), ("X", "vdel"), ("E", "vedit")): sc(k, lambda key=key: self.pick_tool(key))
    def rename_selected(self):
        """F2: rename the selected picture / bone / folder."""
        k, o = self._sel_obj()
        if o is None: return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=o["name"])
        if ok and name.strip(): self.doc.checkpoint(); o["name"] = name.strip(); self.layers_changed(geom=False)
    # ---- helpers
    @property
    def rig(self): return self.doc.rig
    def toast(self, msg): _toast(self.app, msg)
    def update_title(self): self.title.setText("Bone2D  ·  %s%s" % (self.rig.get("name", ""), "  •" if self.doc.dirty else ""))
    def _model_changed(self):
        self.doc.dirty = True; self.update_title(); self.sheet.update(); self.canvas.update()
        if self.canvas.drag is None or self.canvas.drag.get("mode") in ("newbone",): self.rebuild_tree(); self.refresh_props(); self.layers.build()
        else: self._refresh_values()
    def _sel_changed(self): self._sync_tree_selection(); self.refresh_props(); self.sheet.update(); self.layers.update(); self._sync_cards()
    def layers_changed(self, geom=True): self.doc.touch(geom=geom); self.doc.dirty = True; self.update_title(); self.layers.build(); self.rebuild_tree(); self.refresh_props(); self.canvas.update()
    def pick_dock(self, v): self.dock_stack.setCurrentIndex({"l": 0, "b": 1, "p": 2}[v])
    def set_mode(self, m):
        self.mode = m; self.modes.setValue(m); slide_visible(self.bot, m == "animate")
        if m == "animate" and self.canvas.tool in ("mesh", "vadd", "vdel", "vedit", "bone", "link", "line", "lasso", "weight"): self.pick_tool("select", keep_mode=True)
        self.refresh_props(); self.canvas.update(); self.sheet.update()
    GROUP_OF = {"mesh": "mesh", "vadd": "mesh", "vdel": "mesh", "vedit": "mesh", "bone": "bone", "line": "bone"}
    def pick_tool(self, key, keep_mode=False):
        if key == "solo":
            self.canvas.solo = not self.canvas.solo; self.tool_btns["solo"].setChecked(self.canvas.solo); self.canvas.update(); return
        self.canvas.tool = key; self.canvas.line_pts = []; self.canvas.lasso = []; grp = self.GROUP_OF.get(key, key)
        if grp in self.group_last: self.group_last[grp] = key
        for k, b in self.tool_btns.items():
            if k != "solo": b.setChecked(k == grp)
        for g, bar in self.mode_bars.items(): bar.setVisible(g == grp)
        for k, b in self.mode_btns.items(): b.setChecked(k == key)
        if not keep_mode:
            if key in ("mesh", "vadd", "vdel", "vedit", "bone", "link", "line", "lasso", "weight") and self.mode != "setup": self.set_mode("setup")
            elif key == "physic" and self.mode != "animate": self.set_mode("animate")
        for k, c in self.cards_by_tool.items(): c.setVisible(k == key)
        self._sync_cards(); self.canvas.on_cards(); self.canvas.update()
    def undo(self):
        if self.doc.do_undo(): self._after_restore()
    def redo(self):
        if self.doc.do_redo(): self._after_restore()
    def _after_restore(self):
        a = B.get(self.rig["anims"], self.doc.anim["id"]) or self.rig["anims"][0]; self.doc.anim = a; cv = self.canvas; ex = lambda k, i: B.get({"bone": self.rig["bones"], "part": self.rig["parts"], "group": self.rig["groups"]}[k], i) is not None
        cv.select_many([x for x in cv.msel if ex(*x)]) if any(not ex(*x) for x in cv.msel) else None
        if cv.sel and not ex(*cv.sel): cv.sel = None
        cv.sel_verts = set(); self.sheet.sel_keys = []; self.curve.show_keys([]); self.rebuild_tree(); self.refresh_anims(); self.refresh_props(); self.layers.build(); self.update_title(); self.canvas.update(); self.sheet.update()
    def begin_edit(self):
        if not self._edit_open: self.doc.checkpoint(); self._edit_open = True
    def end_edit(self): self._edit_open = False
    # ---- mesh / weights
    def ensure_mesh(self, p, quiet=False):
        if p is None or p.get("mesh"): return
        im = self.rig["images"].get(p.get("img"))
        if not im: return
        self.doc.checkpoint(); p["mesh"] = B.build_mesh(self.rig, p, float(self.rig["cfg"].get("mesh_density", 5.0)))
        mine = {b["id"] for b in self.rig["bones"] if b.get("owner") == p["id"]}
        if mine: B.auto_weights(self.rig, p, mine, self.sharp)
        elif p.get("bone"): p["mesh"]["w"] = [[[p["bone"], 1.0]] for _ in p["mesh"]["uv"]]
        self.doc.touch(); self.doc.dirty = True; self.layers.build(); self.update_title()
        if not quiet: self.toast("Auto mesh: %d vertices, %d triangles" % (len(p["mesh"]["uv"]), len(p["mesh"]["t"])))
    def _gen_mesh(self):
        p = self.canvas.cur_part()
        if p is None: self.toast("Select a picture first"); return
        self.doc.checkpoint(); p.pop("mesh", None); self.ensure_mesh(p); self.canvas.sel_verts = set(); self.canvas.update()
    def _del_mesh(self):
        p = self.canvas.cur_part()
        if p is not None and p.get("mesh"): self.doc.checkpoint(); p.pop("mesh", None); self.canvas.sel_verts = set(); self.doc.touch(); self.layers.build(); self.canvas.update()
    def _auto_weight(self):
        p = self.canvas.cur_part()
        if p is None: self.toast("Select a picture first"); return
        if not self.rig["bones"]: self.toast("Draw some bones first"); return
        self.ensure_mesh(p, quiet=True); self.doc.checkpoint(); B.auto_weights(self.rig, p, None, self.sharp, (sorted(self.canvas.sel_verts) or None))
        if not self.canvas.sel_verts: p["mesh"]["painted"] = False
        self.doc.touch(); self.canvas.update(); self.toast("Weights set from the bones")
    def _smooth_weights(self):
        p = self.canvas.cur_part()
        if p is not None and p.get("mesh"): self.doc.checkpoint(); B.smooth_weights(p["mesh"], 1); self.doc.touch(); self.canvas.update()
    def _normalize_weights(self):
        p = self.canvas.cur_part()
        if p is not None and p.get("mesh"): self.doc.checkpoint(); B.normalize_weights(p["mesh"], (sorted(self.canvas.sel_verts) or None)); p["mesh"]["painted"] = True; self.doc.touch(); self.canvas.update()
    def _assign(self):
        p = self.canvas.cur_part(); b = self.canvas.wbone
        if p is None or not p.get("mesh"): self.toast("Select a picture with a mesh"); return
        if not b or not B.get(self.rig["bones"], b): self.toast("Select a bone first (Select tool)"); return
        if not self.canvas.sel_verts: self.toast("Lasso some vertices first"); return
        self.doc.checkpoint(); B.set_weight(p["mesh"], sorted(self.canvas.sel_verts), b, self.vweight / 100.0, normalize=bool(self.auto_norm)); p["mesh"]["painted"] = True; self.doc.touch(); self.canvas.update(); self.toast("%d vertices set to %d%%" % (len(self.canvas.sel_verts), self.vweight))
    def verts_changed(self):
        n = len(self.canvas.sel_verts); self.lasso_info.setText("%d vertices selected" % n); bn = B.get(self.rig["bones"], self.canvas.wbone)
        self.lasso_bone.setText("Bone: " + (bn["name"] if bn else "— select one with the Select tool")); self.canvas.update()
    # ---- tool option cards (over the canvas, bottom left)
    def _build_mode_bars(self):
        """The mode choosers at the top left of the canvas: Mesh editor (Auto / Pencil / Eraser / Edit) and Bone (Drag / Line)."""
        self.mode_bars = {}; self.mode_btns = {}
        for grp, items in (("mesh", (("mesh", "Auto", "Auto mesh"), ("vadd", "Pencil", "Pencil: add mesh points"), ("vdel", "Eraser", "Eraser: delete mesh points"), ("vedit", "Edit", "Edit: select and move mesh points"))),
                           ("bone", (("bone", "Drag", "Drag to draw a bone"), ("line", "Line", "Click points along a tail / hair, then Enter: a chain of bones")))):
            f = Card(); f.setStyleSheet("QFrame{background:rgba(34,34,40,235);border:1px solid #3d3d46;border-radius:10px}"); h = QHBoxLayout(f); h.setContentsMargins(6, 6, 6, 6); h.setSpacing(4)
            for key, txt, tip in items:
                b = QToolButton(); b.setCheckable(True); b.setIcon(tool_icon(key, 24)); b.setIconSize(QSize(24, 24)); b.setText(txt); b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); b.setToolTip(tip); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setFixedHeight(32)
                b.setStyleSheet("QToolButton{background:transparent;color:#e8e8ee;border:1px solid transparent;border-radius:8px;padding:0 8px}QToolButton:hover{background:#2f2f37}QToolButton:checked{background:#1e3a8a;border:1px solid #2f6bff}")
                b.clicked.connect(lambda _=False, k=key: self.pick_tool(k)); h.addWidget(b); self.mode_btns[key] = b
            self.mode_bars[grp] = f; self.canvas.add_card(f, top=True)
    def _build_cards(self):
        self.cards_by_tool = {}; self._build_mode_bars()
        # auto mesh
        f, v = card_frame("Auto mesh"); s = Slider(1, 10, float(self.rig["cfg"].get("mesh_density", 5)), 5, 0); s.changed.connect(lambda x: self.rig["cfg"].__setitem__("mesh_density", float(x))); slider_row(v, "Density", s)
        s2 = Slider(1, 8, self.sharp, 3, 0); s2.changed.connect(lambda x: setattr(self, "sharp", float(x))); slider_row(v, "Sharpness", s2)
        r = QHBoxLayout(); r.addWidget(Btn("Generate", "refresh", "accent", "Cut the selected picture into a mesh", self._gen_mesh, h=28)); r.addWidget(Btn("Remove", "delete", "soft", "Back to a flat picture", self._del_mesh, h=28)); v.addLayout(r)
        r = QHBoxLayout(); r.addWidget(Btn("Auto weight", "center", "soft", "Give every vertex to the nearest bones", self._auto_weight, h=28)); r.addWidget(Btn("Smooth", "reset", "soft", "Soften the weights between neighbours", self._smooth_weights, h=28)); v.addLayout(r)
        self.cards_by_tool["mesh"] = f; self.canvas.add_card(f)
        # line deform
        f, v = card_frame("Line deform"); s = Slider(1, 12, self.line_n, 4, 0); s.changed.connect(lambda x: setattr(self, "line_n", int(x))); slider_row(v, "Bones", s)
        t = Toggle("Weight the selected picture to the chain", True); t.toggled.connect(lambda on: setattr(self, "line_weight", bool(on))); v.addWidget(t)
        r = QHBoxLayout(); r.addWidget(Btn("Finish", "done", "accent", "Make the chain (Enter)", lambda: self.canvas.finish_line(), h=28)); r.addWidget(Btn("Cancel", "close", "soft", "Esc", lambda: (setattr(self.canvas, "line_pts", []), self.canvas.update()), h=28)); v.addLayout(r)
        self.cards_by_tool["line"] = f; self.canvas.add_card(f)
        # link
        f, v = card_frame("Link"); self.lk_btns = {}
        row_ = QHBoxLayout(); row_.setSpacing(6)
        for key, txt, tip in (("link", "Link", "Drag FROM the child bone TO the mother bone (like a picture -> bone). The child follows the mother; turning the child moves only the child. A dashed line joins their heads. Head and tail are NOT joined."), ("parent", "Parent", "The head of the child joins the tail of the mother, all the way down the chain.")):
            b = QPushButton(txt); b.setCheckable(True); b.setToolTip(tip); b.setFocusPolicy(Qt.NoFocus); b.setFixedHeight(28)
            b.setStyleSheet("QPushButton{background:#2b2b33;color:#e8e8ee;border:1px solid #3d3d46;border-radius:8px}QPushButton:checked{background:#1e3a8a;border:1px solid #2f6bff}"); b.clicked.connect(lambda _=False, k=key: self._set_link_mode(k)); row_.addWidget(b); self.lk_btns[key] = b
        v.addLayout(row_); h = QLabel("Drag child bone → mother bone.  Drag picture → bone to glue it.\nSame drag again = unlink · drag the other way = flip · empty space = unlink all."); h.setStyleSheet("color:#a9a9b6;background:transparent;font-size:11px"); v.addWidget(h)
        self.lk_btns[self.link_mode].setChecked(True); self.cards_by_tool["link"] = f; self.canvas.add_card(f)
        # weight paint
        f, v = card_frame("Weight paint"); self.wp_name = QLabel("Select a bone"); self.wp_name.setStyleSheet("color:#a9a9b6;background:transparent"); v.addWidget(self.wp_name)
        self.wp_size = Slider(4, 300, self.brush_r, 40, 0); self.wp_size.changed.connect(lambda x: setattr(self, "brush_r", float(x))); slider_row(v, "Brush size", self.wp_size)
        s = Slider(1, 100, self.brush_str, 50, 0); s.changed.connect(lambda x: setattr(self, "brush_str", float(x))); slider_row(v, "Strength", s)
        t = Toggle("Subtract (erase)  ·  or hold Shift", False); t.toggled.connect(lambda on: setattr(self, "brush_sub", bool(on))); v.addWidget(t)
        t = Toggle("Auto normalize (other bones give way)", False); t.setToolTip("OFF (like Blender): every bone has its own weight, so several bones can cover the same place; they are shared out when drawn.\nON: painting a bone takes the weight from the others so the sum stays 100%."); t.toggled.connect(lambda on: setattr(self, "auto_norm", bool(on))); v.addWidget(t)
        v.addWidget(Btn("Normalize all", "done", "soft", "Make the weights of every vertex of this picture add up to 100% (the ratios stay)", self._normalize_weights, h=28))
        r = QHBoxLayout(); r.addWidget(Btn("Auto weight", "center", "soft", "Start again from the distance to the bones", self._auto_weight, h=28)); r.addWidget(Btn("Smooth", "reset", "soft", "Soften the weights between neighbours", self._smooth_weights, h=28)); v.addLayout(r)
        self.cards_by_tool["weight"] = f; self.canvas.add_card(f)
        # lasso
        f, v = card_frame("Lasso — weights"); self.lasso_info = QLabel("0 vertices selected"); self.lasso_info.setStyleSheet("color:#e8e8ee;background:transparent"); v.addWidget(self.lasso_info)
        self.lasso_bone = QLabel("Bone: —"); self.lasso_bone.setStyleSheet("color:#a9a9b6;background:transparent"); v.addWidget(self.lasso_bone)
        s = Slider(0, 100, self.vweight, 100, 0); s.changed.connect(lambda x: setattr(self, "vweight", float(x))); slider_row(v, "Weight", s, "%d%%")
        r = QHBoxLayout(); r.addWidget(Btn("Assign to bone", "done", "accent", "Give the selected vertices this weight for the selected bone", self._assign, h=28)); r.addWidget(Btn("Smooth", "reset", "soft", "", self._smooth_weights, h=28)); v.addLayout(r)
        r = QHBoxLayout(); r.addWidget(Btn("Select all", "center", "soft", "", self._select_all_verts, h=28)); r.addWidget(Btn("Clear", "close", "soft", "Esc", lambda: (self.canvas.sel_verts.clear(), self.verts_changed()), h=28)); v.addLayout(r)
        self.cards_by_tool["lasso"] = f; self.canvas.add_card(f)
        # physic
        f, v = card_frame("Physic"); self.ph_name = QLabel("Select a bone"); self.ph_name.setStyleSheet("color:#a9a9b6;background:transparent"); v.addWidget(self.ph_name)
        self.ph_on = Toggle("Swing (hair, tail, cloth …)", False); self.ph_on.toggled.connect(lambda on: self._phys_set("on", bool(on))); v.addWidget(self.ph_on); self.ph = {}
        for key, txt in (("stiff", "Stiffness"), ("damp", "Damping"), ("grav", "Gravity")):
            s = Slider(0, 100, B.PHYS_DEFAULT[key], B.PHYS_DEFAULT[key], 0); s.changed.connect(lambda x, k=key: self._phys_set(k, float(x))); s.pressed.connect(self.begin_edit); s.released.connect(self.end_edit); slider_row(v, txt, s); self.ph[key] = s
        v.addWidget(Btn("Apply to child bones", "duplicate", "soft", "Copy these values to every bone below the selected one", self._phys_children, h=28))
        self.cards_by_tool["physic"] = f; self.canvas.add_card(f); self._sync_cards()
    def _set_link_mode(self, k):
        self.link_mode = k
        for kk, b in self.lk_btns.items(): b.setChecked(kk == k)
    def set_brush(self, r):
        self.brush_r = max(4.0, min(300.0, float(r))); self.wp_size.setValue(self.brush_r); self.canvas.update()
    def _select_all_verts(self):
        p = self.canvas.cur_part()
        if p is not None and p.get("mesh"): self.canvas.sel_verts = set(range(len(p["mesh"]["uv"]))); self.verts_changed()
    def _sel_bone(self):
        s = self.canvas.sel
        return B.get(self.rig["bones"], s[1]) if (s and s[0] == "bone") else None
    def _sync_cards(self):
        b = self._sel_bone(); self._loading = True
        wb = B.get(self.rig["bones"], self.canvas.wbone) if self.canvas.wbone else None; self.wp_name.setText(("Painting: " + wb["name"]) if wb else "Select a bone (Select tool)")
        self.ph_name.setText(("Bone: " + b["name"]) if b else "Select a bone (Select tool)"); ph = dict(B.PHYS_DEFAULT); ph.update((b or {}).get("phys") or {}); self.ph_on.setChecked(bool(ph["on"]))
        for k, s in self.ph.items(): s.setValue(ph[k])
        self._loading = False; self.verts_changed()
        if hasattr(self, "layers"): self._sync_opacity()
    def _phys_set(self, key, val):
        if self._loading: return
        b = self._sel_bone()
        if b is None: return
        self.begin_edit(); b.setdefault("phys", dict(B.PHYS_DEFAULT))[key] = val; self.doc.touch(); self.doc.dirty = True; self.canvas.update(); self.update_title()
    def _phys_children(self):
        b = self._sel_bone()
        if b is None: return
        self.doc.checkpoint()
        for c in B.descendants(self.rig, b["id"]): B.get(self.rig["bones"], c)["phys"] = dict(b.get("phys") or B.PHYS_DEFAULT)
        self.doc.touch(); self.canvas.update(); self.toast("Copied to the child bones")
    # ---- opacity slider of the layer panel
    def _alpha_targets(self):
        cv = self.canvas; out = []
        if cv.sel and cv.sel[0] == "group": return [B.get(self.rig["groups"], cv.sel[1])]
        for k, i in cv.sel_items():
            if k == "part": out.append(B.get(self.rig["parts"], i))
        return [o for o in out if o is not None]
    def _sync_opacity(self):
        ts = self._alpha_targets(); self._loading = True; a = ts[0].get("alpha", 100.0) if ts else 100.0
        self.op_slider.setValue(a); self.op_lbl.setText("%d%%" % a); self.op_slider.setEnabled(bool(ts)); self._loading = False
    def _set_opacity(self, v):
        if self._loading: return
        ts = self._alpha_targets()
        for o in ts: o["alpha"] = float(v)
        if ts: self.op_lbl.setText("%d%%" % v); self.doc.touch(); self.doc.dirty = True; self.canvas.update(); self.refresh_props_values()
    def refresh_props_values(self): self._refresh_values()
    def new_group(self):
        """A new folder; the selected pictures (and bones' pictures) go into it."""
        r = self.rig; cv = self.canvas; self.doc.checkpoint(); g = {"id": new_id(), "name": "Folder %d" % (len(r["groups"]) + 1), "open": True, "hidden": False, "lock": False, "alpha": 100.0}; r["groups"].append(g)
        pids = [i for k, i in cv.sel_items() if k == "part"]
        for k, i in cv.sel_items():
            if k == "bone":
                b = B.get(r["bones"], i)
                if b and b.get("owner") and b["owner"] not in pids: pids.append(b["owner"])
        for i in pids: B.get(r["parts"], i)["group"] = g["id"]
        self.layers_changed(); cv.select("group", g["id"])
        if not pids: self.toast("Empty folder made — drag pictures onto it (or select pictures first, then press the folder button)")
    def delete_group(self, gid):
        self.doc.checkpoint(); r = self.rig; r["groups"] = [g for g in r["groups"] if g["id"] != gid]
        for p in r["parts"]:
            if p.get("group") == gid: p["group"] = None
        self.canvas.select(None, None); self.layers_changed(); self.toast("Folder deleted (the pictures are kept) — Ctrl+Z to undo")
    def delete_items(self, items):
        """Delete pictures (with their bones), bones (with the bones below them) and folders (the pictures stay)."""
        r = self.rig; items = list(items)
        if not items: return
        self.doc.checkpoint(); bones = set(); parts = set(); groups = set()
        for k, i in items:
            if k == "part": parts.add(i)
            elif k == "bone": bones.add(i); bones |= set(B.descendants(r, i))
            elif k == "group": groups.add(i)
        for b in r["bones"]:
            if b.get("owner") in parts: bones.add(b["id"])
        r["parts"] = [p for p in r["parts"] if p["id"] not in parts]; r["bones"] = [b for b in r["bones"] if b["id"] not in bones]; r["groups"] = [g for g in r["groups"] if g["id"] not in groups]
        for p in r["parts"]:
            if p.get("bone") in bones: p["bone"] = None
            if p.get("group") in groups: p["group"] = None
            m = p.get("mesh")
            if m and bones: m["w"] = [[x for x in ws if x[0] not in bones] for ws in m["w"]]
        for b in r["bones"]: b["links"] = [x for x in b["links"] if x not in bones]; b["lkids"] = [x for x in b.get("lkids", []) if x not in bones]
        for p in r["parts"]:
            if p.get("mask_part") in parts: p["mask_part"] = None                    # Patch 48: the picture that was its layer mask is gone
        for a in r["anims"]:
            for g in bones: a["tracks"].pop(g, None)
            for g in parts: a["ptracks"].pop(g, None)
        cv = self.canvas; cv.select(None, None); cv.last_part = None if cv.last_part in parts else cv.last_part; cv.wbone = None if cv.wbone in bones else cv.wbone; cv.sel_verts = set()
        self.layers_changed(); self.sheet.update(); self.toast("Deleted — Ctrl+Z to undo")
    # ---- bones tree
    def rebuild_tree(self):
        if hasattr(self, "layers"): self.layers.build()
    def _sync_tree_selection(self): pass
    def _tree_pick(self): pass
    def _tree_edit(self, it, col): pass
    # ---- properties
    def _build_props(self):
        self.pstack = FadeStack(); self.props.body.addWidget(self.pstack, 1)
        def page():
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 4, 0); v.setSpacing(8); sa.setWidget(w); return sa, v
        def num(lo, hi, dec, suf="", scrub=1.0):
            n = NumberField(0, lo, hi, dec, suf, "", scrub); n.changed.connect(lambda *_: self.begin_edit()); n.finished.connect(self.end_edit); return n
        def line(sec, txt, *ws):
            r = QHBoxLayout(); r.setSpacing(6); l = label(txt, True, 12); l.setFixedWidth(70); r.addWidget(l)
            for i, w in enumerate(ws): r.addWidget(w, 1)
            sec.body.addLayout(r)
        # empty
        sa, v = page(); sec = Section("Rig", "layers"); self.info = label("", True, 12); self.info.setWordWrap(True); sec.body.addWidget(self.info)
        sec.body.addWidget(Btn("Settings…", "settings", "soft", "", self.open_config, h=28)); v.addWidget(sec); v.addStretch(); self.pstack.addWidget(sa)
        # bone
        sa, v = page(); sec = Section("Bone", "move"); self.b_name = TextField(); self.b_name.textChanged.connect(lambda t: self._set_obj("bone", "name", t))
        self.b_parent = Dropdown([], 120); self.b_parent.changed.connect(self._bone_parent); line(sec, "Name", self.b_name); line(sec, "Parent", self.b_parent)
        self.b_owner = label("", True, 11); self.b_owner.setWordWrap(True); sec.body.addWidget(self.b_owner)
        sec.body.addWidget(Btn("Weight paint this bone", "adjust", "soft", "Paint how strongly this bone moves its picture (W)", lambda: self.pick_tool("weight"), h=28)); v.addWidget(sec)
        self.b_setup = Section("Rest pose (pivot)", "center"); self.b_x = num(-9999, 9999, 1, "", 0.5); self.b_y = num(-9999, 9999, 1, "", 0.5); self.b_rot = num(-3600, 3600, 1, " °", 0.5); self.b_len = num(1, 9999, 0, "", 1.0)
        for n, k in ((self.b_x, "x"), (self.b_y, "y"), (self.b_rot, "rot"), (self.b_len, "len")): n.changed.connect(lambda val, k=k: self._set_obj("bone", k, val, rest=True))
        line(self.b_setup, "Pivot X", self.b_x); line(self.b_setup, "Pivot Y", self.b_y); line(self.b_setup, "Angle", self.b_rot); line(self.b_setup, "Length", self.b_len); v.addWidget(self.b_setup)
        self.b_anim = Section("Pose at the playhead", "keys"); self.ch = {}
        for ch, lo, hi, dec, suf in (("rot", -3600, 3600, 1, " °"), ("x", -9999, 9999, 1, ""), ("y", -9999, 9999, 1, ""), ("sx", 1, 1000, 0, " %"), ("sy", 1, 1000, 0, " %")):
            n = num(lo, hi, dec, suf, 0.5 if ch != "sx" and ch != "sy" else 1.0); n.changed.connect(lambda val, ch=ch: self._set_channel(ch, val)); self.ch[ch] = n; line(self.b_anim, B.CH_LABEL[ch], n)
        rr = QHBoxLayout(); rr.addWidget(Btn("Key all", "keyframe", "soft", "Make a keyframe of every value of this bone at the playhead (K)", self.key_selected, h=28)); rr.addWidget(Btn("Reset pose", "reset", "soft", "Remove this bone's keys at the playhead", self.reset_pose, h=28)); self.b_anim.body.addLayout(rr)
        v.addWidget(self.b_anim); v.addStretch(); self.pstack.addWidget(sa)
        # part
        sa, v = page(); sec = Section("Picture", "image"); self.p_name = TextField(); self.p_name.textChanged.connect(lambda t: self._set_obj("part", "name", t))
        self.p_bone = Dropdown([], 120); self.p_bone.changed.connect(self._part_bone); line(sec, "Name", self.p_name); line(sec, "Glued to", self.p_bone)
        sec.body.addWidget(Btn("Make a bone here", "plus", "soft", "Create a bone whose pivot is the middle of this picture and glue the picture to it", self.bone_for_part, h=28))
        self.p_vis = Toggle("Visible", True); self.p_vis.toggled.connect(lambda v_: self._set_obj("part", "visible", bool(v_), now=True)); sec.body.addWidget(self.p_vis); v.addWidget(sec)
        sec = Section("Place (rest pose)", "move"); self.p_x = num(-9999, 9999, 1, "", 0.5); self.p_y = num(-9999, 9999, 1, "", 0.5); self.p_rot = num(-3600, 3600, 1, " °", 0.5)
        self.p_sx = num(1, 2000, 0, " %", 1.0); self.p_sy = num(1, 2000, 0, " %", 1.0); self.p_a = num(0, 100, 0, " %", 1.0)
        for n, k in ((self.p_x, "x"), (self.p_y, "y"), (self.p_rot, "rot"), (self.p_sx, "sx"), (self.p_sy, "sy")): n.changed.connect(lambda val, k=k: self._set_obj("part", k, val))
        self.p_a.changed.connect(self._set_part_alpha)
        line(sec, "X", self.p_x); line(sec, "Y", self.p_y); line(sec, "Angle", self.p_rot); line(sec, "Scale X", self.p_sx); line(sec, "Scale Y", self.p_sy); line(sec, "Opacity", self.p_a); v.addWidget(sec)
        sec = Section("Layer", "layers")                                                   # Patch 48: blend mode, clipping mask, layer mask
        self.p_blend = Dropdown([(b.title(), b) for b in B.FX_BLENDS], 120); self.p_blend.changed.connect(lambda *_: self._set_part_fx("blend", self.p_blend.currentData())); line(sec, "Blend", self.p_blend)
        self.p_clip = Toggle("Clipping mask", False, "Show this picture only where the picture below it (the nearest one that is not clipped) has colour"); self.p_clip.toggled.connect(lambda on: self._set_part_fx("clip", bool(on))); sec.body.addWidget(self.p_clip)
        self.p_mask = Dropdown([("(none)", "")], 120); self.p_mask.changed.connect(lambda *_: self._set_part_fx("mask_part", self.p_mask.currentData() or None)); line(sec, "Layer mask", self.p_mask)
        self.p_minv = Toggle("Invert the mask", False, "Show the picture where the mask picture is empty instead. The mask picture can be hidden (eye): it still masks."); self.p_minv.toggled.connect(lambda on: self._set_part_fx("mask_inv", bool(on))); sec.body.addWidget(self.p_minv)
        nt = label("Blend, clipping and masks are drawn by the CPU renderer (slower than the graphics card).", True, 11); nt.setWordWrap(True); sec.body.addWidget(nt); v.addWidget(sec)
        sec = Section("Order", "layers"); rr = QHBoxLayout()
        rr.addWidget(Btn("Forward", "up", "soft", "Draw this picture above the next one", lambda: self.move_z(1), h=28)); rr.addWidget(Btn("Backward", "down", "soft", "Draw this picture below the next one", lambda: self.move_z(-1), h=28)); sec.body.addLayout(rr)
        sec.body.addWidget(Btn("Duplicate", "duplicate", "soft", "", self.dup_part, h=28)); v.addWidget(sec); v.addStretch(); self.pstack.addWidget(sa)
        # folder
        sa, v = page(); sec = Section("Folder", "folder"); self.g_name = TextField(); self.g_name.textChanged.connect(lambda t: self._set_group("name", t)); line(sec, "Name", self.g_name)
        self.g_alpha = num(0, 100, 0, " %", 1.0); self.g_alpha.changed.connect(lambda val: self._set_group("alpha", float(val))); line(sec, "Opacity", self.g_alpha)
        self.g_vis = Toggle("Visible", True); self.g_vis.toggled.connect(lambda on: self._set_group("hidden", not on, now=True)); sec.body.addWidget(self.g_vis)
        self.g_lock = Toggle("Locked (cannot be picked on the canvas)", False); self.g_lock.toggled.connect(lambda on: self._set_group("lock", bool(on), now=True)); sec.body.addWidget(self.g_lock)
        sec.body.addWidget(Btn("Delete folder (keep pictures)", "delete", "soft", "", lambda: self.delete_group(self.canvas.sel[1]), h=28)); v.addWidget(sec); v.addStretch(); self.pstack.addWidget(sa)
        # several things selected
        sa, v = page(); sec = Section("Selection", "layers"); self.m_info = label("", True, 12); self.m_info.setWordWrap(True); sec.body.addWidget(self.m_info)
        self.m_alpha = num(0, 100, 0, " %", 1.0); self.m_alpha.changed.connect(self._multi_alpha); line(sec, "Opacity", self.m_alpha)
        self.m_bone = Dropdown([], 120); self.m_bone.changed.connect(self._multi_bone); line(sec, "Glued to", self.m_bone)
        rr = QHBoxLayout(); rr.addWidget(Btn("Show", "show", "soft", "", lambda: self._multi_flag("visible", True), h=28)); rr.addWidget(Btn("Hide", "hide", "soft", "", lambda: self._multi_flag("visible", False), h=28)); sec.body.addLayout(rr)
        rr = QHBoxLayout(); rr.addWidget(Btn("Lock", "lock", "soft", "", lambda: self._multi_flag("lock", True), h=28)); rr.addWidget(Btn("Unlock", "unlock", "soft", "", lambda: self._multi_flag("lock", False), h=28)); sec.body.addLayout(rr); v.addWidget(sec)
        sec = Section("Move together", "move"); self.m_dx = NumberField(0, -9999, 9999, 1, "", "", 0.5); self.m_dy = NumberField(0, -9999, 9999, 1, "", "", 0.5); line(sec, "By X", self.m_dx); line(sec, "By Y", self.m_dy)
        sec.body.addWidget(Btn("Move", "move", "soft", "Move the selected pictures and bones by this much", self._multi_move, h=28)); v.addWidget(sec)
        sec = Section("Organise", "folder"); sec.body.addWidget(Btn("Put in a new folder", "folder", "soft", "", self.new_group, h=28)); sec.body.addWidget(Btn("Delete all selected", "delete", "danger", "", self.delete_sel, h=28)); v.addWidget(sec); v.addStretch(); self.pstack.addWidget(sa)
    def _sel_obj(self):
        s = self.canvas.sel
        if not s: return None, None
        return s[0], B.get({"bone": self.rig["bones"], "part": self.rig["parts"], "group": self.rig["groups"]}[s[0]], s[1])
    def _set_group(self, key, val, now=False):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "group": return
        if key == "name" or now: self.doc.checkpoint()
        else: self.begin_edit()
        o[key] = val; self.doc.touch(); self.doc.dirty = True; self.update_title(); self.canvas.update(); self.layers.build(); self._sync_opacity()
    def _multi_parts(self): return [B.get(self.rig["parts"], i) for k, i in self.canvas.sel_items() if k == "part"]
    def _multi_alpha(self, val):
        if self._loading: return
        self.begin_edit()
        for pt in self._multi_parts(): pt["alpha"] = float(val)
        self.doc.touch(); self.doc.dirty = True; self.canvas.update()
    def _multi_bone(self, *_):
        if self._loading: return
        self.doc.checkpoint()
        for pt in self._multi_parts(): pt["bone"] = self.m_bone.currentData()
        self.layers_changed()
    def _multi_flag(self, key, val):
        self.doc.checkpoint()
        for pt in self._multi_parts(): pt[key] = val
        self.layers_changed()
    def _multi_move(self):
        dx, dy = float(self.m_dx.value()), float(self.m_dy.value()); self.doc.checkpoint(); r = self.rig
        for k, i in self.canvas.sel_items():
            if k == "part": pt = B.get(r["parts"], i); pt["x"] += dx; pt["y"] += dy
            else:
                b = B.get(r["bones"], i)
                if b and not b.get("parent"): w = B.rest_world(r)[i]; self.canvas.set_bone_rest(b, head=(w[0, 2] + dx, w[1, 2] + dy))
        self.doc.touch(); self.canvas.update(); self.doc.dirty = True
    def refresh_props(self):
        self._loading = True; kind, o = self._sel_obj(); r = self.rig; cv = self.canvas; many = len(cv.sel_items()) > 1 and kind != "group"
        if many:
            parts = self._multi_parts(); nb = sum(1 for k, i in cv.sel_items() if k == "bone"); self.pstack.setCurrentIndex(4)
            self.m_info.setText("%d picture(s) and %d bone(s) selected.\nDrag on the canvas to move them together. Anything set here applies to all the selected pictures." % (len(parts), nb))
            self.m_alpha.setValue(parts[0].get("alpha", 100.0) if parts else 100.0); opts = [("(unchanged)", "__keep__"), ("(none)", None)] + [(b["name"], b["id"]) for b in r["bones"]]; self.m_bone.clear()
            for t_, d_ in opts: self.m_bone.addItem(t_, d_)
            self.m_bone.setCurrentIndex(0)
            for w in (self.m_alpha, self.m_bone): w.setEnabled(bool(parts))
        elif o is None:
            self.pstack.setCurrentIndex(0); self.info.setText("%d × %d px · %d picture(s) · %d bone(s) · %d animation(s)\n\nTools on the left: Auto mesh (M) · Bone (B) · Select (V) · Link (L) · Line deform (D) · Solo (S) · Lasso (A) · Physic (P) · Weight paint (W).\nSelect a picture first, then draw its bones. Drag a box with Select to pick several things. Hold Ctrl and drag a bone to place it without moving the picture. Wheel = zoom, Space/middle mouse = pan." % (r["w"], r["h"], len(r["parts"]), len(r["bones"]), len(r["anims"])))
        elif kind == "group":
            self.pstack.setCurrentIndex(3); self.g_name.setText(o["name"]); self.g_alpha.setValue(o.get("alpha", 100.0)); self.g_vis.setChecked(not o.get("hidden", False)); self.g_lock.setChecked(bool(o.get("lock", False)))
        elif kind == "bone":
            self.pstack.setCurrentIndex(1); self.b_name.setText(o["name"]); self.b_setup.setVisible(self.mode == "setup"); self.b_anim.setVisible(self.mode == "animate")
            opts = [("(none — root)", None)] + [(b["name"], b["id"]) for b in r["bones"] if b["id"] != o["id"] and b["id"] not in B.descendants(r, o["id"])]
            self.b_parent.clear()
            for t_, d_ in opts: self.b_parent.addItem(t_, d_)
            self.b_parent.setCurrentIndex(max(0, next((i for i, (_, d_) in enumerate(opts) if d_ == o.get("parent")), 0)))
            ow = B.get(r["parts"], o.get("owner")); lk = [B.get(r["bones"], q) for q in o.get("links", [])]; kid = [x for x in lk if x and x["id"] in o.get("lkids", [])]; mom = [x for x in lk if x and o["id"] in x.get("lkids", [])]; old_ = [x for x in lk if x and x not in kid and x not in mom]
            self.b_owner.setText("Moves only: " + (ow["name"] if ow else "(no picture — old bone)") + ("\nLink mother of (follow it): " + ", ".join(x["name"] for x in kid) if kid else "") + ("\nLink child of: " + ", ".join(x["name"] for x in mom) if mom else "") + ("\nLinked, no direction (drag from the child to the mother again): " + ", ".join(x["name"] for x in old_) if old_ else "") + ("\nHead joined to the tail of its parent" if o.get("parent") else ""))
            for n in (self.b_x, self.b_y): n.setEnabled(not o.get("parent"))
        else:
            self.pstack.setCurrentIndex(2); self.p_name.setText(o["name"]); self.p_vis.setChecked(bool(o.get("visible", True)))
            opts = [("(none)", None)] + [(b["name"], b["id"]) for b in r["bones"]]; self.p_bone.clear()
            for t_, d_ in opts: self.p_bone.addItem(t_, d_)
            self.p_bone.setCurrentIndex(max(0, next((i for i, (_, d_) in enumerate(opts) if d_ == o.get("bone")), 0)))
            self.p_blend.setCurrentData(o.get("blend", "normal")); self.p_clip.setChecked(bool(o.get("clip", False))); self.p_minv.setChecked(bool(o.get("mask_inv", False)))
            self.p_mask.clear(); self.p_mask.addItem("(none)", "")
            for q in sorted(r["parts"], key=lambda q: -q.get("z", 0)):
                if q["id"] != o["id"]: self.p_mask.addItem(q["name"], q["id"])
            self.p_mask.setCurrentData(o.get("mask_part") or "")
        self._loading = False; self._refresh_values()
    def _refresh_values(self):
        self._loading = True; kind, o = self._sel_obj()
        if o is not None and kind == "bone":
            for n, k in ((self.b_x, "x"), (self.b_y, "y"), (self.b_rot, "rot"), (self.b_len, "len")): n.setValue(o[k])
            chv = B.bone_channels(self.doc.anim, o["id"], self.t)
            for ch, n in self.ch.items(): n.setValue(chv[ch])
        elif o is not None and kind == "part":
            for n, k in ((self.p_x, "x"), (self.p_y, "y"), (self.p_rot, "rot"), (self.p_sx, "sx"), (self.p_sy, "sy")): n.setValue(o[k])
            al = o.get("alpha", 100.0)
            if self.mode == "animate" and o["id"] in self.doc.anim["ptracks"]: al = B.track_value(self.doc.anim["ptracks"][o["id"]].get("alpha"), self.t, 100.0)
            self.p_a.setValue(al)
        self._loading = False
    def _set_obj(self, kind, key, val, rest=False, now=False):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != kind: return
        if key in ("name", "visible") or now: self.doc.checkpoint()
        if kind == "bone" and rest and key in ("x", "y", "rot", "len"):
            r = self.rig; kids = B.children_of(r, o["id"]); old = {c["id"]: B.rest_world(r)[c["id"]] for c in kids}
            o[key] = float(val); nb = B.rest_world(r)[o["id"]]
            if key != "len":
                for c in kids: l2 = B.inv(nb) @ old[c["id"]]; c["x"], c["y"], c["rot"] = float(l2[0, 2]), float(l2[1, 2]), float(B.mat_angle(l2))
        else: o[key] = val if key in ("name", "visible") else float(val)
        self.doc.touch(geom=(kind == "part")); self.doc.dirty = True; self.update_title(); self.canvas.update()
        if key in ("name", "visible"): self.rebuild_tree()
    def _set_part_alpha(self, val):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "part": return
        if self.mode == "animate": self.begin_edit(); self.doc.set_key(o["id"], "alpha", self.t, val, part=True)
        else: o["alpha"] = float(val)
        self.doc.touch(); self.doc.dirty = True; self.canvas.update(); self.sheet.update()
    def _set_channel(self, ch, val):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "bone": return
        self.begin_edit(); self.doc.set_key(o["id"], ch, self.t, val); self.doc.touch(); self.doc.dirty = True; self.update_title(); self.canvas.update(); self.sheet.update()
    def _bone_parent(self, *_):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "bone": return
        new = self.b_parent.currentData()
        if new == o.get("parent"): return
        self.doc.checkpoint(); r = self.rig; rest = B.rest_world(r); w = rest[o["id"]]; o["parent"] = new
        par = rest.get(new) if new else None; loc = (B.inv(par) if par is not None else np.eye(3)) @ w
        o["x"], o["y"], o["rot"] = float(loc[0, 2]), float(loc[1, 2]), float(B.mat_angle(loc)); self.doc.touch(); self.rebuild_tree(); self.canvas.update()
    def _set_part_fx(self, key, val):
        """Patch 48: blend / clip / mask_part / mask_inv of the selected picture."""
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "part": return
        self.doc.checkpoint(); o[key] = val; self.doc.touch(geom=True); self.doc.dirty = True; self.update_title(); self.rebuild_tree(); self.canvas.update()
    def _part_bone(self, *_):
        if self._loading: return
        k, o = self._sel_obj()
        if o is None or k != "part": return
        self.doc.checkpoint(); o["bone"] = self.p_bone.currentData(); self.doc.touch(); self.rebuild_tree(); self.canvas.update()
    def bone_for_part(self):
        k, o = self._sel_obj()
        if o is None or k != "part": return
        self.doc.checkpoint(); r = self.rig; par = self.canvas.sel and None
        sz = B.part_image_size(r, o); L = max(20.0, sz[1] * o["sy"] / 200.0)
        nb = {"id": new_id(), "name": o["name"] + " bone", "parent": None, "x": float(o["x"]), "y": float(o["y"]), "rot": -90.0, "len": L, "owner": o["id"], "links": [], "hidden": False}; r["bones"].append(nb)
        o["bone"] = nb["id"]; self.canvas._bone_added(o); self.doc.touch(); self.canvas.select("bone", nb["id"]); self.rebuild_tree(); self.canvas.update()
    def move_z(self, d):
        k, o = self._sel_obj()
        if o is None or k != "part": return
        self.doc.checkpoint(); lst = B.sorted_parts(self.rig); i = lst.index(o); j = max(0, min(len(lst) - 1, i + d))
        lst[i], lst[j] = lst[j], lst[i]
        for n, p in enumerate(lst): p["z"] = n
        self.doc.touch(); self.rebuild_tree(); self.canvas.update()
    def dup_part(self):
        k, o = self._sel_obj()
        if o is None or k != "part": return
        self.doc.checkpoint(); n = copy.deepcopy(o); n["id"] = new_id(); n["name"] = o["name"] + " copy"; n["x"] += 30; n["y"] += 30; n["z"] = max(p["z"] for p in self.rig["parts"]) + 1
        self.rig["parts"].append(n); self.doc.touch(); self.canvas.select("part", n["id"]); self.rebuild_tree(); self.canvas.update()
    # ---- adding / deleting
    def pick_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add pictures", self.app.settings["asset_folder"], "Pictures (*" + " *".join(sorted(IMAGE_EXT | GIF_EXT)) + ")")
        if paths: self.add_images(paths)
    def add_files(self, paths):
        pics = [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_EXT | GIF_EXT]; psds = [p for p in paths if p.lower().endswith(".psd")]
        if pics: self.add_images(pics)
        for p in psds: self.import_psd(p)
    def pick_psd(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a Photoshop file", self.app.settings["asset_folder"], "Photoshop (*.psd)")
        if path: self.import_psd(path)
    def add_images(self, paths):
        r = self.rig; added = None; self.doc.checkpoint()
        for p in paths:
            if os.path.splitext(p)[1].lower() not in IMAGE_EXT | GIF_EXT: continue
            res = B.image_entry(p)
            if not res: _toast(self.app, "Cannot read " + os.path.basename(p)); continue
            ent, (iw, ih) = res; iid = new_id(); r["images"][iid] = ent; sc = min(100.0, 80.0 * min(r["w"] / iw, r["h"] / ih)) if (iw > r["w"] or ih > r["h"]) else 100.0
            part = {"id": new_id(), "name": os.path.splitext(os.path.basename(p))[0], "img": iid, "bone": None, "x": 0.0, "y": 0.0, "rot": 0.0, "sx": sc, "sy": sc, "z": (max((q["z"] for q in r["parts"]), default=-1) + 1), "alpha": 100.0, "visible": True, "lock": False, "color": "#ff3b30", "group": None}
            r["parts"].append(part); added = part
        if added: self.doc.touch(); self.canvas.select("part", added["id"]); self.layers_changed()
    def import_psd(self, path):
        """Every layer of the PSD becomes a picture at the same place; PSD folders become folders."""
        from ..render import psd_reader as PR
        try: W, H, layers = PR.read_psd(path)
        except Exception as ex: self.toast("Cannot import %s: %s" % (os.path.basename(path), ex)); return
        if not layers: self.toast("No pixel layers in " + os.path.basename(path)); return
        r = self.rig; self.doc.checkpoint()
        if not r["parts"]: r["w"], r["h"] = int(W), int(H)
        gmap = {}; z0 = max((q["z"] for q in r["parts"]), default=-1) + 1; n = 0
        for L in layers:
            img = L["img"]; ih, iw = img.shape[:2]; ent = B.image_entry_array(img); iid = new_id(); r["images"][iid] = ent; gid = None
            if L["group"]:
                gkey = " / ".join(L["group"])
                if gkey not in gmap: g = {"id": new_id(), "name": L["group"][-1], "open": True, "hidden": False, "lock": False, "alpha": 100.0}; r["groups"].append(g); gmap[gkey] = g["id"]
                gid = gmap[gkey]
            r["parts"].append({"id": new_id(), "name": L["name"] or "Layer", "img": iid, "bone": None, "x": float(L["x"] + iw / 2.0 - W / 2.0), "y": float(L["y"] + ih / 2.0 - H / 2.0), "rot": 0.0, "sx": 100.0, "sy": 100.0, "z": z0 + n,
                               "alpha": float(L["opacity"]), "visible": bool(L["visible"]), "lock": False, "color": "#ff3b30", "group": gid}); n += 1
        self.canvas.select(None, None); self.layers_changed(); self.canvas.fit(); self.toast("Imported %d layer(s) and %d folder(s) from %s" % (n, len(gmap), os.path.basename(path)))
    def delete_sel(self):
        cv = self.canvas
        if self.sheet.sel_keys and self.mode == "animate" and (self.sheet.hasFocus() or cv.tool == "select" and not cv.sel_items()):
            sel = list(self.sheet.sel_keys); self.sheet.sel_keys = []; self.delete_keys(sel); self.model_dirty(); return
        if cv.tool in ("vadd", "vdel", "vedit"): cv.delete_selected_verts(); return            # in a mesh tool Delete is for mesh points only
        if cv.sel and cv.sel[0] == "group" and len(cv.msel) <= 1: self.delete_group(cv.sel[1]); return
        items = cv.sel_items() + [x for x in cv.msel if x[0] == "bone" and x not in cv.sel_items()]
        self.delete_items(items)
    # ---- animation bar
    def _build_anim_bar(self, bot):
        row = QHBoxLayout(); row.setSpacing(6)
        self.a_sel = Dropdown([], 150); self.a_sel.changed.connect(self._pick_anim); row.addWidget(self.a_sel)
        row.addWidget(Btn("New", "plus", "soft", "New animation", self.new_anim, h=28)); row.addWidget(Btn("Copy", "duplicate", "soft", "Duplicate this animation", self.dup_anim, h=28))
        row.addWidget(Btn("Rename", "text", "soft", "Rename this animation", self.rename_anim, h=28)); row.addWidget(Btn("", "delete", "danger", "Delete this animation", self.del_anim, h=28)); row.addSpacing(8)
        row.addWidget(Btn("", "previous", "ghost", "To the start", lambda: self.goto(0.0), h=28)); self.play_btn = Btn("", "play", "soft", "Play / pause (Space)", self.toggle_play, h=28); self.play_btn.setFixedWidth(46); row.addWidget(self.play_btn)
        self.t_field = NumberField(0, 0, 3600, 2, " s", "", 0.02); self.t_field.changed.connect(lambda v: self.goto(self.sheet.snap(v))); row.addWidget(self.t_field); row.addSpacing(6)
        row.addWidget(label("Length", True, 12)); self.a_dur = NumberField(2, 0.1, 600, 2, " s", "", 0.05); self.a_dur.changed.connect(self._set_dur); self.a_dur.finished.connect(self.end_edit); row.addWidget(self.a_dur)
        self.a_loop = Dropdown([(n, v) for n, v in B.LOOPS], 110); self.a_loop.changed.connect(self._set_loop); row.addWidget(self.a_loop); row.addSpacing(6)
        row.addWidget(Btn("Key", "keyframe", "soft", "Key the selected bone at the playhead (K)", self.key_selected, h=28))
        row.addWidget(Btn("Close loop", "refresh", "soft", "Copy the pose at 0 s to the end of the animation, so it loops without a jump", self.close_loop, h=28))
        # the motion curve of the selected keys is edited in the curve box at the bottom right (CurveBox)
        row.addStretch(); bot.body.addLayout(row)
    def refresh_anims(self):
        self._loading = True; a = self.doc.anim; self.a_sel.clear()
        for x in self.rig["anims"]: self.a_sel.addItem(x["name"], x["id"])
        self.a_sel.setCurrentIndex(max(0, self.a_sel.findData(a["id"]))); self.a_dur.setValue(a["dur"]); self.a_loop.setCurrentIndex(max(0, self.a_loop.findData(a.get("loop", "loop")))); self.t_field.setValue(self.t); self._loading = False; self.sync_ui()
    def _pick_anim(self, *_):
        if self._loading: return
        a = B.get(self.rig["anims"], self.a_sel.currentData())
        if a: self.doc.anim = a; self.t = min(self.t, a["dur"]); self.sheet.sel_keys = []; self.curve.show_keys([]); self.audio.stop(); self.doc.touch(); self.refresh_anims(); self.sheet.update(); self.canvas.update(); self._refresh_values()
    def new_anim(self):
        name, ok = QInputDialog.getText(self, "New animation", "Name:", text="Animation %d" % (len(self.rig["anims"]) + 1))
        if ok and name.strip(): self.doc.checkpoint(); a = B.new_anim(name.strip()); self.rig["anims"].append(a); self.doc.anim = a; self.t = 0.0; self.doc.touch(); self.refresh_anims(); self.canvas.update(); self.sheet.update()
    def dup_anim(self):
        self.doc.checkpoint(); a = copy.deepcopy(self.doc.anim); a["id"] = new_id(); a["name"] += " copy"; self.rig["anims"].append(a); self.doc.anim = a; self.doc.touch(); self.refresh_anims(); self.sheet.update()
    def rename_anim(self):
        name, ok = QInputDialog.getText(self, "Rename animation", "Name:", text=self.doc.anim["name"])
        if ok and name.strip(): self.doc.checkpoint(); self.doc.anim["name"] = name.strip(); self.refresh_anims()
    def del_anim(self):
        if len(self.rig["anims"]) < 2: _toast(self.app, "A rig needs at least one animation"); return
        self.doc.checkpoint(); self.rig["anims"].remove(self.doc.anim); self.doc.anim = self.rig["anims"][0]
        if not B.get(self.rig["anims"], self.rig["cfg"]["default_anim"]): self.rig["cfg"]["default_anim"] = self.doc.anim["id"]
        self.doc.touch(); self.refresh_anims(); self.sheet.update(); self.canvas.update()
    def _set_dur(self, v):
        if self._loading: return
        self.begin_edit(); self.doc.anim["dur"] = float(v); self.t = min(self.t, float(v)); self.doc.touch(); self.sheet.update(); self.canvas.update()
    def _set_loop(self, *_):
        if self._loading: return
        self.doc.checkpoint(); self.doc.anim["loop"] = self.a_loop.currentData(); self.doc.touch()
    def on_key_selection(self, sel):
        self.curve.show_keys(sel)
    def model_dirty(self): self.doc.dirty = True; self.update_title(); self.sheet.update(); self.canvas.update()
    def delete_keys(self, sel):
        self.doc.checkpoint()
        for k, oid, ch, is_part in sel: self.doc.drop_key(oid, ch, k, is_part)
        self.doc.touch(); self.sheet.update(); self.canvas.update()
    def key_selected(self):
        k, o = self._sel_obj()
        if o is None or k != "bone": _toast(self.app, "Select a bone first"); return
        if self.mode != "animate": self.set_mode("animate")
        self.doc.checkpoint(); chv = B.bone_channels(self.doc.anim, o["id"], self.t)
        for ch in B.CHANNELS: self.doc.set_key(o["id"], ch, self.t, chv[ch])
        self.doc.touch(); self.sheet.update()
    def reset_pose(self):
        k, o = self._sel_obj()
        if o is None or k != "bone": return
        self.doc.checkpoint(); tol = 0.5 / max(1, self.rig["cfg"]["fps"])
        for ch in B.CHANNELS:
            for key in list((self.doc.anim["tracks"].get(o["id"], {}).get(ch) or [])):
                if abs(key["t"] - self.t) < tol: self.doc.drop_key(o["id"], ch, key)
        self.doc.touch(); self.canvas.update(); self.sheet.update(); self._refresh_values()
    def close_loop(self):
        a = self.doc.anim; self.doc.checkpoint()
        for trs in (a["tracks"], a["ptracks"]):
            for oid, tr in trs.items():
                for ch, ks in tr.items():
                    if not ks: continue
                    v0 = B.track_value(ks, 0.0, 0.0)
                    ks[:] = [k for k in ks if abs(k["t"] - 0.0) > 1e-6 and abs(k["t"] - a["dur"]) > 1e-6]
                    ks.append({"t": 0.0, "v": v0, "e": [0, 0, 1, 1]}); ks.append({"t": a["dur"], "v": v0, "e": [0, 0, 1, 1]}); ks.sort(key=lambda k: k["t"])
        self.doc.touch(); self.sheet.update(); self.canvas.update(); _toast(self.app, "Loop closed")
    # ---- time
    def goto(self, t, scrub=True):
        self.t = max(0.0, min(self.doc.anim["dur"], float(t))); self._loading = True; self.t_field.setValue(self.t); self._loading = False
        self.canvas.update(); self.sheet.update(); self._refresh_values()
        if scrub and self.playing: self.audio_start()                      # the sound follows a jump of the playhead
    def step_frame(self, d): self.goto(self.sheet.snap(self.t + d / max(1, self.rig["cfg"]["fps"])))
    def toggle_play(self):
        self.playing = not self.playing; self.play_btn.setIcon(app_icon("pause" if self.playing else "play"))
        if self.playing:
            if self.mode != "animate": self.set_mode("animate")
            self._last = time.monotonic(); self._tick.start(); self.audio_start()
        else: self._tick.stop(); self.audio.stop()
    def _step(self):
        now = time.monotonic(); dt = now - self._last; self._last = now; a = self.doc.anim; t = self.t + dt
        if t >= a["dur"]:
            if a.get("loop") == "once": self.goto(a["dur"], False); self.toggle_play(); return
            t = t % a["dur"]; self.goto(t, False); self.audio_start(); return          # the loop starts the sound again
        self.goto(t, False)
    # ---- file / app
    def open_config(self):
        d = Bone2DConfigDialog(self.app, self.rig)
        if d.exec():
            self.doc.checkpoint(); rc, _ = d.apply(); self.doc.touch(); self.update_title(); self.canvas._fitted = False; self.canvas.fit(); self.refresh_anims(); self.refresh_props(); self.canvas.update()
    def save(self, quiet=False):
        try: self.doc.save()
        except Exception as ex: QMessageBox.warning(self, "Bone2D", "Could not save the rig:\n%s" % ex); return False
        self.update_title(); self.app.bone2d_saved(self.path)
        if not quiet: _toast(self.app, "Saved " + os.path.basename(self.path))
        return True
    def add_to_timeline(self):
        if not self.save(True): return
        self.app.bone2d_add_clip(self.path); _toast(self.app, "Added to the timeline — go back to the editor to see it")
    def close_page(self):
        if self.playing: self.toggle_play()
        if self.doc.dirty and not self.save(True): return
        self.audio.stop(); self.cleanup_audio(); self.closed.emit()


# ───────────────────────── the Inspector tab of a Bone2D clip ─────────────────────────
class Bone2DPanel(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self._loading = False; self._rig_path = None; v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        sec = Section("Bone2D", "layers"); self.rig_lbl = label("", True, 12); self.rig_lbl.setWordWrap(True); sec.body.addWidget(self.rig_lbl)
        def row(txt, w):
            r = QHBoxLayout(); r.setSpacing(6); l = label(txt, True, 12); l.setFixedWidth(70); r.addWidget(l); r.addWidget(w, 1); sec.body.addLayout(r)
        self.anim = Dropdown([], 120); self.loop = Dropdown([(n, v_) for n, v_ in B.CLIP_LOOPS], 120)
        self.speed = NumberField(100, 5, 1000, 0, " %", "", 1.0); self.off = NumberField(0, -3600, 3600, 2, " s", "", 0.05)
        row("Animation", self.anim); row("Loop", self.loop); row("Speed", self.speed); row("Offset", self.off)
        self.anim.changed.connect(lambda *_: self._edit("anim", self.anim.currentData())); self.loop.changed.connect(lambda *_: self._edit("loop", self.loop.currentData()))
        self.speed.changed.connect(lambda v_: self._edit("speed", float(v_))); self.off.changed.connect(lambda v_: self._edit("offset", float(v_)))
        sec.body.addWidget(Btn("Edit rig (Bone2D mode)", "move", "accent", "Open this rig in the Bone2D editor", self.edit_rig, h=30)); sec.body.addWidget(Btn("Settings…", "settings", "soft", "Rig and playback settings", self.config, h=28)); v.addWidget(sec); v.addStretch()
    def _clip(self): return self.app.sel_clip()
    def load(self, c):
        self._loading = True; self._rig_path = c.get("path")
        rs = B.cached_rig(c.get("path") or ""); cc = dict(B.DEFAULT_CLIP); cc.update(c.get("b2d") or {})
        self.rig_lbl.setText(os.path.basename(c.get("path") or "") + ("" if rs else "\n(file not found)")); self.anim.clear()
        if rs:
            for a in rs.rig["anims"]: self.anim.addItem(a["name"], a["id"])
            self.anim.setCurrentIndex(max(0, self.anim.findData(cc["anim"] or rs.rig["cfg"]["default_anim"])))
        self.loop.setCurrentIndex(max(0, self.loop.findData(cc["loop"]))); self.speed.setValue(cc["speed"]); self.off.setValue(cc["offset"]); self._loading = False
    def _edit(self, key, val):
        c = self._clip()
        if self._loading or not c or c.get("kind") != "bone2d": return
        rs = B.cached_rig(c.get("path") or "")
        if key == "anim" and rs and val == rs.rig["cfg"]["default_anim"]: val = ""
        self.app.checkpoint(); c.setdefault("b2d", dict(B.DEFAULT_CLIP))[key] = val; self.app.on_changed(insp=False)
    def edit_rig(self):
        c = self._clip()
        if c: self.app.open_bone2d(c.get("path"))
    def config(self):
        c = self._clip(); rs = B.cached_rig(c.get("path") or "") if c else None
        if not rs: return
        rig = copy.deepcopy({k: v for k, v in rs.rig.items() if k != "images"}); rig["images"] = rs.rig["images"]
        d = Bone2DConfigDialog(self.app, rig, c)
        if d.exec():
            self.app.checkpoint(); rc, cc = d.apply()
            if rc:
                try: B.save_file(c["path"], rig); self.app.bone2d_saved(c["path"])
                except Exception as ex: QMessageBox.warning(self.app, "Bone2D", "Could not save the rig:\n%s" % ex)
            self.app.on_changed()


# ───────────────────────── app side (mixin of the main window) ─────────────────────────
class Bone2DMixin:
    _b2d_page = None
    def bone2d_new(self):
        if not self.proj: return None
        name, ok = QInputDialog.getText(self, "New Bone2D rig", "Name of the character:", text="Character")
        if not ok or not name.strip(): return None
        path = unique_path(rig_dir(self), name.strip()); rig = B.new_rig(name.strip(), self.proj.w if self.proj.w == self.proj.h else 1024, self.proj.h if self.proj.w == self.proj.h else 1024)
        B.save_file(path, rig); path = os.path.abspath(path)
        if path not in self.proj.media: self.proj.media.append(path)
        if hasattr(self, "media"): self.media.reload()
        return path
    def bone2d_menu(self, anchor=None):
        """The Bone2D button: edit the selected clip's rig / pick one of the project's rigs / make a new one."""
        if not self.proj: return
        c = self.sel_clip()
        if c and c.get("kind") == "bone2d" and c.get("path") and os.path.isfile(c["path"]): self.open_bone2d(c["path"]); return
        m = QMenu(self); rigs = [p for p in self.proj.media if kind_of(p) == "bone2d" and os.path.isfile(p)]
        for p in rigs: m.addAction("Edit  " + os.path.basename(p), lambda p=p: self.open_bone2d(p))
        if rigs: m.addSeparator()
        m.addAction("＋  New Bone2D rig…", lambda: self.open_bone2d(self.bone2d_new()))
        m.addAction("Open a .bone2d file…", self._bone2d_open_file)
        m.exec(anchor if anchor is not None else QCursor.pos())
    def _bone2d_open_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open Bone2D rig", self.settings["asset_folder"], "Bone2D (*%s)" % B.EXT)
        if p:
            p = os.path.abspath(p)
            if p not in self.proj.media: self.proj.media.append(p); self.media.reload()
            self.open_bone2d(p)
    def open_bone2d(self, path):
        if not path or not self.proj: return
        if not os.path.isfile(path): QMessageBox.warning(self, "Bone2D", "File not found:\n" + path); return
        if self._b2d_page is not None: return
        self.stop_play(); self.exit_media_preview()
        try: page = Bone2DPage(self, path)
        except Exception as ex: QMessageBox.warning(self, "Bone2D", "Could not open the rig:\n%s" % ex); return
        self._b2d_page = page; self._b2d_actions = [(a, a.isEnabled()) for a in self.actions()]
        for a, _ in self._b2d_actions: a.setEnabled(False)           # the editor's shortcuts (Space, Ctrl+Z, Q / W ...) must not act on the timeline now
        page.closed.connect(self.close_bone2d); self.stack.addWidget(page); self.stack.setCurrentWidget(page)
    def close_bone2d(self):
        page = self._b2d_page
        if page is None: return
        self._b2d_page = None; self.stack.setCurrentWidget(self.editor); self.stack.removeWidget(page); page.deleteLater()
        for a, en in getattr(self, "_b2d_actions", []):
            try: a.setEnabled(en)
            except RuntimeError: pass
        self._b2d_actions = []
        if self.proj: self.on_changed()
    def bone2d_saved(self, path):
        """A rig file was written: every clip that uses it must be drawn again, and its picture in the media pool too."""
        if not self.proj: return
        try: rev = os.stat(path).st_mtime_ns
        except OSError: rev = time.time_ns()
        for c in self.proj.clips:
            if c.get("kind") == "bone2d" and c.get("path") == path: c["b2d_rev"] = rev
        for k in [k for k in self.thumbs.cache if isinstance(k, tuple) and len(k) > 1 and k[1] == path]: self.thumbs.cache.pop(k, None)
        try: self.media.list.itemDelegate()._pm.clear()
        except Exception: pass
        with self.renderer._src_lock: self.pool.reset()
        self.renderer.clear_preview_cache()
        if hasattr(self, "media"): self.media.list.viewport().update()
    def bone2d_add_clip(self, path):
        """Put a rig on the timeline at the playhead (same as dragging it from the media pool)."""
        if path not in self.proj.media: self.proj.media.append(path)
        self.add_files([path], self.t, None)

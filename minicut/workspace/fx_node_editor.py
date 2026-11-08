"""FX node editor (Patch 52): build your own effect out of blocks.

Looks and works like the main node editor (same cards, same dotted canvas, same way of drawing a wire) with its own
set of block colours, and it follows the app's dark theme (UI[...]). Every number / colour parameter is on the card and
has a socket, so another block can drive it; the key button next to a parameter offers it as a slider of the effect (in
the inspector, where it can be keyframed). The picture on the right is a live preview of ONE picture (a project media, a
file or a test picture) looping for three seconds.

All the rules (what can be linked, undo / redo, copy / paste, search) live in fx_graph_model.FxDoc; the preview is
fx_preview_engine.FxPreview. This file only draws them.
"""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.theme import *
from ..shared.core import *
from ..shared.widgets import *
from ..shared.ui import *
from ..render.fxpack.custom import (FX_NODE_TYPES, save_effect, load_all as reload_custom_fx, _mcfx_path, exposed_key, collect_param_specs)
from .fx_graph_model import FxDoc, node_rows, search_nodes, can_expose, param_spec, CAT_ORDER, normalize
from .fx_preview_engine import FxPreview, SAMPLE_NAMES, load_picture, LOOP_SECONDS
import json, math, os, re, hashlib, time

FX_HELP = ("Drag a block from the list (or double-click it, or press Tab on the canvas and type its name).\n"
           "Drag from a round socket to another socket to connect. Pick up a wire by dragging from the socket it ends in.\n"
           "Number and colour parameters have a socket too: wire a value block into it and the parameter follows it.\n"
           "The key button beside a parameter offers it as a slider of the effect (inspector, keyframes).\n\n"
           "Mouse: drag empty space = box select  -  middle button = pan  -  wheel = zoom  -  right click = menu.\n"
           "Keys: Del delete  -  Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+D copy / paste / cut / duplicate  -  M mute  -  "
           "Ctrl+Z / Ctrl+Y undo / redo  -  F fit  -  Ctrl+S save  -  Space play / pause the preview.")

# The block colours of this editor (another set than the video node editor, so the two are easy to tell apart).
FX_CATS = {"Image": "#2dd4bf", "Source": "#a3e635", "Color": "#fbbf24", "Blur": "#38bdf8",
           "Distort": "#fb7185", "Composite": "#a78bfa", "Utility": "#94a3b8", "Parameter": "#f0abfc"}
SOCK_COLORS = {"image": "#e8efff", "float": "#ffd86b", "color": "#ff9fd0"}
NODE_INK = QColor("#1f2430")
NODE_QSS = ("QLabel{background:transparent;color:#1f2430;} "
            "QLineEdit{background:rgba(255,255,255,170);color:#1f2430;border:1px solid rgba(0,0,0,40);border-radius:5px;padding:0 4px;} "
            "QToolButton{background:transparent;border:none;border-radius:5px;padding:0px;} "
            "QToolButton:hover{background:rgba(0,0,0,30);} QToolButton:checked{background:rgba(47,123,255,70);}")


def pastel(hex_color, mix=0.58):
    """A soft (pastel) version of a block colour: the colour mixed with white."""
    c = QColor(hex_color); m = lambda v: int(v + (255 - v) * mix)
    return QColor(m(c.red()), m(c.green()), m(c.blue()))


def cat_color(cat): return FX_CATS.get(cat, "#94a3b8")


def _dec_for(lo, hi, kind):
    if kind == "int": return 0
    span = abs(hi - lo)
    return 3 if span <= 5 else (2 if span <= 100 else 1)


def _scrub_for(lo, hi, kind):
    span = abs(hi - lo)
    return max(0.2 if kind == "int" else 0.005, min(50.0, span / 300.0))


# ── socket, wire ──────────────────────────────────────────────────────────────
class FxSocket(QGraphicsEllipseItem):
    R = 6
    def __init__(self, node, idx, is_out, kind):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R, node)
        self.node, self.idx, self.is_out, self.kind = node, idx, is_out, kind
        self._base = QColor(SOCK_COLORS.get(kind, "#e8efff"))
        self.setBrush(self._base); self.setPen(QPen(QColor(UI["ui_panel"]), 2)); self.setZValue(3)
        self.setCursor(Qt.CrossCursor); self.setAcceptHoverEvents(True)
    def hoverEnterEvent(self, e): self.setBrush(QColor(UI["ui_accent"]))
    def hoverLeaveEvent(self, e): self.setBrush(self._base)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.scene().begin_link(self); e.accept()
        else: e.ignore()
    def mouseMoveEvent(self, e): self.scene().drag_link(e.scenePos())
    def mouseReleaseEvent(self, e): self.scene().end_link(e.scenePos())


class FxLinkItem(QGraphicsPathItem):
    def __init__(self, a=None, b=None, rec=None):
        super().__init__(); self.a, self.b, self.rec = a, b, rec; self.end = None
        self.setFlag(QGraphicsItem.ItemIsSelectable, True); self.setZValue(0); self.setAcceptedMouseButtons(Qt.LeftButton)
        self.update_path()
    def shape(self):
        st = QPainterPathStroker(); st.setWidth(12); return st.createStroke(self.path())
    def update_path(self):
        p0 = self.a.scenePos() if self.a else self.end; p1 = self.b.scenePos() if self.b else self.end
        if p0 is None or p1 is None: return
        dx = max(50.0, abs(p1.x() - p0.x()) / 2); path = QPainterPath(p0)
        path.cubicTo(QPointF(p0.x() + dx, p0.y()), QPointF(p1.x() - dx, p1.y()), p1); self.setPath(path)
    def paint(self, p, opt, w=None):
        sel = self.isSelected()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(UI["ui_accent"] if sel else UI["nd_wire"]), 3 if sel else 2.2)); p.setBrush(Qt.NoBrush); p.drawPath(self.path())


# ── block (node) ──────────────────────────────────────────────────────────────
class FxNode(QGraphicsItem):
    W, HEAD, ROW = 250, 28, 26

    def __init__(self, scene, d):
        super().__init__(); self.sc = scene; self.d = d; self.nid = d["id"]; self.spec = FX_NODE_TYPES[d["type"]]
        self.rows = node_rows(d["type"])
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges); self.setZValue(1)
        self.links = []; self.in_socks = {}; self.out_socks = {}; self.row_widgets = {}; self.H = 60
        self._build(); self.setPos(d.get("x", 0), d.get("y", 0))
        self.setToolTip("%s  -  %s" % (self.spec["title"], self.spec.get("cat", "")))

    def boundingRect(self): return QRectF(-8, -8, self.W + 16, self.H + 16)

    # -- widgets of one parameter --
    def _edit(self, key, conv):
        return lambda v, key=key, conv=conv: self.sc.edit_param(self.nid, key, conv(v))

    def _make_widget(self, ps, cur):
        key, kind = ps[0], ps[2]
        lo = ps[4] if len(ps) > 4 and isinstance(ps[4], (int, float)) else -1e6
        hi = ps[5] if len(ps) > 5 and isinstance(ps[5], (int, float)) else 1e6
        if kind in ("float", "int"):
            try: cur = float(cur)
            except (TypeError, ValueError): cur = float(ps[3])
            w = NumberField(cur, lo, hi, _dec_for(lo, hi, kind), "", "", scrub=_scrub_for(lo, hi, kind)); w.setLight(); w.setFixedSize(84, 20)
            w.changed.connect(self._edit(key, (lambda v: int(round(v))) if kind == "int" else float)); return w
        if kind == "bool":
            w = Toggle("", bool(cur)); w.setLight(); w.toggled.connect(self._edit(key, bool)); return w
        if kind == "choice":
            w = ComboBox(); w.setLight(); w.setFixedHeight(20); w.setMinimumWidth(110)
            for val, lab in (ps[4] or []): w.addItem(lab, val)
            ix = w.findData(cur)
            if ix < 0: w.addItem("(%s)" % cur, cur); ix = w.count() - 1
            w.setCurrentIndex(ix); w.currentIndexChanged.connect(lambda _i, w=w, key=key: self.sc.edit_param(self.nid, key, w.currentData())); return w
        if kind == "color":
            w = QPushButton(""); w.setFixedSize(54, 18); w.setCursor(Qt.PointingHandCursor); self._paint_swatch(w, str(cur))
            w.clicked.connect(lambda _=False, w=w, key=key: self._pick_color(w, key)); return w
        w = QLineEdit(str(cur)); w.setFixedSize(110, 20); w.textChanged.connect(self._edit(key, str)); return w

    @staticmethod
    def _paint_swatch(btn, hexcol):
        col = hexcol if re.match(r"^#[0-9a-fA-F]{3,8}$", hexcol or "") else "#888888"
        btn.setStyleSheet("QPushButton{background:%s;border:1px solid rgba(0,0,0,90);border-radius:5px;padding:0px;}" % col)

    def _pick_color(self, btn, key):
        cur = (self.d.get("p") or {}).get(key) or "#ffffff"
        # the program's own colour window (with the eye-dropper), next to the mouse
        open_color_popup(btn, cur, lambda c: self._paint_swatch(btn, c), lambda c: (self._paint_swatch(btn, c), self.sc.edit_param(self.nid, key, c)), at_cursor=True)

    def _build(self):
        typ = self.d["type"]; p = self.d.get("p") or {}; ex = self.d.get("ex") or {}
        box = QWidget(); box.setAttribute(Qt.WA_TranslucentBackground); box.setStyleSheet(NODE_QSS)
        lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        for n, r in enumerate(self.rows):
            row = QWidget(); row.setFixedSize(self.W, self.ROW); h = QHBoxLayout(row); h.setContentsMargins(12, 2, 12, 2); h.setSpacing(6)
            lab = QLabel(r["label"])
            if r["out"] is not None:
                lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter); h.addStretch(); h.addWidget(lab)
            else:
                h.addWidget(lab); h.addStretch()
                if r["param"]:
                    ps = param_spec(typ, r["param"]); ws = []
                    if ps is not None:
                        w = self._make_widget(ps, p.get(r["param"], ps[3])); h.addWidget(w); ws.append(w)
                        if can_expose(typ, r["param"]):
                            b = QToolButton(); b.setCheckable(True); b.setFixedSize(20, 20); b.setFocusPolicy(Qt.NoFocus)
                            b.setIcon(svg_icon("keyframe", "#7b8394", UI["ui_accent2"])); b.setIconSize(QSize(14, 14))
                            b.setToolTip("Offer this parameter as a slider of the effect (inspector, keyframes)")
                            b.setChecked(r["param"] in ex)
                            b.toggled.connect(lambda on, key=r["param"]: self.sc.toggle_expose(self.nid, key, on)); h.addWidget(b); ws.append(b)
                    self.row_widgets[r["param"]] = ws
            lay.addWidget(row)
            y = self.HEAD + n * self.ROW + self.ROW / 2
            if r["out"] is not None:
                s = FxSocket(self, r["out"], True, r["kind"]); s.setPos(self.W, y); self.out_socks[r["out"]] = s
            if r["in"] is not None:
                s = FxSocket(self, r["in"], False, r["kind"]); s.setPos(0, y); self.in_socks[r["in"]] = s
        total = len(self.rows) * self.ROW; box.setFixedSize(self.W, max(total, 1)); self.box = box
        self.proxy = QGraphicsProxyWidget(self); self.proxy.setWidget(box); self.proxy.setPos(0, self.HEAD)
        self.H = self.HEAD + total + 8

    def refresh_inputs(self, linked):
        """A parameter that another block drives shows no field (like the inputs of the main node editor)."""
        for r in self.rows:
            if r["param"] and r["in"] is not None:
                for w in self.row_widgets.get(r["param"], []): w.setVisible(r["in"] not in linked)

    def paint(self, p, opt, w=None):
        p.setRenderHint(QPainter.Antialiasing); r = QRectF(0, 0, self.W, self.H); muted = bool(self.d.get("mute"))
        body = QPainterPath(); body.addRoundedRect(r, 10, 10)
        base = cat_color(self.spec.get("cat")); col = pastel(base, 0.58); bodyc = pastel(base, 0.80)
        if muted: col.setAlpha(110); bodyc.setAlpha(110)
        p.fillPath(body, bodyc); p.setPen(QPen(pastel(base, 0.2), 1.2)); p.setBrush(Qt.NoBrush); p.drawPath(body)
        p.save(); p.setClipPath(body); p.fillRect(QRectF(0, 0, self.W, self.HEAD), col); p.restore()
        p.setPen(NODE_INK); f = QFont(p.font()); f.setBold(True); f.setPointSize(max(8, f.pointSize())); p.setFont(f)
        p.drawText(QRectF(12, 0, self.W - 24, self.HEAD), Qt.AlignVCenter | Qt.AlignLeft, self.spec["title"] + ("  (muted)" if muted else ""))
        if self.isSelected(): p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(UI["ui_accent"]), 2)); p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for l in self.links: l.update_path()
        return super().itemChange(change, value)


# ── scene ─────────────────────────────────────────────────────────────────────
class FxScene(QGraphicsScene):
    def __init__(self, win):
        super().__init__(); self.win = win; self.doc = win.doc; self.items_by_id = {}; self.link_items = []; self._tmp = None; self._from = None

    # -- model -> items (always called from the event loop, never from inside an item's own event) --
    def rebuild(self, select=()):
        sel = set(select) if select else {nid for nid, it in self.items_by_id.items() if it.isSelected()}      # a new / pasted block becomes THE selection
        self.clear(); self.items_by_id = {}; self.link_items = []; self._tmp = None; self._from = None
        for d in self.doc.graph["nodes"]:
            it = FxNode(self, d); self.addItem(it); self.items_by_id[d["id"]] = it
        for rec in self.doc.graph["links"]:
            a, b = self.items_by_id.get(rec["from"]), self.items_by_id.get(rec["to"])
            if a is None or b is None or rec["fo"] not in a.out_socks or rec["ti"] not in b.in_socks: continue
            self._add_link_item(a.out_socks[rec["fo"]], b.in_socks[rec["ti"]], rec)
        for nid in sel:
            if nid in self.items_by_id: self.items_by_id[nid].setSelected(True)
        self._refresh_all()

    def _linked_inputs(self, node): return {r["ti"] for r in self.doc.graph["links"] if r["to"] == node.nid}
    def _refresh_all(self):
        for n in self.items_by_id.values(): n.refresh_inputs(self._linked_inputs(n))
    def _add_link_item(self, out_s, in_s, rec):
        li = FxLinkItem(out_s, in_s, rec); self.addItem(li); self.link_items.append(li); out_s.node.links.append(li); in_s.node.links.append(li); return li
    def _drop_link_item(self, li):
        for n in (li.a.node, li.b.node):
            if li in n.links: n.links.remove(li)
        self.removeItem(li)
        if li in self.link_items: self.link_items.remove(li)

    # -- editing (all through the document) --
    def edit_param(self, nid, key, value): self.win.edit_param(nid, key, value)
    def toggle_expose(self, nid, key, on): self.win.toggle_expose(nid, key, on)
    def selected_ids(self): return [it.nid for it in self.selectedItems() if isinstance(it, FxNode)]
    def selected_links(self): return [it for it in self.selectedItems() if isinstance(it, FxLinkItem) and it.rec]

    def commit_moves(self):
        """Nodes that were dragged: tell the document once, when the mouse is released (one undo step per drag)."""
        pos = {nid: (it.x(), it.y()) for nid, it in self.items_by_id.items()}
        if pos: self.win.move_nodes(pos)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e); self.commit_moves()

    # -- wires (the same way the main node editor does it) --
    def connect(self, out_s, in_s):
        ok, why = self.doc.add_link(out_s.node.nid, out_s.idx, in_s.node.nid, in_s.idx)
        if not ok: self.win.say(why, "warn")
        return ok

    def begin_link(self, sock):
        start = sock
        if not sock.is_out:
            rec = self.doc.link_into(sock.node.nid, sock.idx)
            if rec:                       # pick the wire up and re-route it: no rebuild now (this socket is being dragged)
                li = next((l for l in self.link_items if l.rec is rec or (l.rec and l.rec == rec)), None)
                start = self.items_by_id[rec["from"]].out_socks[rec["fo"]]
                self.win.quiet(lambda: self.doc.remove_link(rec["from"], rec["fo"], rec["to"], rec["ti"]))
                if li is not None: self._drop_link_item(li)
                self._refresh_all()
        self._from = start; self._tmp = FxLinkItem(start if start.is_out else None, None if start.is_out else start); self.addItem(self._tmp)
        self._tmp.end = start.scenePos(); self._tmp.update_path()

    def drag_link(self, pos):
        if self._tmp is not None: self._tmp.end = pos; self._tmp.update_path()

    def end_link(self, pos):
        if self._tmp is None: return
        src = self._from; self.removeItem(self._tmp); self._tmp = None; self._from = None
        cands = [i for i in self.items(QRectF(pos.x() - 12, pos.y() - 12, 24, 24)) if isinstance(i, FxSocket) and i.is_out != src.is_out and i.node is not src.node]
        tgt = next((i for i in cands if i.kind == src.kind), cands[0] if cands else None)
        if tgt is not None: self.connect(src, tgt) if src.is_out else self.connect(tgt, src)


# ── canvas ────────────────────────────────────────────────────────────────────
class FxView(QGraphicsView):
    def __init__(self, scene, win):
        super().__init__(scene); self.win = win; self._pan = None
        self.setRenderHint(QPainter.Antialiasing); self.setDragMode(QGraphicsView.RubberBandDrag); self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse); self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate); self.setFrameShape(QFrame.NoFrame); self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus); scene.setSceneRect(-6000, -6000, 12000, 12000); self.centerOn(0, 0)

    def focusNextPrevChild(self, nxt): return False             # Tab opens the block search instead of moving the focus

    def fit_all(self):
        nodes = [i for i in self.scene().items() if isinstance(i, FxNode)]
        self.resetTransform()
        if not nodes: self.centerOn(0, 0); return
        rect = QRectF()
        for n in nodes: rect = rect.united(n.sceneBoundingRect())
        self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)
        s = self.transform().m11()
        if s > 1.2: self.resetTransform(); self.scale(1.2, 1.2); self.centerOn(rect.center())

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(UI["nd_canvas"])); g = 24; col = QColor(UI["nd_grid"]); p.setPen(QPen(col, 1.5))
        x0 = int(math.floor(rect.left() / g)) * g; y0 = int(math.floor(rect.top() / g)) * g
        pts = [QPointF(x, y) for x in range(x0, int(rect.right()) + g, g) for y in range(y0, int(rect.bottom()) + g, g)]
        p.drawPoints(QPolygonF(pts))

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15; cur = self.transform().m11()
        if 0.25 <= cur * f <= 2.5: self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton: self._pan = e.position(); self.setCursor(Qt.ClosedHandCursor); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan; self._pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x())); self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y())); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton and self._pan is not None: self._pan = None; self.unsetCursor(); return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        node = self.itemAt(e.pos())
        while node is not None and not isinstance(node, (FxNode, FxLinkItem)): node = node.parentItem()
        if node is None and e.button() == Qt.LeftButton: self.win.open_search(self.mapToScene(e.pos())); return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.ControlModifier); shift = bool(e.modifiers() & Qt.ShiftModifier); k = e.key(); w = self.win
        if k in (Qt.Key_Delete, Qt.Key_Backspace): w.delete_selected(); return
        if ctrl and k == Qt.Key_D: w.duplicate_selected(); return
        if ctrl and k == Qt.Key_C: w.copy_selected(); return
        if ctrl and k == Qt.Key_X: w.cut_selected(); return
        if ctrl and k == Qt.Key_V: w.paste_clip(self.mapToScene(self.mapFromGlobal(QCursor.pos()))); return
        if ctrl and k == Qt.Key_A: w.select_all(); return
        if ctrl and k == Qt.Key_Z and not shift: w.undo(); return
        if ctrl and (k == Qt.Key_Y or (k == Qt.Key_Z and shift)): w.redo(); return
        if ctrl and k == Qt.Key_S: w.on_save(); return
        if k == Qt.Key_M and not ctrl: w.toggle_mute(); return
        if k == Qt.Key_F and not ctrl: self.fit_all(); return
        if k == Qt.Key_Tab: w.open_search(self.mapToScene(self.mapFromGlobal(QCursor.pos()))); return
        if k == Qt.Key_Space: w.toggle_play(); return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        pos = self.mapToScene(e.pos()); m = QMenu(self); w = self.win
        node = self.itemAt(e.pos())
        while node is not None and not isinstance(node, (FxNode, FxLinkItem)): node = node.parentItem()
        if isinstance(node, FxNode):
            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)
            m.addAction("Duplicate", w.duplicate_selected); m.addAction("Copy", w.copy_selected); m.addAction("Cut", w.cut_selected)
            m.addAction("Mute / unmute", w.toggle_mute); m.addSeparator(); m.addAction("Delete", w.delete_selected)
        elif isinstance(node, FxLinkItem):
            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)
            m.addAction("Delete connection", w.delete_selected)
        else:
            m.addAction("Search blocks...   (Tab)", lambda: w.open_search(pos)); m.addSeparator()
            for cat in CAT_ORDER:
                types = [t for t, sp in FX_NODE_TYPES.items() if sp.get("cat") == cat]
                if not types: continue
                sub = m.addMenu(cat)
                for typ in types: sub.addAction(FX_NODE_TYPES[typ]["title"], lambda typ=typ: w.add_node(typ, pos))
            m.addSeparator(); m.addAction("Paste", lambda: w.paste_clip(pos)); m.addAction("Arrange", w.arrange)
        m.exec(e.globalPos())

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith("minicut-fxnode:"): e.acceptProposedAction()
    def dragMoveEvent(self, e): e.acceptProposedAction()
    def dropEvent(self, e):
        t = e.mimeData().text()
        if t.startswith("minicut-fxnode:"): self.win.add_node(t.split(":", 1)[1], self.mapToScene(e.position().toPoint())); e.acceptProposedAction(); self.setFocus()


# ── block list ────────────────────────────────────────────────────────────────
class FxPaletteDelegate(QStyledItemDelegate):
    """Each block of the list is a pastel rounded tile in its category colour."""
    def paint(self, p, opt, idx):
        p.save(); p.setRenderHint(QPainter.Antialiasing); r = QRectF(opt.rect).adjusted(2, 2, -2, -2); col = QColor(idx.data(Qt.UserRole + 5) or "#888888")
        if opt.state & QStyle.State_MouseOver: col = col.lighter(108)
        p.setPen(QPen(NODE_INK, 2) if (opt.state & QStyle.State_Selected) else Qt.NoPen); p.setBrush(col); p.drawRoundedRect(r, 8, 8)
        f = QFont(p.font()); f.setBold(True); p.setFont(f); p.setPen(NODE_INK); p.drawText(r.adjusted(12, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, idx.data(Qt.DisplayRole)); p.restore()


class FxPalette(QListWidget):
    def __init__(self):
        super().__init__(); self.setMinimumWidth(180); self.setDragEnabled(True); self.setSpacing(3); self.setFocusPolicy(Qt.NoFocus)
        self.setItemDelegate(FxPaletteDelegate(self)); self.setMouseTracking(True); self.fill("")
    def fill(self, query):
        self.clear()
        for typ in search_nodes(query, 200):
            sp = FX_NODE_TYPES[typ]; it = QListWidgetItem(sp["title"]); it.setData(Qt.UserRole, typ); it.setToolTip(sp.get("cat", ""))
            it.setData(Qt.UserRole + 5, pastel(cat_color(sp.get("cat")), 0.58).name()); it.setSizeHint(QSize(0, 34)); self.addItem(it)
    def startDrag(self, actions):
        it = self.currentItem(); t = it.data(Qt.UserRole) if it else None
        if not t: return
        md = QMimeData(); md.setText("minicut-fxnode:" + t); dr = QDrag(self); dr.setMimeData(md)
        sp = FX_NODE_TYPES[t]; pm = QPixmap(150, 30); pm.fill(Qt.transparent); q = QPainter(pm); q.setRenderHint(QPainter.Antialiasing)
        q.setBrush(pastel(cat_color(sp.get("cat")), 0.58)); q.setPen(Qt.NoPen); q.drawRoundedRect(0, 0, 150, 30, 8, 8); q.setPen(NODE_INK); q.drawText(QRect(10, 0, 135, 30), Qt.AlignVCenter, sp["title"]); q.end()
        dr.setPixmap(pm); dr.setHotSpot(QPoint(20, 15)); dr.exec(Qt.CopyAction)


class _SearchEdit(QLineEdit):
    nav = Signal(int)
    chosen = Signal()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Down: self.nav.emit(1); return
        if e.key() == Qt.Key_Up: self.nav.emit(-1); return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter): self.chosen.emit(); return
        super().keyPressEvent(e)


class FxSearchPopup(QFrame):
    """Tab (or a double click on empty canvas): type a few letters of a block's name and press Enter."""
    picked = Signal(str)
    def __init__(self, owner):
        super().__init__(owner.window(), Qt.Popup | Qt.FramelessWindowHint); self.setAttribute(Qt.WA_DeleteOnClose); self.setObjectName("Panel"); self.setFixedWidth(280)
        v = QVBoxLayout(self); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        self.edit = _SearchEdit(); self.edit.setPlaceholderText("Search blocks (English or Thai)..."); v.addWidget(self.edit)
        self.list = QListWidget(); self.list.setItemDelegate(FxPaletteDelegate(self.list)); self.list.setSpacing(2); self.list.setFocusPolicy(Qt.NoFocus); self.list.setFixedHeight(260); v.addWidget(self.list)
        self.edit.textChanged.connect(self._fill); self.edit.nav.connect(self._nav); self.edit.chosen.connect(self._accept); self.list.itemClicked.connect(lambda it: self._accept(it))
        self._fill("")
    def _fill(self, q):
        self.list.clear()
        for typ in search_nodes(q, 40):
            sp = FX_NODE_TYPES[typ]; it = QListWidgetItem(sp["title"]); it.setData(Qt.UserRole, typ); it.setData(Qt.UserRole + 5, pastel(cat_color(sp.get("cat")), 0.58).name()); it.setSizeHint(QSize(0, 30)); self.list.addItem(it)
        if self.list.count(): self.list.setCurrentRow(0)
    def _nav(self, d):
        n = self.list.count()
        if n: self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + d)))
    def _accept(self, it=None):
        it = it or self.list.currentItem()
        if it is not None: self.picked.emit(it.data(Qt.UserRole)); self.close()
    def popup_at(self, gpos):
        self.move(gpos); self.show(); self.edit.setFocus()


# ── preview ───────────────────────────────────────────────────────────────────
class FxPreviewWidget(QWidget):
    """The picture with the effect on it: zoom (wheel), pan (drag), double-click to fit; a chess pattern shows transparency."""
    def __init__(self):
        super().__init__(); self.img = None; self.zoom = None; self.pan = QPointF(0, 0); self._drag = None; self.note = ""
        self.setMinimumSize(200, 120); self.setCursor(Qt.OpenHandCursor)
        pm = QPixmap(16, 16); pm.fill(QColor("#3a3a40")); q = QPainter(pm); q.fillRect(0, 0, 8, 8, QColor("#4a4a52")); q.fillRect(8, 8, 8, 8, QColor("#4a4a52")); q.end(); self._chess = pm
    def set_img(self, img): self.img = img; self.update()
    def set_note(self, t): self.note = t; self.update()
    def fit_scale(self):
        if self.img is None or self.img.isNull(): return 1.0
        return min(self.width() / max(1, self.img.width()), self.height() / max(1, self.img.height()))
    def cur_scale(self): return self.fit_scale() if self.zoom is None else self.zoom
    def set_zoom(self, z): self.zoom = None if z is None else max(0.1, min(8.0, z)); self.pan = QPointF(0, 0); self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), QColor(UI["vp_bg"]))
        if self.img is None or self.img.isNull():
            p.setPen(QColor(UI["ui_text_dim"])); p.drawText(self.rect(), Qt.AlignCenter, self.note or "No preview yet"); return
        s = self.cur_scale(); w, h = self.img.width() * s, self.img.height() * s
        r = QRectF((self.width() - w) / 2 + self.pan.x(), (self.height() - h) / 2 + self.pan.y(), w, h)
        p.drawTiledPixmap(r.toRect(), self._chess); p.setRenderHint(QPainter.SmoothPixmapTransform, True); p.drawImage(r, self.img)
        if self.note: p.setPen(QColor("#ff9b9b")); p.drawText(self.rect().adjusted(8, 0, -8, -6), Qt.AlignBottom | Qt.AlignLeft, self.note)
    def wheelEvent(self, e): self.set_zoom(self.cur_scale() * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15))
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag = e.position(); self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self, e):
        if self._drag is not None: d = e.position() - self._drag; self._drag = e.position(); self.pan = self.pan + d; self.update()
    def mouseReleaseEvent(self, e): self._drag = None; self.setCursor(Qt.OpenHandCursor)
    def mouseDoubleClickEvent(self, e): self.set_zoom(None)


class FxSliders(QScrollArea):
    """The sliders the effect will have in the inspector (what was exposed, and the Parameter blocks). Moving one here
    changes the preview only; the node's own value is the effect's starting value."""
    def __init__(self, win):
        super().__init__(); self.win = win; self.setWidgetResizable(True); self._sig = None; self._w = {}
        self.body = QWidget(); self.setWidget(self.body); self.lay = QVBoxLayout(self.body); self.lay.setContentsMargins(4, 4, 4, 4); self.lay.setSpacing(4)

    def set_specs(self, specs, labels, values):
        sig = json.dumps([(s[0], s[1], s[2], s[4], s[5]) for s in specs], default=str)
        if sig != self._sig:
            self._sig = sig; self._rebuild(specs, labels, values)
        else: self.set_values(values)

    def _rebuild(self, specs, labels, values):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget() is not None: it.widget().setParent(None); it.widget().deleteLater()
        self._w = {}
        if not specs:
            t = QLabel("No sliders yet. Press the key button next to a parameter on a block (or add a Parameter block) to offer it here and in the inspector.")
            t.setWordWrap(True); t.setObjectName("Dim"); self.lay.addWidget(t)
        for key, label, kind, dflt, lo, hi in specs:
            row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            if key in labels:                                  # an exposed parameter: its slider name can be changed here
                nid, pk = labels[key]; ed = QLineEdit(label); ed.setFixedWidth(130); ed.setToolTip("Name of this slider in the inspector")
                ed.editingFinished.connect(lambda ed=ed, nid=nid, pk=pk: self.win.rename_expose(nid, pk, ed.text())); h.addWidget(ed)
            else:
                lb = QLabel(label); lb.setFixedWidth(130); h.addWidget(lb)
            cur = values.get(key, dflt)
            if kind in ("float", "int"):
                w = NumberField(float(cur), lo, hi, _dec_for(lo, hi, kind), "", "", scrub=_scrub_for(lo, hi, kind)); w.changed.connect(lambda v, key=key, kind=kind: self.win.slider_changed(key, int(round(v)) if kind == "int" else float(v)))
            elif kind == "bool":
                w = Toggle("", bool(cur)); w.toggled.connect(lambda v, key=key: self.win.slider_changed(key, bool(v)))
            elif kind == "choice":
                w = ComboBox()
                for val, lab in lo: w.addItem(lab, val)
                ix = w.findData(cur); w.setCurrentIndex(max(0, ix)); w.currentIndexChanged.connect(lambda _i, w=w, key=key: self.win.slider_changed(key, w.currentData()))
            else:
                w = QPushButton(""); w.setFixedSize(60, 22); FxNode._paint_swatch(w, str(cur))
                w.clicked.connect(lambda _=False, w=w, key=key: self._pick(w, key))
            h.addWidget(w, 1); self._w[key] = w; self.lay.addWidget(row)
        self.lay.addStretch()

    def _pick(self, btn, key):
        open_color_popup(btn, self.win.engine.values.get(key, "#ffffff"), lambda c: FxNode._paint_swatch(btn, c),
                         lambda c: (FxNode._paint_swatch(btn, c), self.win.slider_changed(key, c)), at_cursor=True)

    def set_values(self, values):
        for key, w in self._w.items():
            if key not in values: continue
            v = values[key]
            try:
                if isinstance(w, NumberField): w.setValue(float(v))
                elif isinstance(w, Toggle): w.setChecked(bool(v))
                elif isinstance(w, ComboBox):
                    ix = w.findData(v)
                    if ix >= 0: w.blockSignals(True); w.setCurrentIndex(ix); w.blockSignals(False)
                elif isinstance(w, QPushButton): FxNode._paint_swatch(w, str(v))
            except Exception: pass


# ── the window ────────────────────────────────────────────────────────────────
class FxNodeEditor(QWidget):
    """The effect editor: block list | canvas | live preview and sliders."""
    closed = Signal()

    def __init__(self, app, effect_id: str | None = None):
        super().__init__()
        self.app = app; self._effect_id = effect_id; self._allow_close = False
        self.doc = FxDoc(); self.doc.on_change = self._doc_changed
        self._quiet = 0; self._rebuild_pending = False; self._select_after = []
        self._values_user = {}; self._source = None; self._playing = True; self._t0 = time.monotonic(); self._t_pause = 0.0
        self._frame_dirty = True; self._syncing = False
        try: ref_w = float(getattr(getattr(app, "proj", None), "w", 1920) or 1920)
        except Exception: ref_w = 1920.0
        self.engine = FxPreview(ref_width=ref_w)

        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 10); root.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(6)
        top.addWidget(tool("", "Back to the editor", self.on_back, icon="angle_left", isize=24))
        t = QLabel("Effect editor"); t.setObjectName("Logo"); top.addWidget(t)
        self.name_edit = QLineEdit("Untitled Effect"); self.name_edit.setFixedWidth(210); self.name_edit.setToolTip("Name of the effect")
        self.cat_edit = QLineEdit("Custom"); self.cat_edit.setFixedWidth(110); self.cat_edit.setPlaceholderText("Category"); self.cat_edit.setToolTip("Category in the effects list")
        self.desc_edit = QLineEdit(); self.desc_edit.setFixedWidth(220); self.desc_edit.setPlaceholderText("Description (optional)")
        for w in (self.name_edit, self.cat_edit, self.desc_edit): top.addWidget(w)
        top.addStretch()
        self.status_lbl = QLabel(""); self.status_lbl.setObjectName("Dim"); top.addWidget(self.status_lbl)
        self.btn_undo = tool("", "Undo (Ctrl+Z)", self.undo, icon="undo", isize=20); self.btn_redo = tool("", "Redo (Ctrl+Y)", self.redo, icon="redo", isize=20)
        top.addWidget(self.btn_undo); top.addWidget(self.btn_redo)
        for ic, tip, cb in (("zoom_fit", "Fit all blocks (F)", lambda: self.view.fit_all()), ("nodes", "Arrange the blocks left to right", self.arrange),
                            ("mute", "Mute / unmute selected (M)", self.toggle_mute), ("duplicate", "Duplicate (Ctrl+D)", self.duplicate_selected),
                            ("copy", "Copy (Ctrl+C)", self.copy_selected), ("paste", "Paste (Ctrl+V)", lambda: self.paste_clip(None)), ("delete", "Delete (Del)", self.delete_selected)):
            top.addWidget(tool("", tip, cb, icon=ic, isize=20))
        top.addWidget(tool("", FX_HELP, None, icon="help", isize=20))
        save = QPushButton("Save"); save.setObjectName("Accent"); save.setToolTip("Save the effect (Ctrl+S)"); save.clicked.connect(lambda *_: self.on_save()); top.addWidget(save)
        root.addLayout(top)

        self.scene = FxScene(self); self.view = FxView(self.scene, self)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(6)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search blocks..."); self.search.textChanged.connect(self._filter_palette); ll.addWidget(self.search)
        self.palette = FxPalette(); self.palette.itemDoubleClicked.connect(self._palette_add); ll.addWidget(self.palette, 1)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
        self.preview = FxPreviewWidget(); rl.addWidget(self.preview, 1)
        tr = QHBoxLayout(); tr.setSpacing(4)
        self.play_b = tool("", "Play / Pause (Space)", self.toggle_play, icon="play", isize=20); set_play_icon(self.play_b, True)
        tr.addWidget(self.play_b)
        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, int(LOOP_SECONDS * 100)); self.seek.setFocusPolicy(Qt.NoFocus); self.seek.valueChanged.connect(self._on_seek); tr.addWidget(self.seek, 1)
        self.time_lbl = QLabel("0.00 s"); self.time_lbl.setObjectName("Dim"); self.time_lbl.setFixedWidth(52); tr.addWidget(self.time_lbl)
        for lab, z in (("Fit", None), ("100%", 1.0)):
            zb = QPushButton(lab); zb.setToolTip("Preview zoom"); zb.clicked.connect(lambda _=False, z=z: self.preview.set_zoom(z)); tr.addWidget(zb)
        rl.addLayout(tr)
        sr = QHBoxLayout(); sr.setSpacing(6)
        sl = QLabel("Picture"); sl.setObjectName("PanelTitle"); sr.addWidget(sl)
        self.src_btn = QPushButton("Choose..."); self.src_btn.setToolTip("The picture the preview uses (a media of the project, a file, or a test picture)"); self.src_btn.clicked.connect(lambda *_: self._source_menu()); sr.addWidget(self.src_btn, 1)
        rl.addLayout(sr)
        self.info_lbl = QLabel(""); self.info_lbl.setObjectName("Dim"); self.info_lbl.setWordWrap(True); rl.addWidget(self.info_lbl)
        st = QLabel("Sliders of the effect"); st.setObjectName("PanelTitle"); rl.addWidget(st)
        self.sliders = FxSliders(self); self.sliders.setMinimumHeight(110); self.sliders.setMaximumHeight(230); rl.addWidget(self.sliders)

        body = QSplitter(Qt.Horizontal); body.setHandleWidth(8); body.setChildrenCollapsible(False)
        body.addWidget(left); body.addWidget(self.view); body.addWidget(right)
        body.setSizes([210, 700, 400]); body.setStretchFactor(0, 0); body.setStretchFactor(1, 1); body.setStretchFactor(2, 0)
        root.addWidget(body, 1)

        self._compile_timer = QTimer(self); self._compile_timer.setSingleShot(True); self._compile_timer.setInterval(120); self._compile_timer.timeout.connect(self._compile_now)
        self.timer = QTimer(self); self.timer.setInterval(33); self.timer.timeout.connect(self._tick)

        if effect_id: self._load_existing(effect_id)
        self._choose_default_source()
        self.scene.rebuild(); self._touch(); self._schedule_compile()
        QTimer.singleShot(60, self.view.fit_all)

    # ── document <-> window ──
    def _doc_changed(self):
        self._touch(); self._schedule_compile()
        if self._quiet: return
        self.schedule_rebuild()

    def quiet(self, fn):
        """Run fn (a document edit) without redrawing the canvas afterwards (the items are being used right now)."""
        self._quiet += 1
        try: return fn()
        finally: self._quiet -= 1

    def schedule_rebuild(self):
        if not self._rebuild_pending: self._rebuild_pending = True; QTimer.singleShot(0, self._do_rebuild)

    def _do_rebuild(self):
        self._rebuild_pending = False; sel, self._select_after = self._select_after, []
        self.scene.rebuild(sel)

    def _touch(self):
        self.btn_undo.setEnabled(self.doc.can_undo()); self.btn_redo.setEnabled(self.doc.can_redo())

    def say(self, text, kind="ok"):
        col = {"ok": UI["ui_accent"], "warn": "#f0b429", "err": "#ff7b7b"}.get(kind, UI["ui_accent"])
        self.status_lbl.setText(text[:120]); self.status_lbl.setStyleSheet("color:%s;" % col)
        if kind != "ok" and hasattr(self.app, "toast"):
            try: self.app.toast.show_msg(text)
            except Exception: pass

    # ── editing actions ──
    def edit_param(self, nid, key, value):
        self.quiet(lambda: self.doc.set_param(nid, key, value))
        n = self.doc.node(nid)
        if n is not None and key in (n.get("ex") or {}): self._values_user.pop(exposed_key(nid, key), None)      # the node's own value is the slider's start value

    def toggle_expose(self, nid, key, on):
        n = self.doc.node(nid)
        if n is None: return
        spec = FX_NODE_TYPES[n["type"]]; ps = param_spec(n["type"], key)
        label = "%s %s" % (spec["title"], ps[1]) if ps else key
        self.doc.set_expose(nid, key, bool(on), label if on else None)

    def rename_expose(self, nid, key, text):
        n = self.doc.node(nid)
        if n is None or not text.strip() or (n.get("ex") or {}).get(key) == text.strip(): return
        self.quiet(lambda: self.doc.set_expose(nid, key, True, text.strip()))

    def move_nodes(self, pos): self.quiet(lambda: self.doc.move_nodes(pos))

    def add_node(self, typ, pos):
        nid = self.doc.add_node(typ, pos.x() - 120, pos.y() - 14)
        if nid: self._select_after = [nid]
        return nid

    def _palette_add(self, it):
        typ = it.data(Qt.UserRole)
        if typ: self.add_node(typ, self.view.mapToScene(self.view.viewport().rect().center()))

    def _filter_palette(self, q): self.palette.fill(q.strip())

    def open_search(self, scene_pos):
        pop = FxSearchPopup(self); pos = QPointF(scene_pos)
        pop.picked.connect(lambda typ, pos=pos: self.add_node(typ, pos))
        pop.popup_at(QCursor.pos())

    def delete_selected(self):
        links = self.scene.selected_links(); ids = self.scene.selected_ids()
        for li in links: self.doc.remove_link(li.rec["from"], li.rec["fo"], li.rec["to"], li.rec["ti"])
        if ids and not self.doc.remove_nodes(ids) and not links: self.say("The Output block stays: an effect always needs one", "warn")

    def duplicate_selected(self):
        new = self.doc.duplicate(self.scene.selected_ids())
        if new: self._select_after = new

    def copy_selected(self):
        ids = self.scene.selected_ids()
        if ids: QApplication.clipboard().setText(self.doc.copy_nodes(ids)); self.say("Copied %d block(s)" % len(ids))

    def cut_selected(self): self.copy_selected(); self.delete_selected()

    def paste_clip(self, pos):
        text = QApplication.clipboard().text(); clip = self.doc.parse_clip(text)
        if clip is None: self.say("Nothing to paste (copy some blocks first)", "warn"); return
        xs = [n.get("x", 0) for n in clip["nodes"] if isinstance(n, dict)]; ys = [n.get("y", 0) for n in clip["nodes"] if isinstance(n, dict)]
        if pos is None: pos = self.view.mapToScene(self.view.viewport().rect().center())
        dx = (pos.x() - min(xs)) if xs else 40; dy = (pos.y() - min(ys)) if ys else 40
        new = self.doc.paste(text, dx, dy)
        if new: self._select_after = new

    def select_all(self):
        for it in self.scene.items_by_id.values(): it.setSelected(True)

    def toggle_mute(self): self.doc.set_mute(self.scene.selected_ids())
    def arrange(self):
        if self.doc.arrange(): QTimer.singleShot(30, self.view.fit_all)
    def undo(self):
        if not self.doc.undo(): self.say("Nothing to undo", "warn")
    def redo(self):
        if not self.doc.redo(): self.say("Nothing to redo", "warn")

    # ── preview ──
    def _schedule_compile(self):
        if not self._compile_timer.isActive(): self._compile_timer.start()

    def _compile_now(self):
        ok = self.engine.set_graph(self.doc.graph)
        specs = self.doc.param_specs()
        self.engine.values = {s[0]: self._values_user.get(s[0], s[3]) for s in specs}
        labels = {}
        for n in self.doc.graph["nodes"]:
            for pk in (n.get("ex") or {}): labels[exposed_key(n["id"], pk)] = (n["id"], pk)
        self.sliders.set_specs(specs, labels, self.engine.values)
        if not ok: self.say(self.engine.error or "error", "err"); self.preview.set_note(self.engine.error or ""); return
        self.preview.set_note("")
        warn = self.engine.warnings
        self.info_lbl.setText(("  ".join(warn)) if warn else ""); self.info_lbl.setStyleSheet("color:#f0b429;" if warn else "")
        self.say("Ready" + ("  (warning: %s)" % warn[0] if warn else ""), "warn" if warn else "ok")
        self._frame_dirty = True

    def slider_changed(self, key, value):
        self._values_user[key] = value; self.engine.set_value(key, value); self._frame_dirty = True

    def toggle_play(self):
        self._playing = not self._playing
        if self._playing: self._t0 = time.monotonic() - self._t_pause
        else: self._t_pause = (time.monotonic() - self._t0) % LOOP_SECONDS
        set_play_icon(self.play_b, self._playing)

    def _on_seek(self, v):
        if self._syncing: return
        self._t_pause = v / 100.0; self._t0 = time.monotonic() - self._t_pause; self._frame_dirty = True

    def _tick(self):
        if not self.isVisible() or self.engine.fn is None or self.engine.work is None: return
        moving = self._playing and self.engine.animated
        if not (moving or self._frame_dirty): return
        t = ((time.monotonic() - self._t0) if self._playing else self._t_pause) % LOOP_SECONDS
        out = self.engine.render(t)
        self._frame_dirty = False
        if out is not None:
            self.preview.set_img(np_to_qimage(out))
            self.info_lbl.setText(("%d x %d  -  %.0f ms" % (out.shape[1], out.shape[0], self.engine.last_ms)) + (("   " + "  ".join(self.engine.warnings)) if self.engine.warnings else ""))
        elif self.engine.error: self.preview.set_note(self.engine.error)
        if self._playing and self.engine.animated:
            self._syncing = True; self.seek.setValue(int(t * 100)); self._syncing = False
        self.time_lbl.setText("%.2f s" % t)

    def showEvent(self, e): super().showEvent(e); self.timer.start()
    def hideEvent(self, e): super().hideEvent(e); self.timer.stop()

    def _choose_default_source(self):
        spec = None
        try:
            c = self.app.sel_clip() if hasattr(self.app, "sel_clip") else None
            if c and c.get("path") and c.get("kind") in ("video", "image", "gif"): spec = self._clip_spec(c)
        except Exception: spec = None
        if spec is None or self.set_source(spec, quiet=True) is False: self.set_source({"type": "sample", "name": SAMPLE_NAMES[1]}, quiet=True)

    def _clip_spec(self, c):
        t = 0.0
        try:
            if c.get("kind") == "video": t = max(0.0, min(float(c.get("dur", 0.0)), float(self.app.t) - float(c.get("start", 0.0))))
        except Exception: t = 0.0
        return {"type": "clip", "path": c["path"], "kind": c["kind"], "t": t, "name": c.get("name", "clip")}

    def set_source(self, spec, quiet=False):
        img = load_picture(spec)
        if img is None:
            if not quiet: self.say("That picture could not be opened", "err")
            return False
        self.engine.set_source(img); self._source = spec; self._frame_dirty = True
        name = spec.get("name") or os.path.basename(spec.get("path", "")) or "picture"
        self.src_btn.setText(("Test picture: " if spec["type"] == "sample" else "") + name); self.preview.set_zoom(None); return True

    def _source_menu(self):
        m = QMenu(self); sub = m.addMenu("Test pictures")
        for n in SAMPLE_NAMES: sub.addAction(n, lambda n=n: self.set_source({"type": "sample", "name": n}))
        try: media = [c for c in (self.app.proj.clips if self.app.proj else []) if c.get("path") and c.get("kind") in ("video", "image", "gif")]
        except Exception: media = []
        sub2 = m.addMenu("Media of this project")
        if media:
            for c in media[:60]: sub2.addAction("%s  (%s)" % (c.get("name", "clip"), c.get("kind")), lambda c=c: self.set_source(self._clip_spec(c)))
        else: sub2.setEnabled(False)
        m.addSeparator(); m.addAction("Open a picture file...", self._open_file)
        m.exec(QCursor.pos())

    def _open_file(self):
        path, _f = QFileDialog.getOpenFileName(self, "Choose a picture", "", "Pictures (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All files (*)")
        if path: self.set_source({"type": "file", "path": path, "name": os.path.basename(path)})

    # ── load / save ──
    def _load_existing(self, eid):
        path = _mcfx_path(eid)
        if not os.path.exists(path): return
        try:
            with open(path, encoding="utf-8") as f: data = json.load(f)
            if not isinstance(data, dict): raise ValueError("not an effect file")
        except Exception as ex:
            self.say("Could not read this effect (%s) - starting a new one" % str(ex)[:60], "err"); self._effect_id = None; return     # never save over the unreadable file
        meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
        self.name_edit.setText(meta.get("name", "")); self.cat_edit.setText(meta.get("category", "Custom")); self.desc_edit.setText(meta.get("description", ""))
        self._effect_id = meta.get("id", eid); self.doc.load(data.get("graph", {}))

    def _collect_meta(self):
        name = self.name_edit.text().strip() or "Untitled"; eid = self._effect_id
        if not eid:                                                   # a NEW effect: an id that no other effect uses
            base = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")[:20]
            if not re.search(r"[a-z0-9]", base): base = "fx_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]     # e.g. Thai names
            eid = base; n = 2
            while os.path.exists(_mcfx_path(eid)): eid = "%s_%d" % (base, n); n += 1
        return {"id": eid, "name": name, "category": self.cat_edit.text().strip() or "Custom", "description": self.desc_edit.text().strip(), "author": ""}

    def on_save(self):
        err, warns = self.doc.validate()
        if err: self.say(err, "err"); return False
        try:
            specs = self.doc.param_specs(); eid = save_effect(self._collect_meta(), specs, json.loads(json.dumps(self.doc.graph)))
            self._effect_id = eid; self.doc.mark_saved(); reload_custom_fx()
            self.say("Saved as custom:%s" % eid + (("   (warning: %s)" % warns[0]) if warns else ""), "warn" if warns else "ok")
            if hasattr(self.app, "on_changed"): self.app.on_changed()
            return True
        except Exception as ex:
            self.say(str(ex).splitlines()[0][:110] if str(ex) else "could not save", "err"); return False

    def _confirm_leave(self) -> bool:
        if not self.doc.is_dirty(): return True
        r = QMessageBox.question(self, "Unsaved changes", "Save before leaving?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel: return False
        if r == QMessageBox.Save and not self.on_save(): return False
        return True

    def on_back(self):
        if self._confirm_leave(): self._allow_close = True; self.closed.emit()

    def closeEvent(self, e):
        if self._allow_close or self._confirm_leave(): self.timer.stop(); e.accept()
        else: e.ignore()

    def keyPressEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and e.key() == Qt.Key_S: self.on_save(); return
        super().keyPressEvent(e)

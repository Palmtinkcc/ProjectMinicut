"""Node page: a simple, Scratch-like node editor. Pick a media (clip) on the left to work on its nodes only;
the preview on the right can be zoomed, panned and expanded."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.theme import *
from ..shared.core import *
from ..shared.widgets import *
from ..render.nodegraph import *


NODE_HELP = ("Drag a block from the list (or double-click it) into the canvas.\n"
             "Drag from a round socket to another socket to connect.\n\n"
             "Choose a media on the left to edit only the nodes for that media. Nodes that work on all media stay visible.\n\n"
             "Mouse: drag empty space = box select · middle button or Space = pan · wheel = zoom · right click = menu.\n"
             "Keys: Del delete · Ctrl+D duplicate · M mute · Ctrl+Z / Ctrl+Y undo / redo.")
KIND_NAMES = {"video": "Video", "image": "Image", "gif": "GIF", "text": "Text", "audio": "Audio", "compound": "Compound"}


def node_choices(app, opts):
    P = app.proj
    if isinstance(opts, (list, tuple)): return list(opts)
    clips = [(c["id"], "%s" % c.get("name", "clip")) for c in (P.clips if P else [])]
    if opts == "clips@": return [("@target", "Target clip")] + clips
    if opts == "clips*": return [("*", "All clips")] + clips
    if opts == "props": return [(k, v[0]) for k, v in OUT_PROPS.items()]
    if opts == "fxparams": return [("%s:%s" % (t, key), "%s · %s" % (sp["title"], label)) for t, sp in FX.items() for key, label, kind, *_ in sp["params"] if kind in ("float", "int")]
    if opts == "audiosrc":
        trk = [("track:" + t["id"], "Track: " + t["name"]) for t in (P.tracks if P else [])]
        return [("*", "All audio"), ("@target", "Target clip")] + trk + [("clip:" + i, "Clip: " + n) for i, n in clips]
    return []


class NodeSocket(QGraphicsEllipseItem):
    R = 6
    def __init__(self, node, idx, is_out):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R, node)
        self.node, self.idx, self.is_out = node, idx, is_out
        self.setBrush(QColor("#e8efff")); self.setPen(QPen(QColor(UI["ui_panel"]), 2)); self.setZValue(3)
        self.setCursor(Qt.CrossCursor); self.setAcceptHoverEvents(True)
    def hoverEnterEvent(self, e): self.setBrush(QColor(UI["ui_accent"]))
    def hoverLeaveEvent(self, e): self.setBrush(QColor("#e8efff"))
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.scene().begin_link(self); e.accept()
        else: e.ignore()
    def mouseMoveEvent(self, e): self.scene().drag_link(e.scenePos())
    def mouseReleaseEvent(self, e): self.scene().end_link(e.scenePos())


class LinkItem(QGraphicsPathItem):
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
        p.setPen(QPen(QColor(UI["ui_accent"] if sel else "#7d8fb3"), 3 if sel else 2.2)); p.setBrush(Qt.NoBrush); p.drawPath(self.path())


class NodeItem(QGraphicsItem):
    W, HEAD, ROW = 220, 28, 26
    def __init__(self, scene, d):
        super().__init__(); self.sc = scene; self.d = d; self.spec = NODE_TYPES[d["type"]]
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges); self.setZValue(1)
        self.links = []; self.in_socks = []; self.out_socks = []; self.in_spins = []; self.readouts = []; self.H = 60
        self._build(); self.setPos(d.get("x", 0), d.get("y", 0))
    def boundingRect(self): return QRectF(-8, -8, self.W + 16, self.H + 16)
    def _spin(self, v, cb):
        s = QDoubleSpinBox(); s.setObjectName("PropSpin"); s.setRange(-1e6, 1e6); s.setDecimals(2); s.setSingleStep(0.1); s.setKeyboardTracking(False)
        s.setValue(float(v)); s.setFixedSize(72, 20); s.setAlignment(Qt.AlignRight); s.valueChanged.connect(cb); return s
    def _set(self, k, v):
        self.sc.begin_edit(False); self.d["p"][k] = v; self.sc.touched()
    def _build(self):
        sp = self.spec; ins, outs = sp["ins"], sp["outs"]; sink = sp["sink"] is not None; rows = max(len(ins), len(outs))
        box = QWidget(); box.setAttribute(Qt.WA_TranslucentBackground); box.setStyleSheet("QLabel{background:transparent;}")
        lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        for i in range(rows):
            r = QWidget(); r.setFixedSize(self.W, self.ROW); h = QHBoxLayout(r); h.setContentsMargins(12, 2, 12, 2); h.setSpacing(6)
            if i < len(ins):
                h.addWidget(QLabel(ins[i][0]))
                if not sink:
                    k = "i%d" % i; s = self._spin(self.d["p"].get(k, ins[i][1]), lambda v, k=k: self._set(k, v)); h.addWidget(s); self.in_spins.append(s)
                else: self.in_spins.append(None)
            h.addStretch()
            if i < len(outs):
                ro = QLabel(outs[i]); ro.setAlignment(Qt.AlignRight | Qt.AlignVCenter); h.addWidget(ro); self.readouts.append(ro)
            lay.addWidget(r)
        for key, label, kind, dflt, opts in sp["params"]:
            r = QWidget(); r.setFixedSize(self.W, self.ROW); h = QHBoxLayout(r); h.setContentsMargins(12, 2, 12, 2); h.setSpacing(6)
            h.addWidget(QLabel(label)); cur = self.d["p"].get(key, dflt)
            if kind == "choice":
                w = QComboBox(); w.setFixedHeight(20)
                for val, lab in node_choices(self.sc.app, opts): w.addItem(lab, val)
                ix = w.findData(cur)
                if ix < 0: w.addItem("(missing)", cur); ix = w.count() - 1
                w.setCurrentIndex(ix); w.currentIndexChanged.connect(lambda _, w=w, key=key: self._set(key, w.currentData()))
                h.addWidget(w, 1)
            elif kind == "bool":
                w = QCheckBox(); w.setChecked(bool(cur)); w.toggled.connect(lambda v, key=key: self._set(key, bool(v))); h.addStretch(); h.addWidget(w)
            else:
                w = self._spin(cur, lambda v, key=key: self._set(key, v)); h.addStretch(); h.addWidget(w)
            lay.addWidget(r)
        total = (rows + len(sp["params"])) * self.ROW; box.setFixedSize(self.W, max(total, 1)); self.box = box
        self.proxy = QGraphicsProxyWidget(self); self.proxy.setWidget(box); self.proxy.setPos(0, self.HEAD)
        self.H = self.HEAD + total + 8
        for i in range(len(ins)):
            s = NodeSocket(self, i, False); s.setPos(0, self.HEAD + self.ROW * i + self.ROW / 2); self.in_socks.append(s)
        for j in range(len(outs)):
            s = NodeSocket(self, j, True); s.setPos(self.W, self.HEAD + self.ROW * j + self.ROW / 2); self.out_socks.append(s)
    def refresh_inputs(self, linked):
        for i, s in enumerate(self.in_spins):
            if s is not None: s.setVisible(i not in linked)
    def paint(self, p, opt, w=None):
        p.setRenderHint(QPainter.Antialiasing); r = QRectF(0, 0, self.W, self.H); muted = bool(self.d["p"].get("mute"))
        body = QPainterPath(); body.addRoundedRect(r, 10, 10)
        p.fillPath(body, QColor(UI["ui_panel"]))
        col = QColor(NODE_CATS.get(self.spec["cat"], "#555"))
        if muted: col.setAlpha(80)
        p.save(); p.setClipPath(body); p.fillRect(QRectF(0, 0, self.W, self.HEAD), col); p.restore()
        p.setPen(QColor("#ffffff") if not muted else QColor(255, 255, 255, 130)); f = QFont(p.font()); f.setBold(True); f.setPointSize(max(8, f.pointSize())); p.setFont(f)
        p.drawText(QRectF(12, 0, self.W - 24, self.HEAD), Qt.AlignVCenter | Qt.AlignLeft, self.spec["title"] + ("  (muted)" if muted else ""))
        if self.isSelected(): p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(UI["ui_accent"]), 2)); p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            p = self.pos(); self.d["x"], self.d["y"] = round(p.x(), 1), round(p.y(), 1)
            for l in self.links: l.update_path()
        return super().itemChange(change, value)


class NodeScene(QGraphicsScene):
    changed = Signal()
    def __init__(self, app):
        super().__init__(); self.app = app; self.graph = default_graph(); self.items_by_id = {}; self.link_items = []
        self._tmp = None; self._from = None; self.on_edit = None; self.loading = False; self.filter_clip = None
    # ---- model <-> items ----
    def load(self, graph):
        self.loading = True; self.clear(); self.items_by_id = {}; self.link_items = []; self._tmp = None; self._from = None
        self.graph = graph; graph.setdefault("nodes", []); graph.setdefault("links", []); graph.setdefault("on", True)
        for d in list(graph["nodes"]):
            if d.get("type") in NODE_TYPES:
                d.setdefault("p", {}); self.items_by_id[d["id"]] = NodeItem(self, d); self.addItem(self.items_by_id[d["id"]])
            else: graph["nodes"].remove(d)
        for rec in list(graph["links"]):
            a, b = self.items_by_id.get(rec.get("from")), self.items_by_id.get(rec.get("to"))
            if a is None or b is None or rec.get("fo", 0) >= len(a.out_socks) or rec.get("ti", 0) >= len(b.in_socks): graph["links"].remove(rec); continue
            self._add_link_item(a.out_socks[rec["fo"]], b.in_socks[rec["ti"]], rec)
        self._refresh_all(); self._apply_filter(); self.loading = False
    # ---- media filter: show only the nodes of the chosen media (plus nodes that work on every media) ----
    def set_filter(self, cid):
        self.filter_clip = cid; self._apply_filter()
    def _visible(self, d):
        if self.filter_clip is None: return True
        return d.get("p", {}).get("clip") in (None, "*", "@target", self.filter_clip)
    def _apply_filter(self):
        for it in self.items_by_id.values(): it.setVisible(self._visible(it.d))
        for li in self.link_items: li.setVisible(li.a.node.isVisible() and li.b.node.isVisible())
    def _linked_inputs(self, node): return {r["ti"] for r in self.graph["links"] if r["to"] == node.d["id"]}
    def _refresh_all(self):
        for n in self.items_by_id.values(): n.refresh_inputs(self._linked_inputs(n))
    def _add_link_item(self, out_s, in_s, rec):
        li = LinkItem(out_s, in_s, rec); self.addItem(li); self.link_items.append(li); out_s.node.links.append(li); in_s.node.links.append(li); return li
    def begin_edit(self, force=True):
        if self.on_edit and not self.loading: self.on_edit(force)
    def touched(self):
        if not self.loading: self.changed.emit()
    def new_node_dict(self, typ, pos, sel_clip=None):
        sp = NODE_TYPES[typ]; p = {}
        for key, label, kind, dflt, opts in sp["params"]: p[key] = dflt
        for i, (lab, dflt) in enumerate(sp["ins"]): p["i%d" % i] = dflt
        if sp["sink"] is not None and "clip" in p and sel_clip: p["clip"] = sel_clip
        return {"id": new_id(), "type": typ, "x": round(pos.x(), 1), "y": round(pos.y(), 1), "p": p}
    def add_node(self, typ, pos):
        if typ not in NODE_TYPES: return None
        self.begin_edit(); target = self.filter_clip if self.filter_clip is not None else self.app.sel
        d = self.new_node_dict(typ, pos, target); self.graph["nodes"].append(d)
        it = NodeItem(self, d); self.addItem(it); self.items_by_id[d["id"]] = it; self.clearSelection(); it.setSelected(True); self.touched(); return it
    def remove_node(self, it):
        nid = it.d["id"]
        for rec in [r for r in self.graph["links"] if r["from"] == nid or r["to"] == nid]: self._drop_link(rec)
        self.removeItem(it); self.items_by_id.pop(nid, None)
        if it.d in self.graph["nodes"]: self.graph["nodes"].remove(it.d)
    def _drop_link(self, rec):
        for li in [l for l in self.link_items if l.rec is rec]:
            for n in (li.a.node, li.b.node):
                if li in n.links: n.links.remove(li)
            self.removeItem(li); self.link_items.remove(li)
        if rec in self.graph["links"]: self.graph["links"].remove(rec)
        self._refresh_all()
    def delete_selected(self):
        sel = list(self.selectedItems())
        if not sel: return
        self.begin_edit()
        for it in sel:
            if isinstance(it, LinkItem) and it.rec in self.graph["links"]: self._drop_link(it.rec)
        for it in sel:
            if isinstance(it, NodeItem) and it.d["id"] in self.items_by_id: self.remove_node(it)
        self.touched()
    def duplicate_selected(self):
        src = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        if not src: return
        self.begin_edit(); self.clearSelection()
        for it in src:
            d = copy.deepcopy(it.d); d["id"] = new_id(); d["x"] += 30; d["y"] += 30; self.graph["nodes"].append(d)
            n = NodeItem(self, d); self.addItem(n); self.items_by_id[d["id"]] = n; n.setSelected(True)
        self._apply_filter(); self.touched()
    def toggle_mute(self):
        for it in [i for i in self.selectedItems() if isinstance(i, NodeItem)]:
            self.begin_edit(); it.d["p"]["mute"] = not it.d["p"].get("mute"); it.update()
        self.touched()
    # ---- wiring ----
    def _downstream(self, nid):
        seen = set(); todo = [nid]
        while todo:
            n = todo.pop()
            for r in self.graph["links"]:
                if r["from"] == n and r["to"] not in seen: seen.add(r["to"]); todo.append(r["to"])
        return seen
    def connect(self, out_s, in_s):
        a, b = out_s.node.d["id"], in_s.node.d["id"]
        if a == b or a in self._downstream(b):
            if hasattr(self.app, "toast"): self.app.toast.show_msg("That connection would create a loop")
            return False
        self.begin_edit()
        for rec in [r for r in self.graph["links"] if r["to"] == b and r["ti"] == in_s.idx]: self._drop_link(rec)
        rec = {"from": a, "fo": out_s.idx, "to": b, "ti": in_s.idx}; self.graph["links"].append(rec)
        self._add_link_item(out_s, in_s, rec); self._refresh_all(); self._apply_filter(); self.touched(); return True
    def begin_link(self, sock):
        start = sock
        if not sock.is_out:
            rec = next((r for r in self.graph["links"] if r["to"] == sock.node.d["id"] and r["ti"] == sock.idx), None)
            if rec:      # pick up an existing wire and re-route it
                start = self.items_by_id[rec["from"]].out_socks[rec["fo"]]; self.begin_edit(); self._drop_link(rec); self.touched()
        self._from = start; self._tmp = LinkItem(start if start.is_out else None, None if start.is_out else start); self.addItem(self._tmp)
        self._tmp.end = start.scenePos(); self._tmp.update_path()
    def drag_link(self, pos):
        if self._tmp is not None: self._tmp.end = pos; self._tmp.update_path()
    def end_link(self, pos):
        if self._tmp is None: return
        src = self._from; self.removeItem(self._tmp); self._tmp = None; self._from = None
        tgt = next((i for i in self.items(QRectF(pos.x() - 12, pos.y() - 12, 24, 24)) if isinstance(i, NodeSocket) and i.is_out != src.is_out and i.node is not src.node), None)
        if tgt is not None: self.connect(src, tgt) if src.is_out else self.connect(tgt, src)


class NodeView(QGraphicsView):
    def __init__(self, scene, page):
        super().__init__(scene); self.page = page; self._pan = None
        self.setRenderHint(QPainter.Antialiasing); self.setDragMode(QGraphicsView.RubberBandDrag); self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse); self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate); self.setFrameShape(QFrame.NoFrame); self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus); scene.setSceneRect(-6000, -6000, 12000, 12000); self.centerOn(0, 0)
    def fit_all(self):
        vis = [i for i in self.scene().items() if isinstance(i, NodeItem) and i.isVisible()]
        self.resetTransform()
        if not vis: self.centerOn(0, 0); return
        rect = QRectF()
        for n in vis: rect = rect.united(n.sceneBoundingRect())
        self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)
        s = self.transform().m11()
        if s > 1.4: self.resetTransform(); self.scale(1.4, 1.4); self.centerOn(rect.center())
    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(UI["tl_bg"])); g = 24; col = QColor(255, 255, 255, 18); p.setPen(QPen(col, 1.5))
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
    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace): self.page.delete_selected(); return
        if e.key() == Qt.Key_D and ctrl: self.page.scene.duplicate_selected(); return
        if e.key() == Qt.Key_Z and ctrl: self.page.app.do_undo(); return
        if e.key() == Qt.Key_Y and ctrl: self.page.app.do_redo(); return
        if e.key() == Qt.Key_M: self.page.scene.toggle_mute(); return
        if e.key() == Qt.Key_Space: self.page.app.toggle_play(); return
        super().keyPressEvent(e)
    def contextMenuEvent(self, e):
        pos = self.mapToScene(e.pos()); it = self.itemAt(e.pos()); m = QMenu(self)
        node = it
        while node is not None and not isinstance(node, (NodeItem, LinkItem)): node = node.parentItem()
        if isinstance(node, NodeItem):
            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)
            m.addAction("Duplicate", self.page.scene.duplicate_selected); m.addAction("Mute / unmute", self.page.scene.toggle_mute); m.addAction("Delete", self.page.delete_selected)
        elif isinstance(node, LinkItem):
            if not node.isSelected(): self.scene().clearSelection(); node.setSelected(True)
            m.addAction("Delete connection", self.page.delete_selected)
        else:
            for cat in NODE_CATS:
                sub = m.addMenu(cat)
                for typ, sp in NODE_TYPES.items():
                    if sp["cat"] == cat: sub.addAction(sp["title"], lambda typ=typ: self.page.scene.add_node(typ, pos))
        m.exec(e.globalPos())
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() and e.mimeData().text().startswith("minicut-node:"): e.acceptProposedAction()
    def dragMoveEvent(self, e): e.acceptProposedAction()
    def dropEvent(self, e):
        t = e.mimeData().text()
        if t.startswith("minicut-node:"): self.page.scene.add_node(t.split(":", 1)[1], self.mapToScene(e.position().toPoint())); e.acceptProposedAction(); self.setFocus()


class MediaList(QListWidget):
    """Left column: the media (clips) of the project. Choosing one shows only that media's nodes."""
    picked = Signal(object)
    def __init__(self):
        super().__init__(); self.setObjectName("MediaList"); self.setMinimumWidth(170); self.setFocusPolicy(Qt.NoFocus)
        self.currentItemChanged.connect(self._emit)
    def _emit(self, cur, prev):
        if cur is not None: self.picked.emit(cur.data(Qt.UserRole))
    def fill(self, clips, keep):
        self.blockSignals(True); self.clear()
        it = QListWidgetItem("All media (shared nodes)"); it.setData(Qt.UserRole, None); self.addItem(it)
        for c in clips:
            it = QListWidgetItem("%s  ·  %s" % (c.get("name", "clip"), KIND_NAMES.get(c.get("kind"), c.get("kind", "")))); it.setData(Qt.UserRole, c["id"]); self.addItem(it)
        row = 0
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == keep: row = i
        self.setCurrentRow(row); self.blockSignals(False)


class NodePalette(QTreeWidget):
    def __init__(self):
        super().__init__(); self.setHeaderHidden(True); self.setDragEnabled(True); self.setIndentation(14); self.setMinimumWidth(170)
        for cat in NODE_CATS:
            top = QTreeWidgetItem([cat]); top.setForeground(0, QColor(NODE_CATS[cat])); f = top.font(0); f.setBold(True); top.setFont(0, f); self.addTopLevelItem(top)
            for typ, sp in NODE_TYPES.items():
                if sp["cat"] == cat: ch = QTreeWidgetItem([sp["title"]]); ch.setData(0, Qt.UserRole, typ); top.addChild(ch)
            top.setExpanded(True)
    def startDrag(self, actions):
        it = self.currentItem(); t = it.data(0, Qt.UserRole) if it else None
        if not t: return
        md = QMimeData(); md.setText("minicut-node:" + t); dr = QDrag(self); dr.setMimeData(md); dr.exec(Qt.CopyAction)


class NodePreview(QWidget):
    """Preview with zoom (wheel or buttons), pan (drag) and double-click to fit again."""
    def __init__(self):
        super().__init__(); self.img = None; self.zoom = None; self.pan = QPointF(0, 0); self._drag = None
        self.setMinimumSize(240, 140); self.setCursor(Qt.OpenHandCursor)
    def set_img(self, img): self.img = img; self.update()
    def fit_scale(self):
        if self.img is None or self.img.isNull(): return 1.0
        return min(self.width() / max(1, self.img.width()), self.height() / max(1, self.img.height()))
    def cur_scale(self): return self.fit_scale() if self.zoom is None else self.zoom
    def set_zoom(self, z):
        self.zoom = None if z is None else max(0.1, min(8.0, z)); self.pan = QPointF(0, 0); self.update()
    def zoom_by(self, f): self.set_zoom(self.cur_scale() * f)
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), QColor(UI["vp_bg"]))
        if self.img is None or self.img.isNull():
            p.setPen(QColor("#6b7a99")); p.drawText(self.rect(), Qt.AlignCenter, "No preview yet"); return
        s = self.cur_scale(); w, h = self.img.width() * s, self.img.height() * s
        r = QRectF((self.width() - w) / 2 + self.pan.x(), (self.height() - h) / 2 + self.pan.y(), w, h)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True); p.drawImage(r, self.img)
    def wheelEvent(self, e): self.zoom_by(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag = e.position(); self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self, e):
        if self._drag is not None:
            d = e.position() - self._drag; self._drag = e.position(); self.pan = self.pan + d; self.update()
    def mouseReleaseEvent(self, e): self._drag = None; self.setCursor(Qt.OpenHandCursor)
    def mouseDoubleClickEvent(self, e): self.set_zoom(None)


class NodePage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self._pid = None; self._cp_t = 0.0; self._last_img = None
        self.media_id = None; self._chosen = False
        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 10); root.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(6)
        back = QPushButton("Editor"); back.setIcon(app_icon("angle_left")); back.clicked.connect(app.close_nodes); top.addWidget(back)
        t = QLabel("Nodes"); t.setObjectName("Logo"); top.addWidget(t); self.plabel = QLabel(""); self.plabel.setObjectName("ProjTitle"); top.addWidget(self.plabel); top.addStretch()
        self.en = QCheckBox("Nodes on"); self.en.setToolTip("Turn the whole graph off to compare with the original clips"); self.en.toggled.connect(self.set_enabled); top.addWidget(self.en)
        for label, tip, cb in (("Undo", "Undo (Ctrl+Z)", lambda: self.app.do_undo()), ("Redo", "Redo (Ctrl+Y)", lambda: self.app.do_redo()),
                               ("Fit", "Fit all visible nodes", lambda: self.view.fit_all()),
                               ("Mute", "Mute / unmute selected (M)", lambda: self.scene.toggle_mute()),
                               ("Duplicate", "Duplicate (Ctrl+D)", lambda: self.scene.duplicate_selected()),
                               ("Delete", "Delete (Del)", self.delete_selected)):
            b = QPushButton(label); b.setToolTip(tip); b.clicked.connect(cb); top.addWidget(b)
        hb = QToolButton(); hb.setText("?"); hb.setToolTip(NODE_HELP); hb.setFocusPolicy(Qt.NoFocus); top.addWidget(hb)
        root.addLayout(top)
        self.scene = NodeScene(app); self.scene.on_edit = self.checkpoint; self.scene.changed.connect(self.on_graph_changed)
        self.view = NodeView(self.scene, self)
        self.media = MediaList(); self.media.picked.connect(self.set_media)
        self.palette = NodePalette(); self.palette.itemDoubleClicked.connect(self.add_from_palette)
        pv = QWidget(); pl = QVBoxLayout(pv); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(6)
        self.preview = NodePreview(); pl.addWidget(self.preview, 1)
        tr = QHBoxLayout(); tr.setSpacing(4)
        self.prev_b = tool("", "Previous frame", lambda: app.step(-1), icon="previous")
        self.play_b = tool("", "Play / Pause (Space)", app.toggle_play, icon="play", isize=20)
        self.next_b = tool("", "Next frame", lambda: app.step(1), icon="next")
        tr.addStretch(); [tr.addWidget(b) for b in (self.prev_b, self.play_b, self.next_b)]; tr.addStretch()
        for lab, z in (("Fit", None), ("100%", 1.0), ("200%", 2.0)):
            zb = QPushButton(lab); zb.setToolTip("Preview zoom"); zb.clicked.connect(lambda _=False, z=z: self.preview.set_zoom(z)); tr.addWidget(zb)
        self.exp_b = QPushButton("Expand"); self.exp_b.setCheckable(True); self.exp_b.setToolTip("Make the preview bigger"); self.exp_b.toggled.connect(self.set_expanded); tr.addWidget(self.exp_b)
        pl.addLayout(tr)
        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, 1000); self.seek.setFocusPolicy(Qt.NoFocus); self.seek.valueChanged.connect(self.on_seek); pl.addWidget(self.seek)
        self.time = QLabel(""); self.time.setObjectName("Dim"); self.time.setAlignment(Qt.AlignCenter); pl.addWidget(self.time)
        ml = QLabel("Media  (pick one to edit its nodes)"); ml.setObjectName("H2"); pl.addWidget(ml)
        self.media.setMaximumHeight(190); pl.addWidget(self.media)
        self.body = QSplitter(Qt.Horizontal); self.body.addWidget(self.palette); self.body.addWidget(self.view); self.body.addWidget(pv)
        self.body.setSizes([200, 740, 420]); self.body.setStretchFactor(0, 0); self.body.setStretchFactor(1, 1); self.body.setStretchFactor(2, 0)
        root.addWidget(self.body, 1)
        self.timer = QTimer(self); self.timer.setInterval(90); self.timer.timeout.connect(self.sync)
    # ---- model ----
    def reload(self):
        P = self.app.proj
        if P is None: return
        if not hasattr(P, "graph") or not isinstance(P.graph, dict): P.graph = default_graph()
        self._pid = id(P)
        ids = {c["id"] for c in P.clips}
        if self.media_id is not None and self.media_id not in ids: self.media_id = None
        if self.media_id is None and not self._chosen and self.app.sel in ids: self.media_id = self.app.sel
        self.scene.load(P.graph); self.scene.set_filter(self.media_id)
        self.media.fill(P.clips, self.media_id)
        self.en.blockSignals(True); self.en.setChecked(P.graph.get("on", True)); self.en.blockSignals(False)
        self._update_title()
    def _update_title(self):
        P = self.app.proj
        if P is None: return
        c = next((c for c in P.clips if c["id"] == self.media_id), None)
        self.plabel.setText(P.name + ("  ·  " + c.get("name", "clip") if c else "  ·  all media"))
    def set_media(self, cid):
        self._chosen = True; self.media_id = cid; self.scene.set_filter(cid); self.view.fit_all(); self._update_title()
    def set_expanded(self, v):
        self.body.setSizes([160, 380, 900] if v else [200, 740, 420])
    def checkpoint(self, force=True):
        now = time.monotonic()
        if (force or now - self._cp_t > 0.6) and self.app.proj: self.app.checkpoint()
        self._cp_t = now
    def on_graph_changed(self): self.app.graph_edited()
    def set_enabled(self, v):
        self.checkpoint(True); self.app.proj.graph["on"] = bool(v); self.app.graph_edited()
    def delete_selected(self): self.scene.delete_selected()
    def add_from_palette(self, it, col):
        typ = it.data(0, Qt.UserRole)
        if typ: self.scene.add_node(typ, self.view.mapToScene(self.view.viewport().rect().center()))
    def on_seek(self, v):
        if self.app.proj and not getattr(self, "_syncing", False): self.app.seek(self.app.proj.duration() * v / 1000.0)
    # ---- live updates ----
    def showEvent(self, e):
        super().showEvent(e)
        if self.app.proj is not None: self.reload()
        self.timer.start()
    def hideEvent(self, e): super().hideEvent(e); self.timer.stop()
    def sync(self):
        a = self.app; P = a.proj
        if P is None or not self.isVisible(): return
        self._syncing = True
        dur = max(0.01, P.duration()); self.seek.setValue(int(max(0.0, min(1.0, a.t / dur)) * 1000)); self._syncing = False
        self.time.setText(fmt_time(a.t, P.fps) + " / " + fmt_time(P.duration(), P.fps)); set_play_icon(self.play_b, a.playing)
        img = getattr(a.viewport, "img", None) if hasattr(a, "viewport") else None
        if img is not self._last_img: self._last_img = img; self.preview.set_img(img)
        try:
            clip = next((c for c in P.clips if c["id"] == self.media_id), None) if self.media_id else None
            if clip is None: clip = a.sel_clip() or next((c for c in P.clips if c["kind"] in ("video", "image", "gif", "text")), None)
            memo, err = node_debug(P, a.t, clip)
            for nid, it in self.scene.items_by_id.items():
                vals = memo.get(nid)
                for j, lab in enumerate(it.readouts):
                    base = it.spec["outs"][j]; lab.setText(base if vals is None or j >= len(vals) else "%s  %.2f" % (base, vals[j]))
                if nid in err: it.setToolTip("This node is part of a loop or failed; its value was ignored")
        except Exception as ex: print("[nodes] readout:", ex)


class NodesMixin:
    """Opening the node editor page."""
    def open_nodes(self):
        if not self.proj: return
        self.stop_play()
        if not hasattr(self, "nodes_page"): self.nodes_page = NodePage(self); self.stack.addWidget(self.nodes_page)
        self.nodes_page.reload(); self.stack.setCurrentWidget(self.nodes_page); self.request_render()
    def close_nodes(self):
        if self.proj: self.stack.setCurrentWidget(self.editor); self.on_changed(insp=False)
    def in_nodes(self): return hasattr(self, "nodes_page") and self.stack.currentWidget() is self.nodes_page
    def graph_edited(self):
        """The node graph changed: drop cached frames and re-render with the new graph."""
        if not self.proj: return
        self.renderer.clear_preview_cache(); self.request_render()

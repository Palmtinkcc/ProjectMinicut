"""Better Chroma Key, 'Select object' mode: the controls in the effect card, the paint window and the render job.
The rendering itself is in render/smartkey.py; this file only has the widgets and the glue to the project."""
import copy
from PySide6.QtCore import Slot
from ..shared.deps import *
from ..shared.ui import Btn, label
from ..shared.tasks import TASKS
from ..shared.core import src_time
from ..render import smartkey as sk

_JOBS = {}        # (clip id, effect id) -> running _Job


def _clip_effect(app, cid, eid):
    c = next((x for x in app.proj.clips if x["id"] == cid), None) if app.proj else None
    e = next((x for x in (c or {}).get("effects", []) if x["id"] == eid), None) if c else None
    return c, e


def _toast(app, text):
    try: app.toast.show_msg(text, 2600)
    except Exception: pass


# ---------------------------------------------------------------------------------------------------- the render job
class _Job(QThread):
    ok = Signal(object)
    bad = Signal(str)
    def __init__(self, app, cid, eid, args, sig):
        super().__init__(); self.app = app; self.cid = cid; self.eid = eid; self.args = args; self.sig = sig
        self.task = TASKS.start("smartkey", "Better Chroma Key: rendering"); self.task.total = 1000; self.task.cancel_fn = lambda: None
        self.frac = 0.0; self.text = "Starting"
        self.ok.connect(self._done); self.bad.connect(self._failed)
    def _prog(self, f, t=""):
        self.frac = f; self.text = t; self.task.done = int(f * 1000); self.task.detail = t
    def run(self):
        try:
            info = sk.bake(*self.args, progress=self._prog, cancel=lambda: self.task.cancelled)
            self.ok.emit(info)
        except sk.Cancelled: self.bad.emit("")
        except Exception as ex: self.bad.emit(str(ex) or ex.__class__.__name__)
        finally: self.task.finish()
    @Slot(object)
    def _done(self, info):
        _JOBS.pop((self.cid, self.eid), None); app = self.app
        c, e = _clip_effect(app, self.cid, self.eid)
        if e is None: return                                  # the clip or the effect is gone: the file stays in the cache
        info["sig"] = self.sig; app.checkpoint(); e["bake"] = info
        try: app.renderer.clear_preview_cache()
        except Exception: pass
        app.on_changed(); _toast(app, "Better Chroma Key: rendered. The clip now uses the rendered media")
    @Slot(str)
    def _failed(self, msg):
        _JOBS.pop((self.cid, self.eid), None)
        if msg: _toast(self.app, "Better Chroma Key: " + msg)


def start_render(app, c, e):
    key = (c["id"], e["id"])
    if key in _JOBS: return
    if c.get("kind") not in ("video", "image"): _toast(app, "Select object works on videos and pictures"); return
    strokes = copy.deepcopy(e.get("strokes") or [])
    if not any(s.get("k") == "fg" for s in strokes): _toast(app, "Paint the object first"); return
    hit = sk.cached_info(c, e)
    if hit is not None:                                       # the same paint was rendered before: use it at once
        hit["sig"] = sk.sig_of(c, e); app.checkpoint(); e["bake"] = hit; app.renderer.clear_preview_cache(); app.on_changed(); return
    quality = (e.get("p") or {}).get("quality", "normal")
    span = None if c["kind"] == "image" else sk.used_span(c)
    job = _Job(app, c["id"], e["id"], (c["path"], c["kind"], strokes, quality, sk.out_path_for(c, e), span), sk.sig_of(c, e))
    _JOBS[key] = job; job.start()


# ---------------------------------------------------------------------------------------------------- the paint window
class _Canvas(QWidget):
    changed = Signal()
    def __init__(self, bgr):
        super().__init__(); self.setMinimumSize(520, 340); self.setMouseTracking(True)
        h, w = bgr.shape[:2]; rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        self.qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy(); self.cut = None
        self.strokes = []; self.tool = "fg"; self.rad = 0.012; self.show_cut = False; self._cur = None; self._pos = None
    def _img_rect(self):
        w, h = self.qimg.width(), self.qimg.height(); s = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * s) / 2, (self.height() - h * s) / 2, w * s, h * s)
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.fillRect(0, 0, self.width(), self.height(), QColor("#16161b")); r = self._img_rect()
        p.drawImage(r, self.cut if (self.show_cut and self.cut is not None) else self.qimg)
        for s in self.strokes: self._draw(p, s, r)
        if self._pos is not None and r.contains(self._pos):
            rad = self.rad * r.width(); p.setPen(QPen(QColor(255, 255, 255, 230), 1.5)); p.setBrush(Qt.NoBrush); p.drawEllipse(self._pos, rad, rad)
    def _draw(self, p, s, r):
        col = QColor(40, 220, 90, 150) if s["k"] == "fg" else QColor(240, 60, 60, 150)
        pen = QPen(col, max(1.0, 2 * s["r"] * r.width()), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin); p.setPen(pen)
        pts = [QPointF(r.x() + x * r.width(), r.y() + y * r.height()) for x, y in s["pts"]]
        if len(pts) == 1: p.drawPoint(pts[0])
        else:
            for a, b in zip(pts, pts[1:]): p.drawLine(a, b)
    def _norm(self, pos):
        r = self._img_rect(); return [min(1.0, max(0.0, (pos.x() - r.x()) / r.width())), min(1.0, max(0.0, (pos.y() - r.y()) / r.height()))]
    def mousePressEvent(self, ev):
        if ev.button() not in (Qt.LeftButton, Qt.RightButton): return
        kind = self.tool if ev.button() == Qt.LeftButton else ("bg" if self.tool == "fg" else "fg")       # right button = the other brush
        self._cur = {"k": kind, "r": self.rad, "pts": [self._norm(ev.position())]}; self.strokes.append(self._cur); self.show_cut = False; self.update(); self.changed.emit()
    def mouseMoveEvent(self, ev):
        self._pos = ev.position()
        if self._cur is not None:
            q = self._norm(ev.position()); last = self._cur["pts"][-1]
            if abs(q[0] - last[0]) + abs(q[1] - last[1]) > 0.002: self._cur["pts"].append(q)
        self.update()
    def mouseReleaseEvent(self, ev): self._cur = None; self.changed.emit()
    def leaveEvent(self, ev): self._pos = None; self.update()
    def set_cut(self, col, alpha):
        h, w = alpha.shape; ys, xs = np.mgrid[0:h, 0:w]; chk = (((ys // 16) + (xs // 16)) % 2 * 40 + 70).astype(np.float32)[..., None]
        a = alpha[..., None].astype(np.float32) / 255.0; out = np.clip(col.astype(np.float32) * a + chk * (1 - a), 0, 255).astype(np.uint8)
        rgb = np.ascontiguousarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)); self.cut = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


class SeedPainter(QDialog):
    """Paint the object (green) and, where the program mixes things up, the background (red); look at the cut-out; OK."""
    def __init__(self, app, c, e, parent=None):
        super().__init__(parent or app); self.setWindowTitle("Better Chroma Key - paint the object"); self.resize(980, 700); self.setModal(True)
        self.c = c; self.e = e; self.quality = (e.get("p") or {}).get("quality", "normal")
        lt = min(max(0.0, float(app.t - c.get("start", 0.0))), float(c.get("dur", 0.0))); ts = src_time(c, lt) if c["kind"] != "image" else 0.0
        bgr, self.fidx, fps = sk.read_source_frame(c["path"], c["kind"], ts)
        self.full = bgr; self.scale = 1.0
        if bgr.shape[1] > 1280: self.scale = 1280.0 / bgr.shape[1]; bgr = cv2.resize(bgr, (1280, int(round(bgr.shape[0] * self.scale))), interpolation=cv2.INTER_AREA)
        self.small = bgr; self.cv = _Canvas(bgr)
        self.cv.strokes = [copy.deepcopy({k: v for k, v in s.items() if k != "f"}) for s in (e.get("strokes") or []) if int(s.get("f", 0)) == self.fidx]
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(8)
        hint = label("Paint over the object with the green brush. If part of the background gets taken too, paint that part with the red brush (or use the right mouse button). "
                     "Press Preview to see the cut-out. To help it follow the object, move the playhead to another moment and paint again there.", True, 12); hint.setWordWrap(True); lay.addWidget(hint)
        row = QHBoxLayout(); row.setSpacing(8)
        self.b_fg = Btn("Object", None, "accent", "Green brush: this is the object", None, True); self.b_bg = Btn("Background", None, "soft", "Red brush: this is not the object", None, True); self.b_fg.setChecked(True)
        self.b_fg.clicked.connect(lambda: self._tool("fg")); self.b_bg.clicked.connect(lambda: self._tool("bg")); row.addWidget(self.b_fg); row.addWidget(self.b_bg)
        row.addWidget(label("Brush", True, 12)); self.sl = QSlider(Qt.Horizontal); self.sl.setRange(2, 60); self.sl.setValue(12); self.sl.setFixedWidth(160)
        self.sl.valueChanged.connect(lambda v: (setattr(self.cv, "rad", v / 1000.0), self.cv.update())); row.addWidget(self.sl); row.addStretch(1)
        self.b_undo = Btn("Undo stroke", None, "ghost", "", self._undo); self.b_clear = Btn("Clear", None, "ghost", "Remove all paint on this frame", self._clear)
        self.b_prev = Btn("Preview cut-out", None, "soft", "Cut the object out of this frame with the paint so far", self._preview); self.b_view = Btn("Show paint", None, "ghost", "", self._toggle_view)
        for b in (self.b_undo, self.b_clear, self.b_prev, self.b_view): row.addWidget(b)
        lay.addLayout(row); lay.addWidget(self.cv, 1)
        self.info = label("", True, 12); lay.addWidget(self.info)
        bot = QHBoxLayout(); bot.addStretch(1); bc = Btn("Cancel", None, "ghost", "", self.reject); bo = Btn("Use this paint", None, "accent", "", self.accept); bot.addWidget(bc); bot.addWidget(bo); lay.addLayout(bot)
        self.cv.changed.connect(self._info); self._info()
    def _tool(self, t):
        self.cv.tool = t; self.b_fg.setChecked(t == "fg"); self.b_bg.setChecked(t == "bg")
    def _undo(self):
        if self.cv.strokes: self.cv.strokes.pop(); self.cv.show_cut = False; self.cv.update(); self._info()
    def _clear(self): self.cv.strokes = []; self.cv.show_cut = False; self.cv.update(); self._info()
    def _toggle_view(self):
        if self.cv.cut is None: return
        self.cv.show_cut = not self.cv.show_cut; self.b_view.label = "Show paint" if self.cv.show_cut else "Show cut-out"; self.b_view.update(); self.cv.update()
    def _info(self):
        n_fg = sum(1 for s in self.cv.strokes if s["k"] == "fg"); others = len({int(s.get("f", 0)) for s in (self.e.get("strokes") or []) if int(s.get("f", 0)) != self.fidx})
        self.info.setText("%d object stroke%s, %d background stroke%s on this frame%s" % (n_fg, "" if n_fg == 1 else "s", len(self.cv.strokes) - n_fg, "" if len(self.cv.strokes) - n_fg == 1 else "s",
                          ("  ·  painted on %d other frame%s" % (others, "" if others == 1 else "s")) if others else ""))
    def _preview(self):
        if not any(s["k"] == "fg" for s in self.cv.strokes): self.info.setText("Paint the object first"); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            col, al = sk.segment_still(self.small, copy.deepcopy(self.cv.strokes), self.quality); self.cv.set_cut(col, al); self.cv.show_cut = True; self.b_view.label = "Show paint"; self.b_view.update()
        except Exception as ex: self.info.setText("Could not cut it out: %s" % ex)
        finally: QApplication.restoreOverrideCursor()
        self.cv.update()
    def result(self):
        """The strokes of the effect after this window: the other frames' strokes stay, this frame's are replaced."""
        keep = [s for s in (self.e.get("strokes") or []) if int(s.get("f", 0)) != self.fidx]
        mine = [dict(copy.deepcopy(s), f=int(self.fidx)) for s in self.cv.strokes]
        for s in mine: s["pts"] = [[round(x, 5), round(y, 5)] for x, y in s["pts"]]; s["r"] = round(s["r"], 5)
        return keep + mine


def open_painter(app, c, e):
    try: dlg = SeedPainter(app, c, e)
    except Exception as ex: _toast(app, "Cannot show this frame: %s" % ex); return
    if dlg.exec() == QDialog.Accepted:
        app.checkpoint(); e["strokes"] = dlg.result()
        try: app.renderer.clear_preview_cache()
        except Exception: pass
        app.on_changed(insp=False)


# ---------------------------------------------------------------------------------------------------- the part of the effect card
def build(panel, v, e, info):
    """Adds the 'Select object' controls under the sliders of the card (only in that mode)."""
    if (e.get("p") or {}).get("mode") != "object": return
    app = panel.app; c0 = app.sel_clip(); cid = c0["id"]; eid = e["id"]
    box = QFrame(); lay = QVBoxLayout(box); lay.setContentsMargins(0, 2, 0, 0); lay.setSpacing(6)
    st = label("", True, 12); st.setWordWrap(True); lay.addWidget(st)
    bar = QProgressBar(); bar.setRange(0, 1000); bar.setTextVisible(False); bar.setFixedHeight(6); lay.addWidget(bar)
    row = QHBoxLayout(); row.setSpacing(8)
    b_paint = Btn("Paint object", None, "soft", "Paint the object (and the background) on the frame under the playhead"); b_render = Btn("Render", None, "accent", "Cut the object out of the whole clip. It takes a while; the rendered media then replaces the original while this effect is on")
    b_cancel = Btn("Cancel", None, "danger", "Stop rendering"); b_orig = Btn("Use original", None, "ghost", "Forget the render: the original media is used again")
    for b in (b_paint, b_render, b_cancel, b_orig): row.addWidget(b)
    lay.addLayout(row); v.addWidget(box)
    def cur():
        return _clip_effect(app, cid, eid)
    def paint():
        c, ee = cur()
        if ee is not None: open_painter(app, c, ee); refresh()
    def render():
        c, ee = cur()
        if ee is not None: start_render(app, c, ee); refresh()
    def cancel():
        j = _JOBS.get((cid, eid))
        if j is not None: j.task.cancel()
    def orig():
        c, ee = cur()
        if ee is not None and ee.get("bake"):
            app.checkpoint(); ee.pop("bake", None)
            try: app.renderer.clear_preview_cache()
            except Exception: pass
            app.on_changed(); refresh()
    b_paint.clicked.connect(paint); b_render.clicked.connect(render); b_cancel.clicked.connect(cancel); b_orig.clicked.connect(orig)
    tm = QTimer(box); tm.setInterval(350)
    def refresh():
        c, ee = cur()
        if ee is None: tm.stop(); return
        job = _JOBS.get((cid, eid)); code, text = sk.state_of(c, ee)
        if job is not None:
            bar.setVisible(True); bar.setValue(int(job.frac * 1000)); st.setText("Rendering: %s (%d%%)" % (job.text, int(job.frac * 100)))
        else:
            bar.setVisible(False); st.setText(text)
        b_cancel.setVisible(job is not None); b_render.setVisible(job is None); b_paint.setEnabled(job is None)
        b_render.setEnabled(code != "ready" and code != "none" or (code == "none" and any(s.get("k") == "fg" for s in (ee.get("strokes") or []))))
        b_render.label = "Render again" if code in ("stale", "short") else "Render"; b_render.update()
        b_orig.setVisible(job is None and bool(ee.get("bake")))
    tm.timeout.connect(refresh); tm.start(); refresh()

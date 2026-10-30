"""Progress ring at the bottom right of the window: shows the background work that is running."""
import time
from ..shared.deps import *
from ..shared.tasks import TASKS
from ..shared.icons import *
from ..shared.widgets import AnimatedDialog, tool
from ..render.export import EXPORTS
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMessageBox

RING_ACCENT = "#2fb6ff"      # the blue arc (fixed colour, so it is visible in every theme)
RING_TRACK = "#3a4150"


class ProgressRing(QWidget):
    def __init__(self, parent):
        super().__init__(parent); self.setFixedSize(46, 46); self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)   # no square behind the ring
        self.shown = []; self.hide()
        self.timer = QTimer(self); self.timer.setInterval(120); self.timer.timeout.connect(self._poll); self.timer.start()
    def _poll(self):
        self.shown = TASKS.snapshot()
        self.setVisible(bool(self.shown))
        if self.shown:
            lines = []
            for t in self.shown:
                f = t.fraction()
                pct = ("%d%%" % round(f * 100)) if f is not None else "starting…"
                lines.append("%s   %s%s" % (t.title, pct, ("   " + t.detail) if t.detail else ""))
            self.setToolTip("\n".join(lines))
        self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(6, 6, 34, 34)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(RING_TRACK), 4)); p.drawEllipse(r)
        if not self.shown: return
        t = self.shown[-1]; f = t.fraction()
        p.setPen(QPen(QColor(RING_ACCENT), 4, Qt.SolidLine, Qt.RoundCap))
        if f is None:                                  # not known yet: a turning arc
            start = int((time.monotonic() * 360 * 1.5) % 360); p.drawArc(r, start * 16, -110 * 16)
        else:
            p.drawArc(r, 90 * 16, -max(1, int(f * 360 * 16)))
        p.setPen(QColor("#dfe3ea")); font = QFont(p.font()); font.setPointSize(max(7, font.pointSize() - 2)); p.setFont(font)
        label = str(len(self.shown)) if len(self.shown) > 1 else ("%d" % round(f * 100) if f is not None else "")
        p.drawText(self.rect(), Qt.AlignCenter, label)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            w = self.window()
            if hasattr(w, "show_tasks"): w.show_tasks()


def reveal_file(path):
    """Show a finished file in the file manager."""
    try:
        if os.name == "nt" and os.path.isfile(path): subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))
    except Exception as ex: print("[tasks] could not open the folder:", ex)


def _fmt_eta(sec):
    if sec is None: return ""
    sec = int(sec); return ("%d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60)) if sec >= 3600 else ("%d:%02d" % (sec // 60, sec % 60))


class TaskRow(QFrame):
    """One line of the tasks window: state icon, title, progress bar, and the buttons that make sense for its state."""
    def __init__(self, key):
        super().__init__(); self.key = key; self.setObjectName("TaskRow"); self._state = None
        h = QHBoxLayout(self); h.setContentsMargins(10, 8, 8, 8); h.setSpacing(10)
        self.ico = QLabel(); self.ico.setFixedSize(26, 26); self.ico.setAlignment(Qt.AlignCenter); h.addWidget(self.ico)
        col = QVBoxLayout(); col.setSpacing(4); self.title = QLabel(); self.title.setObjectName("TaskTitle")
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedHeight(6); self.bar.setRange(0, 1000)
        self.info = QLabel(); self.info.setObjectName("Dim"); col.addWidget(self.title); col.addWidget(self.bar); col.addWidget(self.info); h.addLayout(col, 1)
        self.b_open = tool("", "Show in folder", None, icon="folder_open", isize=18); self.b_cancel = tool("", "Cancel", None, icon="cancel", isize=20); self.b_rm = tool("", "Remove from list", None, icon="close", isize=16)
        for b in (self.b_open, self.b_cancel, self.b_rm): h.addWidget(b)
    def set(self, state, title, frac, info, can_cancel, can_open, can_remove):
        if state != self._state:
            self._state = state
            name, col = {"running": ("downloading", "#2fb6ff"), "queued": ("wait", "#9aa4b8"), "done": ("done", "#3ddc97"),
                         "failed": ("info", "#ff6b6b"), "cancelled": ("cancel", "#9aa4b8")}.get(state, ("downloading", "#2fb6ff"))
            self.ico.setPixmap(svg_pixmap(name, col, 22))
        self.title.setText(title); self.info.setText(info)
        self.bar.setRange(0, 0 if (frac is None and state == "running") else 1000); self.bar.setValue(int((frac or (1.0 if state == "done" else 0.0)) * 1000))
        self.b_cancel.setVisible(can_cancel); self.b_open.setVisible(can_open); self.b_rm.setVisible(can_remove)


class TasksDialog(AnimatedDialog):
    """Everything that works in the background: every export (each one can be cancelled on its own), proxies, audio work.
    Exports run in parallel up to the number in the corner; the others wait in line."""
    def __init__(self, app):
        super().__init__(app, "Tasks", 540); self.app = app; self.rows = {}; self.setAttribute(Qt.WA_DeleteOnClose)
        top = QHBoxLayout(); top.setSpacing(6); top.addWidget(icon_label("queue", "#9aa4b8", 18)); self.par = QSpinBox(); self.par.setRange(1, 8); self.par.setValue(int(EXPORTS.max_parallel))
        self.par.setToolTip("How many exports run at the same time"); self.par.valueChanged.connect(self._set_par); top.addWidget(self.par); top.addStretch()
        b = tool("", "Cancel everything", self._cancel_all, icon="delete", isize=18); top.addWidget(b); self.body.addLayout(top)
        self.host = QWidget(); self.lay = QVBoxLayout(self.host); self.lay.setContentsMargins(0, 0, 0, 0); self.lay.setSpacing(6); self.lay.addStretch(1)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(self.host); sa.setMinimumHeight(240); sa.setFrameShape(QFrame.NoFrame); self.body.addWidget(sa, 1)
        self.empty = QLabel(); self.empty.setPixmap(svg_pixmap("done", "#3ddc97", 40)); self.empty.setAlignment(Qt.AlignCenter); self.lay.insertWidget(0, self.empty)
        self.timer = QTimer(self); self.timer.setInterval(300); self.timer.timeout.connect(self.refresh); self.timer.start(); self.refresh()
    def _set_par(self, v):
        EXPORTS.max_parallel = int(v); self.app.settings["export_parallel"] = int(v); self.app.settings.save(); EXPORTS._pump()
    def _cancel_all(self):
        EXPORTS.cancel_all()
        for t in TASKS.snapshot():
            if t.can_cancel(): t.cancel()
    def refresh(self):
        items = [("job", w) for w in EXPORTS.jobs] + [("task", t) for t in TASKS.snapshot() if t.kind != "export"]
        seen = set()
        for kind, o in items:
            key = id(o); seen.add(key); row = self.rows.get(key)
            if row is None:
                row = self.rows[key] = TaskRow(key); self.lay.insertWidget(self.lay.count() - 1, row)
                row.b_cancel.clicked.connect(lambda _=False, o=o, kind=kind: EXPORTS.cancel(o) if kind == "job" else o.cancel())
                if kind == "job":
                    row.b_open.clicked.connect(lambda _=False, o=o: reveal_file(o.out)); row.b_rm.clicked.connect(lambda _=False, o=o: EXPORTS.remove(o))
            if kind == "job":
                t = o._task; f = t.fraction() if (t is not None and o.state == "running") else None
                if o.state == "running": eta = t.eta() if t is not None else None; info = ("%d%%" % round(f * 100) if f is not None else "…") + (("   ·   " + _fmt_eta(eta)) if eta else "") + (("   ·   " + t.detail) if (t is not None and t.detail) else "")
                else: info = {"queued": "waiting", "done": "done", "cancelled": "cancelled", "failed": o.msg[-90:].replace("\n", " ")}.get(o.state, "")
                row.set(o.state, o.title, f, info, o.state in ("queued", "running"), o.state == "done", o.state in ("done", "failed", "cancelled"))
            else:
                f = o.fraction(); eta = o.eta()
                info = ("%d%%" % round(f * 100) if f is not None else "…") + (("   ·   " + _fmt_eta(eta)) if eta else "") + (("   ·   " + o.detail) if o.detail else "")
                row.set("running", o.title, f, info, o.can_cancel(), False, False)
        for key in [k for k in self.rows if k not in seen]:
            r = self.rows.pop(key); self.lay.removeWidget(r); r.deleteLater()
        self.empty.setVisible(not self.rows)
    def done(self, r):
        self.timer.stop(); super().done(r)


class _Placer(QObject):
    def __init__(self, ring):
        super().__init__(); self.ring = ring
    def place(self, main):
        self.ring.move(main.width() - self.ring.width() - 16, main.height() - self.ring.height() - 16); self.ring.raise_()
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize: self.place(obj)
        return False


def install_progress(main):
    ring = ProgressRing(main); pl = _Placer(ring); main._progress_placer = pl
    main.installEventFilter(pl); pl.place(main); return ring

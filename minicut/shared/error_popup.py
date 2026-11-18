"""The corner card (Patch 58): tells the user what the error hub (minicut/errors.py) collected. It only informs: nothing has to be answered or clicked.

  * a card in the BOTTOM-RIGHT corner of the main window (a child widget, not a separate window: it never takes the keyboard focus and moves with the window)
  * a new major problem  -> the card opens with two calm lines: what it is, and what MiniCut is doing about it; after ~8 s it shrinks to a small badge "! 3"
  * a minor problem      -> only the badge appears / its number grows, quietly
  * click the badge (or "Details") -> the full list: what, how often, what was done; "Copy" for the text, "Clear" to forget, "Shrink" to go back to the badge
  * the card stays open while the mouse is over it; a badge stays until it is cleared
  * a problem that was cleared stays quiet; a NEW problem or a breaker trip shows the card again
  * after a crash, the next start shows what the last run left in crash.log, inside the same card

The hub calls its sinks on whatever thread reported the error. The sink copies the report into a plain dict and emits a Qt signal; the slot runs on the GUI thread,
so no widget is ever touched from a render thread.
"""
import time
from PySide6.QtCore import QObject, Signal, Qt, QTimer, QEvent
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QApplication

from .. import errors as _errors

AUTO_COLLAPSE_MS = 8000           # the card shrinks to the badge after this long
POLL_MS = 500                     # while the card is open the counters are re-read this often
MARGIN = 16

QSS = """
QFrame#errcard { background: rgba(34,36,42,238); border: 1px solid #d9a441; border-radius: 9px; }
QFrame#errcard QLabel { color: #ececec; background: transparent; }
QFrame#errcard QLabel#errtitle { font-weight: bold; }
QFrame#errcard QLabel#errsub { color: #bdbdbd; }
QFrame#errcard QPlainTextEdit { background: rgba(20,21,25,255); color: #dcdcdc; border: 1px solid #44464c; border-radius: 5px; font-family: Consolas, monospace; }
QFrame#errcard QPushButton { color: #ececec; background: rgba(255,255,255,18); border: 1px solid #55575d; border-radius: 5px; padding: 3px 10px; }
QFrame#errcard QPushButton:hover { background: rgba(255,255,255,40); }
QFrame#errcard QPushButton#errbadge { color: #ffcf6e; font-weight: bold; border: none; background: transparent; padding: 3px 8px; }
"""


def plain(d):
    """(title, sub-line) in calm words for one entry (a dict made by Report.as_dict + 'text')."""
    src = d.get("source", "")
    if d.get("notice"): return d["notice"], "Details are inside - nothing needs to be done."
    if src.startswith("gpu.pressure") or src in ("gpu.memory", "gpu.leak"): title = "GPU memory is nearly full"
    elif src.startswith("bone2d"): title = "Bone 2D had a drawing problem"
    elif src.startswith("gpu."): title = "The GPU renderer had a problem"
    elif src.startswith("thread:") or src in ("uncaught", "unraisable"): title = "Something unexpected happened"
    else: title = "A problem was detected"
    fx = d.get("fixes") or []
    sub = ("Now: " + fx[-1]) if fx else "MiniCut keeps running; the details are saved."
    return title, sub


def describe(d):
    """The text of one entry for the details list: what, how often, what is being done."""
    if d.get("notice"): return d.get("text", "")
    lines = ["%s  -  %s" % (d["source"], d["kind"]), d["message"], "happened %d time%s in %.1f s" % (d["count"], "" if d["count"] == 1 else "s", d["seconds"])]
    if d.get("tripped"): lines.append("MiniCut stopped retrying this for a while, so it cannot fill the machine up")
    fx = d.get("fixes") or []
    lines.append("being done about it:" if fx else "being done about it: nothing automatic for this one")
    lines += ["   - " + f for f in fx]
    return "\n".join(lines)


class ErrorCard(QFrame):
    """Three looks of one widget: 'pill' (badge), 'summary' (two lines), 'details' (the list)."""

    def __init__(self, win):
        super().__init__(win); self.win = win; self.setObjectName("errcard"); self.setStyleSheet(QSS); self.setFocusPolicy(Qt.NoFocus)
        self.state = "pill"; self._hover = False; self._full = ""; self.n = 0
        v = QVBoxLayout(self); v.setContentsMargins(12, 8, 12, 8); v.setSpacing(6)
        top = QHBoxLayout(); top.setSpacing(8)
        self.badge = QPushButton("!"); self.badge.setObjectName("errbadge"); self.badge.setCursor(Qt.PointingHandCursor); self.badge.setFocusPolicy(Qt.NoFocus); top.addWidget(self.badge)
        self.title = QLabel(); self.title.setObjectName("errtitle"); top.addWidget(self.title, 1); v.addLayout(top)
        self.sub = QLabel(); self.sub.setObjectName("errsub"); self.sub.setWordWrap(True); self.sub.setMinimumWidth(300); self.sub.setMaximumWidth(380); v.addWidget(self.sub)
        self.box = QPlainTextEdit(); self.box.setReadOnly(True); self.box.setFixedSize(420, 190); self.box.setFocusPolicy(Qt.NoFocus); v.addWidget(self.box)
        self.row = QHBoxLayout(); self.row.addStretch(1)
        self.b_details = QPushButton("Details"); self.b_copy = QPushButton("Copy"); self.b_clear = QPushButton("Clear"); self.b_shrink = QPushButton("Shrink")
        for b in (self.b_details, self.b_copy, self.b_clear, self.b_shrink): b.setFocusPolicy(Qt.NoFocus); self.row.addWidget(b)
        v.addLayout(self.row)
        self.badge.clicked.connect(self._badge_clicked); self.b_details.clicked.connect(lambda: self.set_state("details")); self.b_shrink.clicked.connect(lambda: self.set_state("pill"))
        self.b_copy.clicked.connect(self._copy); self.collapse = QTimer(self); self.collapse.setSingleShot(True); self.collapse.timeout.connect(self._auto_collapse)
        win.installEventFilter(self); self.hide()

    # ── looks
    def set_state(self, state):
        self.state = state; pill = state == "pill"; summ = state == "summary"; det = state == "details"
        self.title.setVisible(not pill); self.sub.setVisible(summ); self.box.setVisible(det)
        self.b_details.setVisible(summ); self.b_copy.setVisible(det); self.b_clear.setVisible(not pill); self.b_shrink.setVisible(det)
        self._badge_text(); self.layout().invalidate(); self.adjustSize(); self.place(); self.show(); self.raise_()
        if summ: self.collapse.start(AUTO_COLLAPSE_MS)
        else: self.collapse.stop()

    def _badge_text(self): self.badge.setText("!  %d" % self.n if self.state == "pill" else "!")

    def set_content(self, n, title, sub, details, full):
        self.n = n; self.title.setText(title); self.sub.setText(sub); self.box.setPlainText(details); self._full = full; self._badge_text()
        self.badge.setToolTip("%d problem%s - click for details" % (n, "" if n == 1 else "s"))
        if self.state == "pill": self.adjustSize(); self.place()

    def place(self):
        self.move(max(0, self.win.width() - self.width() - MARGIN), max(0, self.win.height() - self.height() - MARGIN))

    def _badge_clicked(self): self.set_state("pill" if self.state == "details" else "details")      # badge or summary -> details; details -> badge
    def _auto_collapse(self):
        if self._hover: self.collapse.start(1500)                     # the mouse is on it: wait
        elif self.state == "summary": self.set_state("pill")
    def _copy(self):
        QApplication.clipboard().setText(self._full); self.b_copy.setText("Copied"); QTimer.singleShot(1500, lambda: self.b_copy.setText("Copy"))

    def enterEvent(self, e): self._hover = True; super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; super().leaveEvent(e)

    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() in (QEvent.Resize, QEvent.Show) and self.isVisible(): self.place()
        return False


class ErrorPresenter(QObject):
    _got = Signal(str, object)

    def __init__(self, win, hub=None):
        super().__init__(win); self.win = win; self.hub = hub or _errors.HUB; self.card = ErrorCard(win); self.entries = {}; self.quiet = set(); self.notices = {}
        self.poll = QTimer(self); self.poll.setInterval(POLL_MS); self.poll.timeout.connect(self._poll)
        self.card.b_clear.clicked.connect(self.clear); self._got.connect(self._on_event, Qt.QueuedConnection); self.hub.add_sink(self._sink)
        self.last_major = None

    def _sink(self, event, rep):                       # any thread: copy, emit, return
        try:
            d = rep.as_dict(); d["text"] = rep.text(); d["key"] = "%s|%s|%s" % rep.key; self._got.emit(event, d)
        except Exception: pass

    def _on_event(self, event, d):                     # GUI thread
        try:
            k = d["key"]
            if k in self.quiet and event not in ("new", "trip"): return               # cleared and still going on: stay quiet
            if event in ("new", "trip"): self.quiet.discard(k)
            self.entries[k] = d
            if not self.poll.isActive(): self.poll.start()
            if d["severity"] != _errors.MINOR and event in ("new", "trip", "fix"):    # something new, or what MiniCut does about it changed
                self.last_major = k
                if self.card.state == "details": self._refresh()                       # the user is reading: do not move things
                else: self._show_summary()
            else:
                self._refresh()
                if not self.card.isVisible(): self.card.set_state("pill")             # a minor problem: just the badge
        except Exception: pass

    def add_notice(self, title, text):
        """A plain notice (the 'last run ended unexpectedly' report) shown like a major problem."""
        k = "notice|" + title; self.notices[k] = {"key": k, "source": "notice", "kind": "", "message": "", "severity": _errors.MAJOR, "count": 1, "seconds": 0.0, "fixes": [], "tripped": False, "notice": title, "text": text}
        self.entries[k] = self.notices[k]; self.last_major = k; self._show_summary()

    def _show_summary(self):
        self._refresh(); self.card.set_state("summary")

    def _poll(self):
        if self.entries: self._refresh()

    def _refresh(self):
        """Fill the card from the hub's live counters (an event can be skipped by the hub's rate limit; this never misses the end of a flood)."""
        try:
            for r in self.hub.reports():
                k = "%s|%s|%s" % r.key
                if k in self.entries and "notice" not in self.entries[k]: d = r.as_dict(); d["text"] = r.text(); d["key"] = k; self.entries[k] = d
        except Exception: pass
        live = [d for k, d in self.entries.items() if k not in self.quiet]
        if not live: return
        main = self.entries.get(self.last_major) or live[-1]; title, sub = plain(main)
        self.card.set_content(len(live), title, sub, "\n\n".join(describe(d) for d in reversed(live)), "\n\n".join(d.get("text") or describe(d) for d in reversed(live)))

    def clear(self):
        self.quiet.update(self.entries); self.entries.clear(); self.notices.clear(); self.card.hide(); self.card.collapse.stop(); self.card.state = "pill"; self.poll.stop()


def last_run_report():
    """Text for the start after a crash, or None. Reads what crashlog.py captured before it wrote its own 'started' line."""
    try:
        from .. import crashlog
        if not getattr(crashlog, "PREV_CRASHED", False): return None
        tail = (getattr(crashlog, "PREV_TAIL", "") or "").strip().splitlines()[-30:]
        return ("The last MiniCut run did not end normally (crash, freeze or power-off).\nThis is the end of %s:\n\n%s\n\nSend this to whoever fixes the program."
                % (crashlog.LOG, "\n".join(tail) or "(nothing was written)"))
    except Exception: return None


def install(win):
    """Call once after the main window exists. Returns the presenter."""
    p = ErrorPresenter(win); win._error_presenter = p
    rep = last_run_report()
    if rep: QTimer.singleShot(1500, lambda: p.add_notice("The last run ended unexpectedly", rep))
    return p

"""The error hub (Patch 57): ONE place that every error of the program goes through.

Before this, errors were `print()`ed to a console nobody looks at, and a failing frame was simply tried again 60 times a second. Now:

  * report(source, exc, fix=...)   records the error, de-duplicates it (same source + same text = one entry with a counter) and tells the
                                   subscribers (the pop-up, crash.log). It never raises and never blocks.
  * a circuit breaker per source   `n` failures inside `window` seconds = the source is TRIPPED: callers ask `tripped(source)` before they try again
                                   and stop retrying. After `cooldown` seconds one trial is allowed (half-open); a failure re-trips at once,
                                   success(source) closes it.
  * note_fix(source, text)         what the program did about it ("freed 312 MB of cache", "switched to the CPU"). Only real actions are recorded.
  * install_hooks()                sys.excepthook / threading.excepthook / unraisablehook also report here.

No Qt in this file (so it is testable anywhere). The pop-up lives in shared/error_popup.py and subscribes with add_sink(); sinks run on the thread that
reported, so a sink must be fast and must hand the work to the GUI thread itself (the pop-up does that with a Qt signal).
"""
import sys, time, threading, traceback
from collections import OrderedDict, deque

MINOR, MAJOR, FATAL = "minor", "major", "fatal"
_ORDER = {MINOR: 0, MAJOR: 1, FATAL: 2}
_RESOURCE_WORDS = ("memory", "out of vram", "gpu budget", "no space", "allocation")


class Report:
    """One distinct error (source + kind + text) with how often it happened and what was done about it."""
    __slots__ = ("key", "source", "kind", "message", "severity", "count", "first", "last", "fixes", "tb", "tripped")

    def __init__(self, key, source, kind, message, severity, tb, now):
        self.key = key; self.source = source; self.kind = kind; self.message = message; self.severity = severity
        self.count = 0; self.first = now; self.last = now; self.fixes = []; self.tb = tb; self.tripped = False

    def as_dict(self):
        return {"source": self.source, "kind": self.kind, "message": self.message, "severity": self.severity, "count": self.count,
                "seconds": round(self.last - self.first, 2), "fixes": list(self.fixes), "tripped": self.tripped}

    def text(self):
        """Plain text for the pop-up's 'copy' button: what to send to whoever fixes it."""
        out = ["[%s] %s: %s" % (self.severity, self.kind, self.message), "source: %s   count: %d   over %.1f s" % (self.source, self.count, self.last - self.first)]
        out += ["done about it: " + f for f in self.fixes] or ["done about it: nothing yet"]
        if self.tb: out += ["", self.tb.rstrip()]
        return "\n".join(out)


class _Breaker:
    __slots__ = ("times", "open_until", "half", "trips")

    def __init__(self): self.times = deque(); self.open_until = 0.0; self.half = False; self.trips = 0


def classify(exc, message=None):
    """minor / major. Out-of-memory and resource errors are never minor: they are the kind that fills the machine up."""
    name = type(exc).__name__ if isinstance(exc, BaseException) else ""
    text = (message if message is not None else str(exc)).lower()
    if isinstance(exc, MemoryError) or any(w in text for w in _RESOURCE_WORDS) or "budget" in name.lower(): return MAJOR
    return MINOR


class ErrorHub:
    def __init__(self, clock=time.monotonic, trip_n=5, window=2.0, cooldown=30.0, emit_interval=0.5, history=60):
        self.clock = clock; self.trip_n = int(trip_n); self.window = float(window); self.cooldown = float(cooldown); self.emit_interval = float(emit_interval)
        self._lock = threading.RLock(); self._reports = OrderedDict(); self._breakers = {}; self._sinks = []; self._trip_cbs = {}; self._last_emit = {}
        self._history = deque(maxlen=int(history)); self._in_sink = threading.local()

    # ───────── subscribers
    def add_sink(self, fn):
        """fn(event, report): event is 'new' (first time), 'update' (counter moved, at most every emit_interval s), 'fix' (an action was recorded) or 'trip'."""
        with self._lock:
            if fn not in self._sinks: self._sinks.append(fn)

    def remove_sink(self, fn):
        with self._lock:
            if fn in self._sinks: self._sinks.remove(fn)

    def on_trip(self, source, fn):
        """fn(report) is called once each time `source` trips (on the thread that reported the failure that tripped it)."""
        with self._lock: self._trip_cbs.setdefault(source, []).append(fn)

    def _emit(self, event, rep):
        if getattr(self._in_sink, "on", False): return                      # a sink that itself reports an error must not recurse
        with self._lock: sinks = list(self._sinks)
        self._in_sink.on = True
        try:
            for fn in sinks:
                try: fn(event, rep)
                except Exception: pass
        finally: self._in_sink.on = False

    # ───────── reporting
    def report(self, source, exc, severity=None, fix=None):
        """Record one error. exc: an exception or a plain text. fix: what is being done about it right now (optional). Returns the Report; never raises."""
        try: return self._report(source, exc, severity, fix)
        except Exception: return None

    def _report(self, source, exc, severity, fix):
        now = self.clock(); is_exc = isinstance(exc, BaseException)
        kind = type(exc).__name__ if is_exc else "Error"; msg = (str(exc) if is_exc else str(exc)).strip()[:600] or kind
        key = (source, kind, msg[:200]); event = None; tripped_rep = None; cbs = ()
        with self._lock:
            rep = self._reports.get(key)
            if rep is None:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if is_exc and exc.__traceback__ is not None else ""
                sev = severity or classify(exc if is_exc else None, msg); rep = Report(key, source, kind, msg, sev, tb[-3000:], now)
                self._reports[key] = rep; event = "new"
                while len(self._reports) > 200: self._reports.popitem(last=False)
            else:
                self._reports.move_to_end(key)
                if severity and _ORDER[severity] > _ORDER[rep.severity]: rep.severity = severity; event = "update"
            rep.count += 1; rep.last = now
            if fix and fix not in rep.fixes: rep.fixes.append(fix); event = event or "fix"
            self._history.append((now, source, kind, msg[:160]))
            # the circuit breaker of this source
            b = self._breakers.setdefault(source, _Breaker()); b.times.append(now)
            while b.times and now - b.times[0] > self.window: b.times.popleft()
            if b.half or (len(b.times) >= self.trip_n and now >= b.open_until):
                b.half = False; b.open_until = now + self.cooldown; b.trips += 1; b.times.clear(); rep.tripped = True
                if _ORDER[rep.severity] < _ORDER[MAJOR]: rep.severity = MAJOR
                note = "stopped retrying for %d s (it failed %d times in a row)" % (self.cooldown, self.trip_n)
                if note not in rep.fixes: rep.fixes.append(note)
                tripped_rep = rep; cbs = tuple(self._trip_cbs.get(source, ())); event = "trip"
            if event is None and now - self._last_emit.get(key, 0.0) >= self.emit_interval: event = "update"
            if event is not None: self._last_emit[key] = now
        if event is not None: self._emit(event, rep)
        if tripped_rep is not None:
            for fn in cbs:
                try: fn(tripped_rep)
                except Exception: pass
        return rep

    def note_fix(self, source, text):
        """Record an action taken for the latest error of `source` (and tell the sinks, so the pop-up shows it)."""
        try:
            with self._lock:
                rep = next((r for r in reversed(self._reports.values()) if r.source == source), None)
                if rep is None or text in rep.fixes: return
                rep.fixes.append(str(text))
            self._emit("fix", rep)
        except Exception: pass

    # ───────── the circuit breaker
    def tripped(self, source):
        """True while `source` must not be retried. After the cooldown it answers False once (one trial): if that trial fails the breaker re-trips at once."""
        with self._lock:
            b = self._breakers.get(source)
            if b is None or b.open_until <= 0.0: return False
            if self.clock() < b.open_until: return True
            b.open_until = 0.0; b.half = True; return False

    def success(self, source):
        """A try worked: closes a half-open breaker and forgets the recent failures."""
        with self._lock:
            b = self._breakers.get(source)
            if b is not None: b.half = False; b.times.clear()

    def reset(self, source=None):
        with self._lock:
            for s in ([source] if source else list(self._breakers)):
                b = self._breakers.get(s)
                if b is not None: b.times.clear(); b.open_until = 0.0; b.half = False

    # ───────── reading
    def snapshot(self):
        with self._lock: return [r.as_dict() for r in self._reports.values()]

    def reports(self):
        """The live Report objects (oldest first). Read-only use: a pop-up that is open re-reads the counters from here, so the last update of a flood is never lost."""
        with self._lock: return list(self._reports.values())

    def latest(self, source=None):
        with self._lock:
            for r in reversed(self._reports.values()):
                if source is None or r.source == source: return r
        return None

    def clear(self):
        with self._lock: self._reports.clear(); self._breakers.clear(); self._last_emit.clear(); self._history.clear()

    # ───────── hooks for what escapes every try / except
    def install_hooks(self):
        prev_ex = sys.excepthook; prev_th = getattr(threading, "excepthook", None); prev_un = getattr(sys, "unraisablehook", None)

        def _ex(et, ev, tb):
            if not issubclass(et, (KeyboardInterrupt, SystemExit)): self.report("uncaught", ev, severity=MAJOR)
            try: prev_ex(et, ev, tb)
            except Exception: pass
        def _th(a):
            if a.exc_type is not SystemExit: self.report("thread:" + str(getattr(a.thread, "name", "?")), a.exc_value, severity=MAJOR)
            try:
                if prev_th is not None: prev_th(a)
            except Exception: pass
        def _un(u):
            self.report("unraisable", u.exc_value if u.exc_value is not None else "unraisable error", severity=MINOR)
            try:
                if prev_un is not None: prev_un(u)
            except Exception: pass
        sys.excepthook = _ex
        try: threading.excepthook = _th
        except Exception: pass
        try: sys.unraisablehook = _un
        except Exception: pass


HUB = ErrorHub()


def report(source, exc, severity=None, fix=None): return HUB.report(source, exc, severity, fix)
def note_fix(source, text): HUB.note_fix(source, text)
def tripped(source): return HUB.tripped(source)
def success(source): HUB.success(source)

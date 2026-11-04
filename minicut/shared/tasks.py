"""Background work in progress (proxies, audio effects, export...). The progress ring at the bottom right shows it, and the
tasks window (click the ring) lists it. A task that can be stopped has a cancel_fn; Task.cancel() calls it."""
import threading, time


class Task:
    def __init__(self, center, kind, title):
        self.center = center; self.kind = kind; self.title = title
        self.total = None; self.done = 0; self.detail = ""; self.t0 = time.monotonic()
        self.cancel_fn = None; self.cancelled = False
    def fraction(self):
        if not self.total: return None
        return max(0.0, min(1.0, self.done / float(self.total)))
    def can_cancel(self): return self.cancel_fn is not None and not self.cancelled
    def cancel(self):
        """Ask the task to stop. The worker notices the flag (or its cancel_fn does the stopping) and finishes the task."""
        self.cancelled = True
        fn = self.cancel_fn
        if fn is not None:
            try: fn()
            except Exception as ex: print("[tasks] cancel failed:", ex)
    def eta(self):
        f = self.fraction()
        if f is None or f <= 0.02: return None
        el = time.monotonic() - self.t0
        return max(0.0, el / f - el)
    def finish(self):
        self.center._remove(self)


class TaskCenter:
    def __init__(self):
        self.lock = threading.Lock(); self.tasks = []
    def start(self, kind, title):
        t = Task(self, kind, title)
        with self.lock: self.tasks.append(t)
        return t
    def _remove(self, t):
        with self.lock:
            if t in self.tasks: self.tasks.remove(t)
    def snapshot(self):
        with self.lock: return list(self.tasks)


TASKS = TaskCenter()

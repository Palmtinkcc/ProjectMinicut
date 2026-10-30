"""Background work in progress (proxies, audio effects, export...). The progress ring at the bottom right shows it."""
import threading, time


class Task:
    def __init__(self, center, kind, title):
        self.center = center; self.kind = kind; self.title = title
        self.total = None; self.done = 0; self.detail = ""; self.t0 = time.monotonic()
    def fraction(self):
        if not self.total: return None
        return max(0.0, min(1.0, self.done / float(self.total)))
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

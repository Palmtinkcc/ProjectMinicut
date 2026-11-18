"""The last-resort ladder when video memory keeps running out (Patch 58). No Qt: the GUI side hands in callbacks (shared/degrade_qt.py), so it is testable with a fake clock.

The ladder, from the gentlest step:
  1. the engine gives back its idle caches and pools (they go back to RAM; they are re-uploaded when needed)   - done in meshgl._give_back
  2. objects that nobody references any more (leaks) are released                                            - done in gpuledger.check
  3. LOW PREVIEW: the preview is forced to 25 % (a quarter of the pixels in every render target). The user's own setting is NOT changed;
     it only caps it while the pressure lasts. Export is never affected.                                      - this file, level 1
  4. CPU: the drawing moves to the CPU if the machine has the free RAM for it, else the preview stops          - this file, level 2

pressure(why, severe) is called by the engine each time step 1/2 had to run (or the driver said out of memory: severe).
Level 1 starts when `need` pressure events fall inside `window` seconds, or at once when severe. Level 2 starts the same way, but only `settle` seconds after level 1
began (so level 1 has had a chance). tick() (called every few seconds) climbs back down from level 1 after `calm` quiet seconds; the wait doubles each time the pressure
comes back (up to 10 minutes), so it never flips between sharp and blurry. Level 2 (CPU) is not undone until the program is restarted.
Every step is told to the error hub (the corner card): what is being done, in plain words.
"""
import threading, time
from . import errors as _errors

NORMAL, LOW_PREVIEW, CPU = 0, 1, 2
SOURCE = "gpu.pressure"
MESSAGE = "GPU memory is nearly full"


class Degrade:
    def __init__(self, apply_quality=None, cpu_fallback=None, stop_preview=None, ram_ok=None, hub=None, clock=time.monotonic,
                 force_quality=0.25, need=3, window=10.0, settle=5.0, calm=60.0, calm_max=600.0):
        self.apply_quality = apply_quality or (lambda q: None); self.cpu_fallback = cpu_fallback or (lambda: None); self.stop_preview = stop_preview or (lambda: None)
        self.ram_ok = ram_ok or (lambda: False); self.hub = hub or _errors.HUB; self.clock = clock
        self.force_quality = float(force_quality); self.need = int(need); self.window = float(window); self.settle = float(settle)
        self.calm = float(calm); self.calm_now = float(calm); self.calm_max = float(calm_max)
        self.level = NORMAL; self._forced = None; self._times = []; self._t_level = 0.0; self._t_event = 0.0; self.stopped = False
        self._lock = threading.RLock()

    # ── read by the preview
    def forced_quality(self):
        """None, or the most the preview may use now (a fraction 0..1)."""
        return self._forced

    # ── called by the engine
    def pressure(self, why="", severe=False):
        now = self.clock(); todo = None
        with self._lock:
            self._t_event = now; self._times.append(now)
            self._times = [t for t in self._times if now - t <= self.window]
            hot = severe or len(self._times) >= self.need
            if hot and self.level == NORMAL:
                self.level = LOW_PREVIEW; self._t_level = now; self._forced = self.force_quality; self._times = []; todo = "low"
            elif hot and self.level == LOW_PREVIEW and now - self._t_level >= self.settle:
                self.level = CPU; self._t_level = now; self._times = []; todo = "cpu"
        if todo == "low": self._to_low_preview(why)
        elif todo == "cpu": self._to_cpu(why)

    def _to_low_preview(self, why):
        pct = int(round(self.force_quality * 100))
        self.hub.report(SOURCE, MESSAGE, severity=_errors.MAJOR, fix="the preview is shown at %d%% for now (your own setting is kept; export is not affected)" % pct)
        try: self.apply_quality(self.force_quality)
        except Exception as ex: self.hub.report(SOURCE, ex)

    def _to_cpu(self, why):
        try: ok = bool(self.ram_ok())
        except Exception: ok = False
        if ok:
            self.hub.report(SOURCE, MESSAGE, severity=_errors.MAJOR, fix="drawing moved to the CPU (there is enough free RAM); it stays there until MiniCut is restarted")
            try: self.cpu_fallback()
            except Exception as ex: self.hub.report(SOURCE, ex)
        else:
            self.stopped = True
            self.hub.report(SOURCE, MESSAGE, severity=_errors.MAJOR, fix="the preview was stopped: there is not enough free RAM to draw on the CPU instead. Close other programs, then press play")
            try: self.stop_preview()
            except Exception as ex: self.hub.report(SOURCE, ex)

    # ── called every few seconds by the GUI
    def tick(self):
        """Climb back from level 1 after `calm` quiet seconds. Returns True when it did."""
        now = self.clock()
        with self._lock:
            if self.level != LOW_PREVIEW or now - self._t_event < self.calm_now: return False
            self.level = NORMAL; self._forced = None; self._times = []; self.calm_now = min(self.calm_max, self.calm_now * 2.0)
        self.hub.note_fix(SOURCE, "no memory trouble for a while: the preview is back to your own quality setting")
        try: self.apply_quality(None)
        except Exception as ex: self.hub.report(SOURCE, ex)
        return True

    def state(self):
        return {"level": self.level, "forced_quality": self._forced, "next_try_after_s": self.calm_now, "stopped": self.stopped}


# ── the program-wide instance (None in tools / tests / export workers: then every call below does nothing)
INSTANCE = None


def install(d):
    global INSTANCE
    INSTANCE = d; return d


def pressure(why="", severe=False):
    d = INSTANCE
    if d is not None:
        try: d.pressure(why, severe)
        except Exception: pass


def forced_quality():
    d = INSTANCE
    return d.forced_quality() if d is not None else None

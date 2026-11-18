"""Qt side of minicut/degrade.py (Patch 58): the ladder is told about pressure on any thread; what it asks for happens on the GUI thread (queued signals)."""
from PySide6.QtCore import QObject, Signal, QTimer, Qt

from .. import degrade as _dg
from ..render import gpucap as _gpucap


class DegradeBridge(QObject):
    redraw = Signal()
    stop = Signal()

    def __init__(self, win):
        super().__init__(win); self.win = win
        self.redraw.connect(self._redraw, Qt.QueuedConnection); self.stop.connect(self._stop, Qt.QueuedConnection)
        self.d = _dg.Degrade(apply_quality=lambda q: self.redraw.emit(), cpu_fallback=self._cpu, stop_preview=lambda: self.stop.emit(),
                             ram_ok=lambda: _gpucap.ram_ok(_gpucap.system_ram()[1]))
        _dg.install(self.d)
        self.timer = QTimer(self); self.timer.setInterval(5000); self.timer.timeout.connect(self.d.tick); self.timer.start()

    def _cpu(self):
        from ..render import meshgl
        meshgl.fail("memory pressure: the drawing moved to the CPU"); self.redraw.emit()

    def _redraw(self):
        try: self.win.request_render()
        except Exception: pass

    def _stop(self):
        try:
            if getattr(self.win, "playing", False): self.win.stop_play()
        except Exception: pass


def install(win):
    b = DegradeBridge(win); win._degrade_bridge = b; return b

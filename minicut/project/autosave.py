"""Auto save: every few minutes (Settings > General > Auto save) the open project is saved over its own file,
exactly like Ctrl+S, but only when something changed since the last save. Nothing is shown unless it fails."""
import hashlib, json
from ..shared.deps import *


class AutosaveMixin:
    def _proj_sig(self):
        """Fingerprint of the project's content (to see whether anything changed since the last save)."""
        return hashlib.md5(json.dumps(self.proj.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def autosave_apply(self):
        """(Re)start the timer from the settings. Called at start and after Settings is closed with OK."""
        tm = getattr(self, "_autosave_timer", None)
        if tm is None: tm = self._autosave_timer = QTimer(self); tm.timeout.connect(self.autosave_tick)
        tm.stop()
        if self.settings["autosave"]: tm.start(max(1, int(self.settings["autosave_min"])) * 60000)

    def autosave_tick(self):
        if not self.proj or self.stack.currentWidget() is not self.editor or getattr(self, "_rec", None): return
        try: sig = self._proj_sig()
        except Exception: return
        if sig == getattr(self, "_saved_sig", None): return        # nothing changed
        self._quiet_save = True
        try: self.save_project()
        finally: self._quiet_save = False

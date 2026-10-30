"""Recording your voice with a live waveform on the timeline (like CapCut).

Record: the take is drawn on an audio track while you speak, the playhead moves along (the picture follows silently,
so you can watch the video while you talk), and Stop turns it into a normal audio clip. The microphone is chosen in
Settings > General > Recording.
"""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..render.media import AUDIO
from ..render.recorder import *


class RecordMixin:
    def _rec_pick_track(self, start):
        """(track, created): the first unlocked audio track that is free from `start` on, else a new audio track."""
        P = self.proj
        for tr in P.tracks:
            if tr["kind"] == "audio" and not tr.get("locked") and not any(c["track"] == tr["id"] and c["start"] + c["dur"] > start - 1e-6 for c in P.clips):
                return tr, False
        return P.add_track("audio"), True

    def _rec_button(self, on):
        btn = getattr(getattr(self, "timeline_panel", None), "rec_btn", None)
        if btn is not None: btn.label = "Stop" if on else "Record"; btn.setIconName("stop" if on else "mic"); btn.update()

    def toggle_record(self):
        """Record your voice: click to start, click again to stop. The take becomes an audio clip where it started."""
        if not self.proj: return
        if getattr(self, "recorder", None) is None: self.recorder = VoiceRecorder()
        rec = self.recorder
        if rec.active(): self.finish_record(); return
        if getattr(self, "_mprev", None) is not None: self.exit_media_preview(clear_selection=True)
        if self.playing: self.stop_play()
        try: rec.start(self.settings["asset_folder"], self.settings["audio_input"])
        except Exception as ex:
            QMessageBox.warning(self, "MiniCut", "Could not start recording:\n%s" % ex); return
        start = self.t; tr, created = self._rec_pick_track(start)
        self._rec = {"start": start, "track": tr["id"], "created": created, "n": 0}
        tm = getattr(self, "_rec_timer", None)
        if tm is None: tm = self._rec_timer = QTimer(self); tm.setInterval(33); tm.timeout.connect(self._rec_tick)
        tm.start(); self._rec_button(True)
        if created and hasattr(self, "timeline"): self.timeline.update_scroll()
        if rec.fallback and hasattr(self, "toast"): self.toast.show_msg("The chosen microphone was not found. Using the system default: " + rec.device_name, 3500)
        self._rec_tick()

    def _rec_tick(self):
        r = getattr(self, "_rec", None)
        if r is None: return
        self.t = r["start"] + self.recorder.seconds(); r["n"] += 1
        tl = getattr(self, "timeline", None)
        if tl is not None:
            tl.update_scroll(); tl.follow(); tl.update()
        if hasattr(self, "preview"): self.preview.time.setText(fmt_time(self.t, self.proj.fps) + " / " + fmt_time(max(self.proj.duration(), self.t), self.proj.fps))
        if r["n"] % 3 == 0: self.request_render()     # the picture follows the playhead (about 10 times a second)

    def finish_record(self, discard=False):
        """Stop recording (if it is running) and put the take on the timeline."""
        r = getattr(self, "_rec", None); rec = getattr(self, "recorder", None)
        if r is None or rec is None or not rec.active(): self._rec = None; return
        tm = getattr(self, "_rec_timer", None)
        if tm is not None: tm.stop()
        peaks = rec.peaks_view().copy()
        if discard: rec.discard(); path = None
        else: path = rec.stop()
        self._rec = None; self._rec_button(False)
        if path:
            AUDIO.peaks[path] = peaks              # the timeline keeps showing the waveform it drew while recording
            self.add_files([path], r["start"], r["track"])
        else:
            tr = self.proj.track(r["track"]) if self.proj else None
            if r["created"] and tr is not None and not any(c["track"] == tr["id"] for c in self.proj.clips): self.proj.tracks.remove(tr)
            if hasattr(self, "toast") and not discard: self.toast.show_msg("The recording was too short and was not kept.", 2500)
            self.on_changed()
        if hasattr(self, "timeline"): self.timeline.update_scroll(); self.timeline.update()

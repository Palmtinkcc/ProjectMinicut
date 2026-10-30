"""Playback and preview control of the main window (seek / play / tick / request a preview frame)."""
from ..shared.deps import *
from ..shared.icons import *
from .renderer import *


def _follow_playhead(app):
    tl = getattr(app, "timeline", None)
    if not tl or tl.drag or not app.playing: return
    x = tl.t2x(app.t); vw = tl.width()
    if x > vw - 30 or x < tl.HEAD:
        tl.hbar.setValue(max(0, int(app.t * tl.pps - (vw - tl.HEAD) * 0.1)))


class PlaybackMixin:
    """Playback clock and preview rendering requests."""
    def seek(self, t):
        if self._mprev is not None: self.exit_media_preview(clear_selection=True)    # the timeline is used again: leave the media preview
        self.t = max(0, min(float(t), self.proj.duration() if self.proj else 0))
        if self.playing and self.proj:
            tl = getattr(self, "timeline", None)
            if tl is not None and tl.drag: self.audio.stop(); self.audio_seek_timer.start()   # กำลังลาก: รอหยุดก่อน
            else: self.audio.start(self.proj, self.t)                                          # คลิกครั้งเดียว: ตามทันที
        self._adapt_hold = time.monotonic() + 0.8; self._ema = None   # let the first frames after a seek settle
        self._last_tick = time.monotonic()
        self.request_render(); self.refresh_ui()
    def _restart_audio_after_seek(self):
        if self.playing and self.proj:
            self.audio.start(self.proj, self.t, min(90, max(0.1, self.proj.duration()-self.t)))
            self._last_tick = time.monotonic()
    def step(self,d):
        if self._mprev is not None: self.media_step(d); return
        self.seek(self.t+d/(self.proj.fps if self.proj else 30))
    def toggle_play(self):
        if not self.proj:return
        if getattr(self,'_rec',None): return                           # recording: the playhead follows the microphone
        if self._mprev is not None: self.media_toggle_play(); return    # media preview: Space plays the media
        if self.playing:self.stop_play()
        else:self.playing=True; self._last_tick=time.monotonic(); self.timer.start(); self.audio.start(self.proj,self.t,min(90,max(0.1,self.proj.duration()-self.t)))
        if hasattr(self,'preview'):set_play_icon(self.preview.play_btn, self.playing)
    def stop_play(self):self.playing=False; self.timer.stop(); self.audio.stop()
    def tick(self):
        if not self.proj: return
        now = time.monotonic(); tl = getattr(self, "timeline", None)
        if tl is not None and tl.drag and tl.drag.get("mode") == "scrub":
            self._last_tick = now; return
        # Hold the clock while the picture is behind (e.g. a clip whose proxy is not ready yet): smooth, no skipping.
        w = getattr(self, "_rworker", None); done = getattr(w, "done_t", None)
        if self.playing and done is not None and self.t - done > 0.4:
            if not getattr(self, "_stalled", False): self._stalled = True; self.audio.stop()
            self._last_tick = now; self.request_render(); self.refresh_ui(); return
        if getattr(self, "_stalled", False):
            self._stalled = False; self.audio.start(self.proj, self.t, min(90, max(0.1, self.proj.duration() - self.t)))
        if self.audio.running: self.t = self.audio.clock()
        else: self.t += min(.1, now - self._last_tick)
        self._last_tick = now
        if self.t >= self.proj.duration(): self.seek(0); return
        if os.environ.get("MINICUT_PERF"):
            pf = self.__dict__.setdefault("_perf", [now, 0])
            pf[1] += 1
            if now - pf[0] >= 1.0:
                print("[perf] %d ticks/s, last render %.1f ms" % (pf[1], getattr(getattr(self, "_rworker", None), "last_ms", 0.0)))
                pf[0] = now; pf[1] = 0
        self.request_render(); self.refresh_ui(); _follow_playhead(self)
    def _adaptive_scale(self, w):
        """Scale 0.5..1.0 for the preview while playing. Uses a smoothed render time, ignores the first frames
        after a seek (they are slow because the video is opened / decoded from a keyframe), and never goes below half."""
        budget = self.frame_ms(); now = time.monotonic()
        if now < getattr(self, "_adapt_hold", 0.0): return getattr(self, "_adapt", 1.0)
        ms = getattr(w, "last_ms", 0.0); ema = getattr(self, "_ema", None)
        ema = ms if ema is None else ema * 0.7 + ms * 0.3; self._ema = ema
        a = getattr(self, "_adapt", 1.0)
        if ema > budget * 1.15: a = max(0.5, a - 0.1)
        elif ema < budget * 0.6: a = min(1.0, a + 0.05)
        self._adapt = a; return a
    def preview_fast_for(self, sec):
        """While an effect slider is moving, draw the preview small so the change shows at once."""
        self._fast_until = time.monotonic() + sec
        # Patch 38: when the slider stops, ask for the full-quality frame once. The small picture stays on screen until it
        # arrives (the viewport only swaps pictures), so there is no flicker or double picture.
        tm = getattr(self, "_fast_timer", None)
        if tm is None:
            tm = QTimer(self); tm.setSingleShot(True); tm.timeout.connect(self._fast_done); self._fast_timer = tm
        tm.start(int(sec * 1000) + 60)
    def _fast_done(self):
        if time.monotonic() >= getattr(self, "_fast_until", 0.0): self.request_render()
    def request_render(self):
        if not self.proj or not hasattr(self, "viewport"): return
        q = self.settings["preview_quality"]
        if self.settings["fit_viewport"]:        # never draw more pixels than the preview shows
            try: fit = self.viewport.display_scale()
            except Exception: fit = 1.0
            q = min(q, max(0.1, min(1.0, math.ceil(fit * 20) / 20.0)))
        w = getattr(self, "_rworker", None)
        # Adaptive preview replaces the fixed "half while playing" step, so the two never stack into a very blurry image.
        adaptive = self.playing and self.settings["adaptive_preview"] and w is not None
        if self.playing and self.settings["play_reduce"] and not adaptive: q *= .5
        if adaptive: q *= self._adaptive_scale(w)
        else: self._adapt = 1.0; self._ema = None
        fast_now = time.monotonic() < getattr(self, "_fast_until", 0.0)
        if fast_now: q = min(q, 0.25)
        if w is None:
            w = RenderWorker(self.renderer); w.ready.connect(self._on_frame, Qt.QueuedConnection); w.start()
            QApplication.instance().aboutToQuit.connect(w.stop); self._rworker = w
        self.renderer.live_play = bool(self.playing or fast_now)       # Patch 40: effects may use fewer pixels while it moves
        w.submit(self.proj, self.t, q, fast_now or self.settings["preview_interp"] == "fast")
    def toggle_play_shortcut(self):self.toggle_play()
    def _on_frame(self, img):
        if hasattr(self, "viewport"): self.viewport.set_frame(img)

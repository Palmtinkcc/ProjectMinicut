"""Media-pool preview, like CapCut.

Click a media card once (do not drag it) and the Player shows that file instead of the edit preview:
  * the media card itself is the progress bar: a white vertical line shows where the file is, click / drag on the card to move it
  * Play / Pause, previous / next frame, go to start / end (the normal shortcuts and the Player buttons) work on the media
  * it stops when no media card is selected any more, or when you go back to editing (timeline click, adding a clip ...)
Works for video, GIF and audio files. A single picture has nothing to play, so it is not previewed.
"""
from ..shared.deps import *
from ..shared.core import *
from ..shared.icons import *
from ..render.media import *
from ..render.audio import *

PREVIEW_KINDS = ("video", "gif", "audio")
_ZOMBIES = set()          # decoder threads that were asked to stop and are still finishing (a running QThread must not be freed)


class PreviewDecoder(QThread):
    """Decodes the previewed file's pictures off the GUI thread. Only the newest request is served, so a slow
    disk or a big video drops pictures instead of falling behind (the sound / clock keeps the time)."""
    ready = Signal(object)

    def __init__(self, path, kind):
        super().__init__(); self.path = path; self.kind = kind; self.cv = threading.Condition(); self.req = None
        self.alive = True; self.fps = 30.0

    def submit(self, t, max_w, max_h):
        with self.cv: self.req = (float(t), float(max_w), float(max_h)); self.cv.notify()

    def stop(self):
        with self.cv: self.alive = False; self.cv.notify()

    def _open(self):
        if self.kind == "video":
            src = VideoSource(self.path, False); self.fps = float(src.fps or 30.0); return src
        return GifSource(self.path)

    @staticmethod
    def _qimage(fr, fmt):
        fr = np.ascontiguousarray(fr); h, w = fr.shape[:2]
        img = QImage(fr.data, w, h, fr.strides[0], fmt); img._keep = fr; return img

    def run(self):
        try: src = self._open()
        except Exception as ex:
            print("media preview:", ex); return
        try:
            while True:
                with self.cv:
                    while self.req is None and self.alive: self.cv.wait()
                    if not self.alive: break
                    (t, mw, mh), self.req = self.req, None
                try:
                    if self.kind == "video": fr = src.raw_frame(t); fmt = QImage.Format_BGR888
                    else: fr = src.frame(t, 1.0); fmt = QImage.Format_ARGB32           # GIF frames are BGRA in memory
                    h, w = fr.shape[:2]; s = min(1.0, mw / max(1, w), mh / max(1, h))
                    if s < 0.98: fr = cv2.resize(fr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
                    if self.alive: self.ready.emit(self._qimage(fr, fmt))
                except Exception as ex: print("media preview frame:", ex)
        finally:
            try:
                if hasattr(src, "close"): src.close()
            except Exception: pass


class MediaPreviewMixin:
    """Methods of the main window that drive the media-pool preview. State: self._mprev (None, or a dict)."""

    # ---------------------------------------------------------------- helpers
    def _mprev_duration(self, path, kind):
        key = ("d", path); d = self.thumbs.cache.get(key)
        if not d:
            k, d = probe(path); d = float(d or 0.0)
            if d > 0: self.thumbs.cache[key] = d
        return float(d or 0.0)

    def _mprev_timer_get(self):
        t = getattr(self, "_mprev_timer", None)
        if t is None: t = self._mprev_timer = QTimer(self); t.timeout.connect(self._mprev_tick)
        return t

    def _mprev_shim(self, m):
        if m.get("shim") is None:
            shim = copy.copy(self.proj); clip = make_clip("audio", m["path"], "mprev", 0.0, m["dur"], m["dur"])
            shim.clips = [clip]; shim.tracks = [{"id": "mprev", "kind": "audio", "name": "mprev", "muted": False, "locked": False, "hidden": False}]
            m["shim"] = shim
        return m["shim"]

    def _mprev_fps(self, m):
        dec = m.get("dec")
        return float(getattr(dec, "fps", 0) or m.get("fps") or 30.0) if dec is not None and m["kind"] == "video" else float(m.get("fps") or 30.0)

    def _mprev_clock(self, m):
        if not m["playing"]: return m["t"]
        t = self.audio.clock() if m["audio_on"] else m["t0"] + (time.monotonic() - m["wall0"])
        return max(0.0, min(m["dur"], t))

    def _mprev_request(self, m):
        dec = m.get("dec")
        if dec is None or not hasattr(self, "viewport"): return
        vp = self.viewport; dpr = vp.devicePixelRatioF()
        dec.submit(min(m["t"], max(0.0, m["dur"] - 0.5 / self._mprev_fps(m))), max(64, vp.width() * dpr), max(64, vp.height() * dpr))

    def _mprev_ui(self):
        """Time readout and play icon of the Player; repaint of the card (the white line)."""
        m = self._mprev
        if m is None or not hasattr(self, "preview"): return
        fps = self._mprev_fps(m)
        self.preview.time.setText(fmt_time(m["t"], fps) + " / " + fmt_time(m["dur"], fps))
        want = "pause" if m["playing"] else "play"
        if getattr(self, "_play_icon", None) != want: self.preview.play_btn.setIcon(app_icon(want)); self._play_icon = want
        if hasattr(self, "media"): self.media.list.repaint_path(m["path"])

    def _mprev_after_move(self):
        m = self._mprev
        if m is None: return
        m["frac"] = (m["t"] / m["dur"]) if m["dur"] > 0 else 0.0
        self._mprev_request(m); self._mprev_ui()

    def _mprev_frame(self, img):
        if self._mprev is not None and hasattr(self, "viewport"): self.viewport.set_media_frame(img)

    # ---------------------------------------------------------------- enter / leave
    def enter_media_preview(self, path, kind, frac=0.0):
        """Show a media-pool file in the Player (paused, at the clicked position). Returns False when it cannot be previewed."""
        if kind not in PREVIEW_KINDS or not self.proj or not os.path.isfile(path) or getattr(self, "_rec", None):
            if kind not in PREVIEW_KINDS: self.exit_media_preview()
            return False
        m = self._mprev
        if m is not None and m["path"] == path: self._mprev_seek_frac(frac); return True
        self._mprev_close()
        if self.playing: self.stop_play()
        dur = self._mprev_duration(path, kind)
        if dur <= 0: return False
        m = {"path": path, "kind": kind, "frac": 0.0, "t": 0.0, "dur": dur, "playing": False, "fps": float(self.proj.fps),
             "dec": None, "shim": None, "audio_on": False, "t0": 0.0, "wall0": 0.0, "was_playing": False}
        if kind in ("video", "gif"):
            dec = PreviewDecoder(path, kind); dec.ready.connect(self._mprev_frame, Qt.QueuedConnection); m["dec"] = dec; dec.start()
        if kind in ("video", "audio"): self.thumbs.wave(path)           # decode the sound now, so Play starts at once
        try: self.thumbs.updated.connect(self._mprev_audio_check)
        except Exception: pass
        self._mprev = m
        if hasattr(self, "viewport"): self.viewport.mimg = None
        self._mprev_seek_frac(frac)
        return True

    def _mprev_close(self):
        m = self._mprev
        if m is None: return
        self._mprev = None
        self._mprev_timer_get().stop()
        if m["playing"] or m["audio_on"]: self.audio.stop()
        try: self.thumbs.updated.disconnect(self._mprev_audio_check)
        except Exception: pass
        dec = m.get("dec")
        if dec is not None:
            try: dec.ready.disconnect(self._mprev_frame)
            except Exception: pass
            dec.stop()
            if not dec.isFinished():
                _ZOMBIES.add(dec); dec.finished.connect(lambda d=dec: _ZOMBIES.discard(d))
        if hasattr(self, "viewport"): self.viewport.mimg = None
        if hasattr(self, "media"): self.media.list.repaint_path(m["path"])

    def exit_media_preview(self, clear_selection=False):
        """Back to the edit preview. clear_selection also un-selects the media card."""
        had = self._mprev is not None
        self._mprev_close()
        if clear_selection and hasattr(self, "media"):
            lst = self.media.list; lst.blockSignals(True); lst.clearSelection(); lst.setCurrentRow(-1); lst.blockSignals(False); lst.viewport().update()
        if had:
            if hasattr(self, "viewport"): self.viewport.update()
            if self.proj: self.request_render(); self.refresh_ui()

    def media_click(self, path, kind, frac=0.0):
        """A single click on a media card (not a drag)."""
        if kind in PREVIEW_KINDS: self.enter_media_preview(path, kind, frac)
        else: self.exit_media_preview()

    # ---------------------------------------------------------------- playing
    def media_play(self):
        m = self._mprev
        if m is None or m["playing"]: return
        if m["t"] >= m["dur"] - 0.02: self._mprev_set_t(0.0)
        m["playing"] = True; m["t0"] = m["t"]; m["wall0"] = time.monotonic(); m["audio_on"] = False
        self._mprev_audio_start(m, m["t"])
        tm = self._mprev_timer_get(); tm.setInterval(self.frame_ms()); tm.start(); self._mprev_ui()

    def media_pause(self):
        m = self._mprev
        if m is None or not m["playing"]: return
        m["t"] = self._mprev_clock(m); m["playing"] = False; self._mprev_timer_get().stop()
        if m["audio_on"]: self.audio.stop()
        m["audio_on"] = False; self._mprev_after_move()

    def media_toggle_play(self):
        if self._mprev is None: return
        self.media_pause() if self._mprev["playing"] else self.media_play()

    def _mprev_audio_start(self, m, t):
        if m["kind"] not in ("video", "audio"): return
        if m["path"] not in AUDIO.peaks:
            self.thumbs.wave(m["path"]); return         # still decoding in the background: the sound joins in when ready
        self.audio.start(self._mprev_shim(m), t); m["audio_on"] = True

    def _mprev_audio_check(self):
        m = self._mprev
        if m is not None and m["playing"] and not m["audio_on"] and m["path"] in AUDIO.peaks:
            self._mprev_audio_start(m, self._mprev_clock(m))

    def _mprev_tick(self):
        m = self._mprev
        if m is None or not m["playing"]: self._mprev_timer_get().stop(); return
        t = self._mprev_clock(m)
        if t >= m["dur"] - 1e-3:
            self.media_pause(); self._mprev_set_t(m["dur"]); return          # reached the end: stay on the last picture
        m["t"] = t; self._mprev_after_move()

    # ---------------------------------------------------------------- moving
    def _mprev_set_t(self, t):
        m = self._mprev
        if m is None: return
        m["t"] = max(0.0, min(m["dur"], float(t)))
        if m["playing"]:
            m["t0"] = m["t"]; m["wall0"] = time.monotonic()
            if m["audio_on"]: self.audio.start(self._mprev_shim(m), m["t"])
        self._mprev_after_move()

    def _mprev_seek_frac(self, frac):
        m = self._mprev
        if m is not None: self._mprev_set_t(max(0.0, min(1.0, float(frac))) * m["dur"])

    def media_scrub_begin(self, frac):
        """Mouse down on the media card: it is the progress bar. Playing is paused while the line is dragged."""
        m = self._mprev
        if m is None: return
        m["was_playing"] = m["playing"]
        if m["playing"]: self.media_pause()
        self._mprev_seek_frac(frac)

    def media_scrub(self, frac): self._mprev_seek_frac(frac)

    def media_scrub_end(self):
        m = self._mprev
        if m is not None and m["was_playing"]: m["was_playing"] = False; self.media_play()

    def media_step(self, d):
        m = self._mprev
        if m is None: return
        self.media_pause(); self._mprev_set_t(m["t"] + d / self._mprev_fps(m))

    def media_go(self, end):
        m = self._mprev
        if m is None: return
        self.media_pause(); self._mprev_set_t(m["dur"] if end else 0.0)

    def sc_guard(self, fn):
        """Editing shortcuts (split, delete ...) do nothing while a media file is being previewed: the timeline is not on screen."""
        def run(*a):
            if self._mprev is not None: return
            return fn()
        return run

    def sc_go(self, end):
        if self._mprev is not None: self.media_go(end); return
        self.seek((self.proj.duration() if self.proj else 0) if end else 0)

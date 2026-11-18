"""Export dialog and the background export worker."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.widgets import *
from ..shared.ui import *
from .media import *
from .audio import *
from .renderer import *
from ..shared.hwaccel import *
from ..shared.tasks import TASKS
from ..shared.optimize import X264_PRESET, SVT_PRESET, AOM_CPU_USED, export_crf
from . import export_par as XP
from .perf import render_threads as _render_threads
import functools, queue, threading


def letterbox(fr, ow, oh):
    h, w = fr.shape[:2]; s = min(ow / w, oh / h)
    nw, nh = min(ow, max(1, int(round(w * s)))), min(oh, max(1, int(round(h * s))))
    if (nw, nh) != (w, h): fr = cv2.resize(fr, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    out = np.zeros((oh, ow, 3), np.uint8); y, x = (oh - nh) // 2, (ow - nw) // 2
    out[y:y + nh, x:x + nw] = fr; return out


FORMATS = OrderedDict([("mp4", ("MP4 · H.264", ".mp4")), ("mp4_265", ("MP4 · H.265 / HEVC", ".mp4")), ("av1", ("AV1 · AV1 (GPU if this PC can, else CPU)", ".mp4")), ("mov", ("MOV · ProRes 422 HQ", ".mov")),
                       ("webm", ("WebM · VP9", ".webm")), ("mkv", ("MKV · H.264", ".mkv")), ("gif", ("GIF · animated", ".gif")),
                       ("png", ("PNG sequence", "")), ("mp3", ("MP3 · audio only", ".mp3")), ("wav", ("WAV · audio only", ".wav"))])


from . import ramgov as _RAM


class ExportWorker(QThread):
    """One export, running in its own thread. It can be cancelled at any moment: the encoder is stopped, the half-written
    file is deleted. States: queued -> running -> done / failed / cancelled."""
    progress = Signal(float)
    done_sig = Signal(bool, str)
    finished_job = Signal(object, bool, str)       # (this worker, ok, message): delivered to the manager in the main thread
    def __init__(self, pd, opts, task=None):
        super().__init__(); self.pd = pd; self.o = opts; self.cancel = False; self._proc = None; self._task = task
        self.thumb = None; self._thumb_t = 0.0; self._procs = []; self._plock = threading.Lock()      # thumb: (small BGR picture, frame, total) of the frame being built, for the Tasks window
        self.state = "queued"; self.msg = ""; self.out = opts["path"]; self.title = os.path.basename(opts["path"].rstrip("/\\")) or opts["path"]
    def request_cancel(self):
        """Stop as soon as possible: set the flag, and kill the encoder so a blocked write ends at once."""
        self.cancel = True
        with self._plock: ps = list(self._procs) + [self._proc]
        for p in ps:
            if p is not None and p.poll() is None:
                try: p.kill()
                except Exception: pass
    def _thumb(self, fr, i, total):
        """Keep a small copy of the frame that was just built (about 8 times a second) for the build preview in the Tasks window."""
        now = time.monotonic()
        if now - self._thumb_t < 0.12 or not CFG.get("show_build_preview", True): return
        self._thumb_t = now
        try:
            h, w = fr.shape[:2]; tw = 360; self.thumb = (cv2.resize(fr, (tw, max(2, int(h * tw / float(w)))), interpolation=cv2.INTER_AREA), int(i), int(total))
        except Exception: pass
    def run(self):
        self.state = "running"
        if self._task is not None: self._task.detail = ""; self._task.t0 = time.monotonic()
        ok, msg = False, ""
        try: ok, msg = self._run()
        except Exception as ex: ok, msg = False, str(ex)
        finally:
            if self._task is not None: self._task.finish()
        self.done_sig.emit(ok, msg); self.finished_job.emit(self, ok, msg)
    def _detail(self, text):
        if self._task is not None: self._task.detail = text
    def _write_audio(self, proj, dur, wav):
        """Mix the sound in 10 second pieces (so a cancel is noticed quickly and a long project does not fill the memory)."""
        total = max(dur, 0.01); t = 0.0; step = 10.0
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
            while t < total - 1e-9:
                if self.cancel: return False
                e = min(total, t + step); d = mix_audio(proj, t, e, wait=True)      # the export waits for the effects
                wf.writeframes((np.clip(d, -1, 1) * 32767).astype(np.int16).tobytes()); t = e
                self._detail("audio %d%%" % int(t / total * 100))
        return True
    def _discard(self, fmt, out, frames):
        """Remove what a cancelled / failed export left behind."""
        try:
            if fmt == "png":
                for f in frames:
                    try: os.remove(f)
                    except OSError: pass
                try: os.rmdir(out)
                except OSError: pass
            elif os.path.isfile(out): os.remove(out)
        except Exception: pass
    def _run(self):
        tmpd = None; proc = None; frames = []; fmt = self.o.get("fmt"); out = self.o.get("path")
        try:
            proj = Project.from_dict(self.pd); o = self.o; dur = proj.duration()
            if dur <= 0 and o["fmt"] not in ("mp3", "wav"): raise RuntimeError("Timeline is empty")
            fmt, out, fps, ow, oh, crf = o["fmt"], o["path"], int(o["fps"]), int(o["w"]), int(o["h"]), int(o["crf"])
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            tmpd = tempfile.mkdtemp(prefix="minicut_"); wav = os.path.join(tmpd, "audio.wav"); errlog = os.path.join(tmpd, "ffmpeg.log")
            if not self._write_audio(proj, dur, wav): return False, "Export cancelled"
            if fmt in ("mp3", "wav"):
                cmd = [FFMPEG, "-y", "-i", wav]
                if fmt == "mp3": cmd += ["-b:a", "192k"]
                cmd += [out]
                with open(errlog, "wb") as ef: self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=ef, creationflags=NOWIN)
                code = self._proc.wait()
                if self.cancel: self._discard(fmt, out, frames); return False, "Export cancelled"
                if code: raise RuntimeError(open(errlog, "rb").read().decode(errors="replace")[-1500:])
                return True, out
            if fmt == "png": os.makedirs(out, exist_ok=True)
            elif fmt == "gif":
                cmd = [FFMPEG, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ow}x{oh}", "-r", str(fps), "-i", "-", "-vf", "fps=15,scale=480:-1:flags=lanczos", out]
            else:
                cmd = [FFMPEG, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ow}x{oh}", "-r", str(fps), "-i", "-"]
                has_audio = os.path.getsize(wav) > 44
                if has_audio: cmd += ["-i", wav]
                vcodec, hwenc, _note = codec_plan(fmt); _xp = CFG.get("export_preset", "fast")       # Settings > Export > Preset
                if vcodec is None: raise RuntimeError(_note)
                self._detail(_note); _v0 = len(cmd)
                cmd += ["-c:v", vcodec]
                if fmt == "mov": cmd += ["-profile:v", "3"]
                elif fmt == "webm": cmd += ["-b:v", "4M"]
                elif hwenc: cmd += hw_quality_args(hwenc[0], crf, ow, _xp)
                elif vcodec == "libsvtav1": cmd += ["-crf", str(crf), "-preset", SVT_PRESET.get(_xp, "8"), "-pix_fmt", "yuv420p"]
                elif vcodec == "libaom-av1": cmd += ["-crf", str(crf), "-b:v", "0", "-cpu-used", AOM_CPU_USED.get(_xp, "6"), "-row-mt", "1", "-pix_fmt", "yuv420p"]
                else: cmd += ["-crf", str(crf), "-preset", X264_PRESET.get(_xp, "veryfast"), "-pix_fmt", "yuv420p"]
                vargs = cmd[_v0:]; aargs = ["-c:a", "libopus" if fmt == "webm" else "aac", "-b:a", "192k"]; tail = ["-movflags", "+faststart"] if fmt in ("mp4", "mp4_265", "mkv", "av1") else []
                if has_audio: cmd += aargs + ["-shortest"]
                cmd += tail
                cmd += [out]
                total_f = max(1, int(dur * fps))
                running = len([j for j in EXPORTS.jobs if j.state == "running"])
                nw = XP.worker_count(_render_threads(CFG.get("render_threads", 0)), running, bool(hwenc), total_f)
                nw = _RAM.export_workers(nw, ow, oh, vcodec, X264_PRESET.get(_xp, "veryfast"), bool(hwenc))        # Patch 46: only as many pieces as fit under the RAM limit
                if running > 1 and _RAM.limit_mb(): nw = max(1, nw // running)
                if fmt in XP.SEG_EXT and nw >= 2:      # Patch 38: several pieces of the timeline are rendered at the same time
                    return self._run_parallel(proj, wav, has_audio, vargs, aargs if has_audio else [], tail, hwenc, total_f, fps, ow, oh, nw, tmpd, out, fmt)
            if fmt != "png":
                ef = open(errlog, "wb")      # the encoder's messages go to a file: a full pipe can never block it
                proc = self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ef, creationflags=NOWIN)
            try:                                    # Patch 36: OpenGL effects also work on the export thread (a real GPU only; software GL stays off)
                from . import glfx as _glx; _glx.enable_current_thread(); _glx.set_export_mode(True)
            except Exception: pass
            _enter_export_thread()                  # Patch 46: the frame is composed on the GPU of this thread; small caches
            renderer = Renderer(MediaPool(export=True)); renderer.export_mode = True; total = max(1, int(dur * fps))
            if self._task is not None: self._task.total = total
            # Patch 36: the frame is written to the encoder by a second thread, so rendering frame i+1 overlaps writing frame i
            # (before, the render waited for every write). A small queue keeps the memory low.
            wq = queue.Queue(maxsize=4); werr = []
            def _writer():
                while True:
                    item = wq.get()
                    if item is None: return
                    if werr: continue                                  # an error happened: only drain the queue so the render never blocks
                    kind, i, data = item
                    try:
                        if kind == "png":
                            if not cv2.imwrite(data[0], data[1]): raise RuntimeError("Could not write PNG frame")
                            frames.append(data[0])
                        elif proc and proc.stdin: proc.stdin.write(data)
                    except (BrokenPipeError, OSError) as ex:
                        if not self.cancel: werr.append(ex)
                        else: werr.append(None)
                    except Exception as ex: werr.append(ex)
            wt = threading.Thread(target=_writer, daemon=True, name="export-writer"); wt.start()
            try:
                for i in range(total):
                    if self.cancel or werr: break
                    fr = renderer.render(proj, i / fps, 1.0, fast=False)
                    if ow != proj.w or oh != proj.h: fr = letterbox(fr, ow, oh)
                    self._thumb(fr, i, total)
                    if fmt == "png": wq.put(("png", i, (os.path.join(out, f"frame_{i:06d}.png"), fr)))
                    elif proc and proc.stdin: wq.put(("raw", i, memoryview(np.ascontiguousarray(fr)).cast("B")))        # no copy: the frame is new for every call
                    if i % 3 == 0:
                        self.progress.emit((i + 1) / total * 100)
                        if self._task is not None: self._task.done = i + 1
            finally:
                wq.put(None); wt.join()
            if werr and werr[0] is not None and not self.cancel: raise RuntimeError(str(werr[0]))
            if proc:
                if self.cancel:
                    try: proc.kill()
                    except Exception: pass
                try:
                    if proc.stdin: proc.stdin.close()
                except Exception: pass
                code = proc.wait(); ef.close()
                if code and not self.cancel: raise RuntimeError(open(errlog, "rb").read().decode(errors="replace")[-1800:] or f"FFmpeg exited with code {code}")
            if self.cancel: self._discard(fmt, out, frames); return False, "Export cancelled"
            self.progress.emit(100); return True, out
        except Exception as ex:
            if proc is not None:
                try: proc.kill()
                except Exception: pass
            if self.cancel: self._discard(fmt, out, frames); return False, "Export cancelled"
            return False, str(ex)
        finally:
            self._proc = None
            _leave_export_thread()
            if tmpd:
                import shutil; shutil.rmtree(tmpd, ignore_errors=True)


def _enter_export_thread():
    """Patch 46: this thread renders export frames: GPU composing on, Bone2D pictures are not cached, small caches."""
    try:
        from . import meshgl as _mg; _mg.enable_current_thread(); _mg.set_export_mode(True)
    except Exception: pass
    try:
        from . import bone2d as _b2; _b2.set_export_thread(True)
    except Exception: pass


def _leave_export_thread():
    try:
        from . import glfx as _glx; _glx.close_thread()
    except Exception: pass
    try:
        from . import meshgl as _mg; _mg.close_thread()
    except Exception: pass
    try:
        from . import bone2d as _b2; _b2.set_export_thread(False)
    except Exception: pass


def _export_parallel(self, proj, wav, has_audio, vargs, aargs, tail, hwenc, total, fps, ow, oh, nw, tmpd, out, fmt):
    """Render the timeline in pieces on `nw` threads (render/export_par.py), then join the pieces and add the sound. (Patch 38)"""
    ext = XP.SEG_EXT[fmt]; t0 = time.monotonic(); last = [0.0]
    def reg(proc, add):
        with self._plock:
            if add: self._procs.append(proc)
            elif proc in self._procs: self._procs.remove(proc)
    def make():
        try:
            from . import glfx as _glx; _glx.enable_current_thread(); _glx.set_export_mode(True)
        except Exception: pass
        _enter_export_thread()
        rend = Renderer(MediaPool(export=True)); rend.export_mode = True
        return Project.from_dict(copy.deepcopy(self.pd)), rend
    def ended():
        _leave_export_thread()
    def frames(n, rate):
        if self._task is not None: self._task.done = n
        now = time.monotonic()
        if now - last[0] > 0.25:
            last[0] = now; self.progress.emit(n / float(total) * 100); self._detail("%d threads \u00b7 %.0f fps" % (nw, rate))
    same = (ow == proj.w and oh == proj.h)
    if self._task is not None: self._task.total = total
    enc_thr = None if (hwenc or not str(vargs[1] if len(vargs) > 1 else "").startswith("lib")) else max(2, (os.cpu_count() or 4) // nw)
    paths = XP.render_pieces(make, lambda p, r, t: r.render(p, t, 1.0, fast=False), (lambda f: f) if same else (lambda f: letterbox(f, ow, oh)), total, fps, ow, oh,
                             vargs, ext, tmpd, nw, FFMPEG, lambda: self.cancel, frames, lambda f, i: self._thumb(f, i, total), reg, enc_thr, ended)
    if paths is None or self.cancel: self._discard(fmt, out, []); return False, "Export cancelled"
    self._detail("joining"); lst = os.path.join(tmpd, "pieces.txt"); XP.write_list(lst, paths)
    log = os.path.join(tmpd, "join.log")
    with open(log, "wb") as ef: self._proc = subprocess.Popen(XP.join_cmd(FFMPEG, lst, wav if has_audio else None, aargs, tail, out), stdout=subprocess.DEVNULL, stderr=ef, creationflags=NOWIN)
    code = self._proc.wait()
    if self.cancel: self._discard(fmt, out, []); return False, "Export cancelled"
    if code: raise RuntimeError(open(log, "rb").read().decode(errors="replace")[-1800:] or "FFmpeg exited with code %d" % code)
    self.progress.emit(100); return True, out


ExportWorker._run_parallel = _export_parallel


class ExportManager(QObject):
    """All exports of the program. Each export is its own job with its own cancel; several run at the same time (up to
    `max_parallel`, the others wait in line and start by themselves). The jobs belong to the manager, not to a window, so
    closing the export window or editing the project never disturbs a running export."""
    changed = Signal()
    job_finished = Signal(object)
    HISTORY = 12
    def __init__(self):
        super().__init__(); self.jobs = []; self.max_parallel = 2
    def add(self, pd, opts):
        task = TASKS.start("export", "Export  " + (os.path.basename(opts["path"].rstrip("/\\")) or opts["path"])); task.detail = "waiting"
        w = ExportWorker(pd, opts, task); task.cancel_fn = lambda w=w: self.cancel(w)
        w.finished_job.connect(self._on_done); self.jobs.append(w); self._pump(); self.changed.emit(); return w
    def paths_in_use(self): return {j.out for j in self.jobs if j.state in ("queued", "running")}
    def active(self): return [j for j in self.jobs if j.state in ("queued", "running")]
    def _pump(self):
        run = [j for j in self.jobs if j.state == "running"]
        for j in self.jobs:
            if len(run) >= max(1, int(self.max_parallel)): break
            if j.state == "queued" and not j.isRunning():
                j.state = "running"; j.start(); run.append(j)
    def cancel(self, w):
        if w.state == "queued":
            w.state = "cancelled"; w.msg = "Export cancelled"; w.cancel = True
            if w._task is not None: w._task.finish()
            self._pump(); self.changed.emit()
        elif w.state == "running": w.request_cancel(); self.changed.emit()
    def cancel_all(self):
        for j in list(self.active()): self.cancel(j)
    def _on_done(self, w, ok, msg):
        w.state = "done" if ok else ("cancelled" if w.cancel else "failed"); w.msg = msg
        finished = [j for j in self.jobs if j.state in ("done", "failed", "cancelled")]
        for j in finished[:-self.HISTORY]:
            if not j.isRunning(): self.jobs.remove(j)
        self._pump(); self.changed.emit(); self.job_finished.emit(w)
    def remove(self, w):
        if w.state in ("done", "failed", "cancelled") and w in self.jobs: self.jobs.remove(w); self.changed.emit()
    def shutdown(self, timeout_ms=4000):
        """Cancel everything and wait a little for the threads (used when the program closes)."""
        self.cancel_all()
        for j in list(self.jobs):
            if j.isRunning(): j.wait(timeout_ms)


EXPORTS = ExportManager()


QSpinBox = SpinBox; QComboBox = ComboBox; QCheckBox = CheckBox      # drawn by the program (set here, after all the imports)


class ExportDialog(AnimatedDialog):
    """Choose the settings and press the export button: the export runs in the background (see the progress ring), so the
    editor stays usable and another export can be started right away."""
    def __init__(self, app):
        super().__init__(app, "Export video", 500); self.app = app
        form = QFormLayout(); self.fmt = QComboBox()
        for k, (label, ext) in FORMATS.items(): self.fmt.addItem(label, k)
        self.fmt.currentIndexChanged.connect(self.update_ext)
        self.path = PathEdit(app.settings["export_folder"]); self.filename = TextField(safe_name(app.proj.name) + ".mp4")
        self.fps = QComboBox(); [self.fps.addItem(f"{v} fps", v) for v in (24, 25, 30, 50, 60)]
        self.fps.setCurrentIndex(max(0, self.fps.findData(app.proj.fps)))
        self.size = QComboBox()
        for label, w, h in SIZE_PRESETS: self.size.addItem(label, (w, h))
        idx = next((i for i, (_, w, h) in enumerate(SIZE_PRESETS) if (w, h) == (app.proj.w, app.proj.h)), 0); self.size.setCurrentIndex(idx)
        self.crf = QSpinBox(); self.crf.setRange(12, 35); self.crf.setValue(export_crf(app.settings["export_space"])); self.crf.setToolTip("Lower = better quality, bigger file")
        for ic, lab, w in (("video", "Format", self.fmt), ("folder_open", "Folder", self.path), ("text", "Name", self.filename),
                           ("aspect_ratio", "Size", self.size), ("speed", "FPS", self.fps), ("tune", "Quality", self.crf)):
            l = QWidget(); ll = QHBoxLayout(l); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(6); ll.addWidget(icon_label(ic, "#9aa4b8", 16)); t = QLabel(lab); t.setObjectName("Dim"); ll.addWidget(t); ll.addStretch()
            form.addRow(l, w)
        self.body.addLayout(form)
        row = QHBoxLayout(); row.addStretch()
        cancel = tool("", "Close", self.reject, icon="close", isize=18); self.go = QPushButton("Export"); self.go.setIcon(app_icon("export", "#ffffff")); self.go.setObjectName("Accent"); self.go.clicked.connect(self.start_export)
        row.addWidget(cancel); row.addWidget(self.go); self.body.addLayout(row)
    def update_ext(self):
        k = self.fmt.currentData(); ext = FORMATS[k][1]
        base = os.path.splitext(self.filename.text())[0] or safe_name(self.app.proj.name)
        if ext: self.filename.setText(base + ext)
    def start_export(self):
        folder = self.path.text() or self.app.settings["export_folder"]
        try: os.makedirs(folder, exist_ok=True)
        except Exception as ex: QMessageBox.warning(self, "Export", str(ex)); return
        name = self.filename.text().strip() or safe_name(self.app.proj.name) + FORMATS[self.fmt.currentData()][1]
        out = os.path.join(folder, name); w, h = self.size.currentData()
        if out in EXPORTS.paths_in_use():
            QMessageBox.information(self, "Export", "This file name is already being exported. Choose another name."); return
        self.app.settings["export_folder"] = folder; self.app.settings.save()
        pd = copy.deepcopy(self.app.proj.to_dict())       # a private copy: editing the project while it renders changes nothing
        EXPORTS.add(pd, {"fmt": self.fmt.currentData(), "path": out, "fps": self.fps.currentData(), "w": w, "h": h, "crf": self.crf.value()})
        try: self.app.toast.show_msg("Export started: " + os.path.basename(out), 2600)
        except Exception: pass
        self.accept()


# MINI CUT PATCH 39: no background baking while an export runs
try:
    from .bake import guard_export as _mc39_guard
    _mc39_guard(ExportWorker)
except Exception as _mc39_ex:
    print("[bake] export guard not installed:", _mc39_ex)

"""Parallel export (Patch 38): the timeline is cut into short pieces, several threads render them at the same time and each piece goes
to its own encoder; the pieces are then joined without re-encoding (see join_cmd). Plain Python (no Qt) so it can be tested alone.

Why pieces: one frame after another keeps a single core busy while the others wait. Different pieces never depend on each other
(every piece starts with a key frame), so any number of cores can work at once and the result is the same video."""
import os, queue, threading, subprocess, time, math

NOWIN = 0x08000000 if os.name == "nt" else 0
SEG_EXT = {"mp4": ".mkv", "mp4_265": ".mkv", "av1": ".mkv", "mkv": ".mkv", "mov": ".mov", "webm": ".webm"}     # pieces for each output format


def plan_ranges(total, workers, min_chunk=30, per_worker=4):
    """[(start_frame, end_frame)): about `per_worker` pieces for each worker (so a slow piece does not leave the others idle)."""
    chunk = max(min_chunk, int(math.ceil(total / float(max(1, workers) * per_worker))))
    return [(a, min(total, a + chunk)) for a in range(0, total, chunk)]


def worker_count(threads, running_jobs, hw_encoder, total_frames):
    """How many pieces are rendered at once. threads: the render-thread budget; it is shared with the other exports that run now."""
    n = max(1, int(threads) // max(1, int(running_jobs)))
    if hw_encoder: n = min(n, 3)                       # GPU encoders only accept a few sessions at once
    return max(1, min(n, total_frames // 30 or 1))


def segment_cmd(ffmpeg, ow, oh, fps, vargs, path, threads=None):
    c = [ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (ow, oh), "-r", str(fps), "-i", "-"] + list(vargs)
    if threads: c += ["-threads", str(int(threads))]
    return c + ["-an", path]


def join_cmd(ffmpeg, listfile, wav, audio_args, tail_args, out):
    """Join the pieces (stream copy) and add the sound."""
    c = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", listfile]
    if wav: c += ["-i", wav]
    c += ["-c:v", "copy"]
    if wav: c += list(audio_args) + ["-shortest"]
    return c + list(tail_args) + [out]


def write_list(listfile, paths):
    with open(listfile, "w", encoding="utf-8") as f:
        for p in paths: f.write("file '%s'\n" % p.replace("\\", "/").replace("'", "'\\''"))


def render_pieces(make_renderer, render_frame, post, total, fps, ow, oh, vargs, ext, tmpd, workers, ffmpeg, cancelled,
                  on_frames=None, on_thumb=None, register_proc=None, enc_threads=None, thread_done=None):
    """Render the whole timeline in pieces. make_renderer() -> (project, renderer) is called once on each worker thread; render_frame(project,
    renderer, t) -> BGR frame; post(frame) -> frame at the output size. Returns the piece paths in order. Raises on the first error."""
    ranges = plan_ranges(total, workers); todo = queue.Queue()
    for k, (a, b) in enumerate(ranges): todo.put((k, a, b))
    result = {}; errors = []; lock = threading.Lock(); done = [0]; t0 = time.monotonic()

    def one_piece(proj, rend, k, a, b):
        path = os.path.join(tmpd, "piece_%05d%s" % (k, ext)); log = open(path + ".log", "wb")
        proc = subprocess.Popen(segment_cmd(ffmpeg, ow, oh, fps, vargs, path, enc_threads), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, creationflags=NOWIN)
        if register_proc: register_proc(proc, True)
        wq = queue.Queue(maxsize=3); werr = []

        def writer():
            while True:
                data = wq.get()
                if data is None: return
                if werr: continue
                try: proc.stdin.write(data)
                except Exception as ex: werr.append(ex)
        wt = threading.Thread(target=writer, daemon=True); wt.start()
        try:
            for i in range(a, b):
                if cancelled() or errors or werr: break
                fr = post(render_frame(proj, rend, i / float(fps)))
                wq.put(memoryview(fr).cast("B") if fr.flags["C_CONTIGUOUS"] else fr.copy().tobytes())        # Patch 46: no copy of the frame (it is new for every call)
                with lock: done[0] += 1; n = done[0]
                if on_frames: on_frames(n, (n / max(1e-6, time.monotonic() - t0)))
                if on_thumb: on_thumb(fr, i)
        finally:
            wq.put(None); wt.join()
            try: proc.stdin.close()
            except Exception: pass
            code = proc.wait(); log.close()
            if register_proc: register_proc(proc, False)
        if cancelled() or errors: return
        if werr or code:
            try: msg = open(path + ".log", "rb").read().decode(errors="replace")[-1500:]
            except Exception: msg = ""
            raise RuntimeError(msg or "encoder failed (piece %d)" % k)
        result[k] = path

    def worker():
        try:
            proj, rend = make_renderer()
            while not cancelled() and not errors:
                try: k, a, b = todo.get_nowait()
                except queue.Empty: break
                one_piece(proj, rend, k, a, b)
        except Exception as ex:
            with lock: errors.append(ex)
        finally:
            if thread_done:
                try: thread_done()
                except Exception: pass

    ths = [threading.Thread(target=worker, daemon=True, name="export-piece-%d" % i) for i in range(workers)]
    for t in ths: t.start()
    for t in ths: t.join()
    if errors: raise errors[0]
    if cancelled(): return None
    if len(result) != len(ranges): raise RuntimeError("some pieces were not rendered")
    return [result[k] for k in range(len(ranges))]

"""Sampling profiler for the REAL editor (Patch 38). Start with Run_MiniCut_Profile.bat, play the slow project for ~30 s, close MiniCut.
Every 20 ms it records, for every thread, which function is running (full stack, innermost 6 frames) and writes
minicut_profile.txt: which thread is busy, and in which code. A thread that is "waiting" is idle and not a problem."""
import sys, threading, time, os, collections, traceback, atexit

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "minicut_profile.txt")


_T = {}      # name -> list of (start_time, ms)


def _wrap_render():
    """Time the calls that make one preview frame, so the report also says how many frames per second the editor really delivers."""
    try:
        from .render import renderer as R
        def timed(name, fn):
            lst = _T.setdefault(name, [])
            def w(*a, **k):
                t0 = time.perf_counter()
                try: return fn(*a, **k)
                finally:
                    if len(lst) < 200000: lst.append((t0, (time.perf_counter() - t0) * 1000.0))
            return w
        R.Renderer.render_cached = timed("render_cached (one preview frame, incl. proxy lookup)", R.Renderer.render_cached)
        R.Renderer.render = timed("Renderer.render (real composition work)", R.Renderer.render)
        R.frame_to_qimage = timed("frame_to_qimage (convert for the window)", R.frame_to_qimage)
    except Exception as ex:
        _T["wrap_error"] = [(0, 0)]; print("profiler: cannot time renders:", ex)


def _frame_report(f):
    f.write("== FRAME TIMING (what the user feels) ==\n")
    for name, lst in _T.items():
        if len(lst) < 2: f.write("  %-62s %d calls\n" % (name, len(lst))); continue
        ms = sorted(x[1] for x in lst); n = len(ms); span = max(1e-3, lst[-1][0] - lst[0][0])
        gaps = sorted(lst[i + 1][0] - lst[i][0] for i in range(n - 1))
        f.write("  %-62s %6d calls | %5.1f/s | work mean %6.1f ms p50 %6.1f p95 %6.1f worst %7.1f | gap between calls p50 %5.0f ms p95 %5.0f ms\n" % (
            name, n, n / span, sum(ms) / n, ms[n // 2], ms[int(n * .95)], ms[-1], gaps[len(gaps) // 2] * 1000, gaps[int(len(gaps) * .95)] * 1000))
        # per 5-second window: shows whether it is slow all the time or only in bursts
        w0 = lst[0][0]; wins = collections.defaultdict(list)
        for t0, m in lst: wins[int((t0 - w0) // 5)].append(m)
        f.write("      per 5 s: " + "  ".join("%d:%.0ffps/%.0fms" % (k * 5, len(v) / 5.0, sum(v) / len(v)) for k, v in sorted(wins.items())[:24]) + "\n")
    f.write("\n")


def start():
    _wrap_render()
    t0 = time.time(); per = collections.defaultdict(collections.Counter); leaf = collections.defaultdict(collections.Counter)
    total = collections.Counter(); busy = collections.Counter(); stop = [False]; me = None
    names = lambda: {t.ident: t.name for t in threading.enumerate()}

    def loop():
        n = 0
        while not stop[0]:
            time.sleep(0.02); n += 1; nm = names()
            frames = sys._current_frames()
            for tid in list(frames):
                if nm.get(tid) == "MiniCutProfiler": continue
                tn = nm.get(tid, str(tid)); total[tn] += 1
                fr = frames[tid]; f = fr; stack = []
                while f is not None and len(stack) < 40:
                    stack.append("%s:%d %s" % (os.path.basename(f.f_code.co_filename), f.f_lineno, f.f_code.co_name)); f = f.f_back
                fn = fr.f_code.co_name; skip_idle = any(fn == w or fn.startswith(w) for w in ("wait", "sleep", "acquire", "select", "poll", "readinto", "join", "get")) and "minicut" not in fr.f_code.co_filename
                fr = f = None; frames[tid] = None            # never keep a frame alive: a kept paintEvent frame keeps its QPainter open (Qt endPaint warning)
                if skip_idle or not stack: continue
                top = stack[0]; busy[tn] += 1; leaf[tn][top.split(":")[0] + " " + top.split(" ", 1)[1]] += 1
                key = " <- ".join(s.split(" ", 1)[1] + "@" + s.split(":")[0] for s in stack[:6]); per[tn][key] += 1
            del frames

    th = threading.Thread(target=loop, name="MiniCutProfiler", daemon=True); th.start()

    def dump():
        stop[0] = True; el = time.time() - t0
        try:
            with open(OUT, "w", encoding="utf-8") as f:
                f.write("MiniCut profile, %.0f s, samples every 20 ms\nPython %s\n\n" % (el, sys.version.split()[0])); _frame_report(f)
                for tn, b in busy.most_common():
                    f.write("== thread %-28s busy %5.1f%% of the time (%d of %d samples)\n" % (tn, 100.0 * b / max(1, total[tn]), b, total[tn]))
                    for k, c in per[tn].most_common(12): f.write("   %5.1f%%  %s\n" % (100.0 * c / max(1, total[tn]), k))
                    f.write("   -- innermost function only:\n")
                    for k, c in leaf[tn].most_common(8): f.write("   %5.1f%%  %s\n" % (100.0 * c / max(1, total[tn]), k))
                    f.write("\n")
        except Exception: pass
    atexit.register(dump)
    return dump

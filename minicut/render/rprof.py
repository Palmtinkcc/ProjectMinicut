"""Patch 47, phase 1: render stage profiler.

Measures where the time of one frame goes, split into CPU work, uploads (CPU -> GPU), GPU time, read-backs (GPU -> CPU) and memory.
It is OFF by default. Switch it on with the environment variable MINICUT_RPROF=1 or with rprof.enable() (bench_core.py does this).
When it is off every hook costs one float test (t0() returns 0.0 and end() returns at once); nothing is stored, nothing is timed.

Use at a hook site:

    _t = _rp.t0()                       # 0.0 when the profiler is off
    ... the work ...
    _rp.end("upload", _t, nbytes)       # adds the time (and bytes) to the stage "upload" of the frame that is being rendered

Stages are plain names. The kind of a stage is the part before the first ":" or ".", e.g. "layer:video" -> kind "layer".
Kinds used by the hooks: plan, layer (decode / scale / effects of one layer), fx (effects), cpu_draw, upload, draw (GL commands being issued,
NOT the time the GPU needs), gpu (real GPU time from a GL timer query), readback (GPU -> CPU; it also waits for the GPU, so it
contains GPU time that was still running), composite (the whole composite call).

Caveats that the report repeats:
  * "draw" is only the time to ISSUE the GL commands. The GPU runs them later. Real GPU time is in "gpu" (timer query), when the driver has one.
  * "readback" contains the wait for the GPU. Do not add draw + gpu + readback and call it the total: use the frame total.
  * Stages can be nested (e.g. "upload" happens inside "composite"), so the stages of a frame add up to more than the frame total.
"""
import os, time, threading, json, collections, contextlib

on = bool(os.environ.get("MINICUT_RPROF"))
_lock = threading.Lock()
_TL = threading.local()
_FRAMES = []                  # finished frame records (all threads)
MAX_FRAMES = 50000
_proc = None


def enable(flag=True):
    global on
    on = bool(flag)


def reset():
    with _lock: _FRAMES.clear()


def t0():
    """Start a timing. Returns 0.0 when the profiler is off (then end() does nothing)."""
    return time.perf_counter() if on else 0.0


def _cur():
    f = getattr(_TL, "frame", None)
    return f


def end(stage, started, nbytes=0):
    """Add the time since `started` (from t0()) to `stage` of the current frame; nbytes is added to the stage's byte counter."""
    if not started: return
    ms = (time.perf_counter() - started) * 1000.0
    add(stage, ms, nbytes)


def add(stage, ms, nbytes=0):
    f = _cur()
    if f is None: return
    s = f["stages"].get(stage)
    if s is None: s = f["stages"][stage] = [0.0, 0, 0]       # ms, calls, bytes
    s[0] += ms; s[1] += 1; s[2] += int(nbytes)


def count(name, n=1):
    """Plain counter of the current frame (texture cache hits, draw calls ...)."""
    if not on: return
    f = _cur()
    if f is None: return
    f["counters"][name] = f["counters"].get(name, 0) + n


def note(name, value):
    """A value of the current frame that is not summed (the compositor path, a texture-cache size ...)."""
    if not on: return
    f = _cur()
    if f is None: return
    f["notes"][name] = value


def rss_mb():
    global _proc
    try:
        import psutil
        if _proc is None: _proc = psutil.Process()
        return _proc.memory_info().rss / 1e6
    except Exception:
        return 0.0


def frame_begin(label=""):
    """Called by Renderer.render() at depth 0. Starts the record of one frame on this thread."""
    if not on: return 0.0
    _TL.frame = {"label": label, "thread": threading.current_thread().name, "stages": {}, "counters": {}, "notes": {}, "total_ms": 0.0, "rss_mb": 0.0}
    return time.perf_counter()


def frame_end(started):
    if not started: return
    f = getattr(_TL, "frame", None); _TL.frame = None
    if f is None: return
    f["total_ms"] = (time.perf_counter() - started) * 1000.0; f["rss_mb"] = rss_mb()
    with _lock:
        if len(_FRAMES) < MAX_FRAMES: _FRAMES.append(f)


class _NullTimer:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _GLTimer:
    """GL timer query around some draw calls. Reading the result waits for the GPU, which is acceptable only while profiling."""
    def __init__(self, ctx, stage):
        self.ctx = ctx; self.stage = stage; self.q = None
    def __enter__(self):
        try:
            self.q = self.ctx.query(time=True); self.q.__enter__()
        except Exception:
            self.q = None
        return self
    def __exit__(self, *a):
        if self.q is None: return False
        try:
            self.q.__exit__(*a); ns = self.q.elapsed
            add(self.stage, ns / 1e6)
        except Exception:
            note("gpu_timer", "unavailable")
        return False


def gpu_timer(ctx, stage="gpu"):
    """`with _rp.gpu_timer(ctx, "gpu:composite"): ...draw calls...`  Adds the real GPU time to the stage. Does nothing when the profiler is off."""
    return _GLTimer(ctx, stage) if on else _NullTimer()


# ───────────────────────────── report
def frames():
    with _lock: return list(_FRAMES)


def _pct(v, p):
    if not v: return 0.0
    v = sorted(v); return v[min(len(v) - 1, int(len(v) * p))]


def summary(fr=None, skip=0):
    """Dict: per stage (mean / p95 ms per frame, calls per frame, MB per frame), frame totals, counters, notes, memory. skip: warm-up frames to leave out."""
    fr = frames() if fr is None else fr
    fr = fr[skip:] if len(fr) > skip else fr
    n = len(fr)
    out = {"frames": n, "total_ms": {}, "stages": {}, "counters": {}, "notes": {}, "rss_mb": {}}
    if not n: return out
    tot = [f["total_ms"] for f in fr]
    out["total_ms"] = {"mean": sum(tot) / n, "p50": _pct(tot, .5), "p95": _pct(tot, .95), "max": max(tot), "fps_if_serial": 1000.0 / max(1e-9, sum(tot) / n)}
    names = sorted({k for f in fr for k in f["stages"]})
    for k in names:
        ms = [f["stages"].get(k, [0.0, 0, 0])[0] for f in fr]; calls = [f["stages"].get(k, [0.0, 0, 0])[1] for f in fr]; by = [f["stages"].get(k, [0.0, 0, 0])[2] for f in fr]
        out["stages"][k] = {"mean_ms": sum(ms) / n, "p95_ms": _pct(ms, .95), "calls": sum(calls) / n, "mb": sum(by) / n / 1e6}
    cn = sorted({k for f in fr for k in f["counters"]})
    for k in cn: out["counters"][k] = sum(f["counters"].get(k, 0) for f in fr) / n
    nt = collections.defaultdict(collections.Counter)
    for f in fr:
        for k, v in f["notes"].items(): nt[k][str(v)] += 1
    out["notes"] = {k: dict(c) for k, c in nt.items()}
    rs = [f["rss_mb"] for f in fr if f["rss_mb"]]
    if rs: out["rss_mb"] = {"first": rs[0], "last": rs[-1], "max": max(rs)}
    return out


def kind_totals(s):
    """Sum the mean ms of the stages by kind (the part of the name before ':' or '.')."""
    out = collections.OrderedDict()
    for k, v in s["stages"].items():
        kind = k.replace(":", ".").split(".")[0]; out[kind] = out.get(kind, 0.0) + v["mean_ms"]
    return out


def report_text(s, title="", skip_note=""):
    L = []
    if title: L.append("== %s ==" % title)
    if not s["frames"]: L.append("(no frames recorded)"); return "\n".join(L)
    t = s["total_ms"]
    L.append("frames %d%s | frame total mean %.2f ms  p50 %.2f  p95 %.2f  max %.2f  (= %.1f fps if the frames ran one after another)" % (s["frames"], skip_note, t["mean"], t["p50"], t["p95"], t["max"], t["fps_if_serial"]))
    L.append("  %-30s %10s %10s %8s %9s" % ("stage", "mean ms", "p95 ms", "calls", "MB/frame"))
    for k, v in s["stages"].items(): L.append("  %-30s %10.3f %10.3f %8.2f %9.3f" % (k, v["mean_ms"], v["p95_ms"], v["calls"], v["mb"]))
    L.append("  by kind (stages can be nested, so this is NOT the frame total): " + ", ".join("%s %.2f ms" % kv for kv in kind_totals(s).items()))
    if s["counters"]: L.append("  per frame: " + ", ".join("%s %.2f" % kv for kv in sorted(s["counters"].items())))
    for k, c in s["notes"].items(): L.append("  %s: %s" % (k, ", ".join("%s x%d" % kv for kv in c.items())))
    if s["rss_mb"]: L.append("  program RSS: first %.0f MB, last %.0f MB, max %.0f MB" % (s["rss_mb"]["first"], s["rss_mb"]["last"], s["rss_mb"]["max"]))
    return "\n".join(L)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f: json.dump(obj, f, indent=1, ensure_ascii=False)

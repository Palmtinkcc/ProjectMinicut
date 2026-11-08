"""Low-overhead append-only diagnostic logger for MiniCut Patch 36."""
import json, os, threading, time, datetime
_LOCK = threading.Lock()
_COUNTS = {}
_LAST_SUMMARY = 0.0
_LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "minicut_render_debug.log"))

_ON = bool(os.environ.get("MINICUT_TRACE"))

def trace_event(event, **fields):
    if not _ON: return
    row = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="milliseconds"),
           "mono": round(time.perf_counter(), 4), "event": event, "thread": threading.current_thread().name}
    row.update(fields)
    try:
        with _LOCK:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

def trace_timing(event, ms, **fields):
    global _LAST_SUMMARY
    if not _ON: return
    ms = float(ms)
    # Log all slow operations; aggregate fast calls so diagnostics do not themselves cause stutter.
    now = time.perf_counter()
    with _LOCK:
        key = (event, "cache_hit=" + str(fields.get("cache_hit", "na")))
        stat = _COUNTS.setdefault(key, {"n": 0, "sum_ms": 0.0, "max_ms": 0.0, "last": {}})
        stat["n"] += 1; stat["sum_ms"] += ms; stat["max_ms"] = max(stat["max_ms"], ms); stat["last"] = fields
        should_summary = now - _LAST_SUMMARY >= 2.0
        if should_summary:
            summary = []
            for (ev, cache), s in list(_COUNTS.items()):
                summary.append({"event": ev, "group": cache, "n": s["n"], "avg_ms": round(s["sum_ms"] / max(1, s["n"]), 2),
                                "max_ms": round(s["max_ms"], 2), "last": s["last"]})
            _COUNTS.clear(); _LAST_SUMMARY = now
        else: summary = None
    if ms >= 25.0:
        trace_event("slow_" + event, duration_ms=round(ms, 2), **fields)
    if summary:
        trace_event("summary_2s", stats=summary)


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut Patch 36 — low-overhead render/playback diagnostics.

Adds timestamped logs for snapshot preparation, preview render duration/cache result, and video frame
read/cache timings. Does not alter render decisions, decoder selection, or playback settings.

Run from MiniCut root or Patch folder:
  python Patch/apply_36_render_diagnostics.py --check
  python Patch/apply_36_render_diagnostics.py
  python Patch/apply_36_render_diagnostics.py --revert
Log: minicut_render_debug.log in the MiniCut root.
"""
import datetime, hashlib, json, os, py_compile, shutil, sys, time
PATCH_NAME = "patch36_render_diagnostics"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(SCRIPT_DIR, "minicut", "app.py")):
    ROOT = SCRIPT_DIR
elif os.path.isfile(os.path.join(os.path.dirname(SCRIPT_DIR), "minicut", "app.py")):
    ROOT = os.path.dirname(SCRIPT_DIR)
else:
    ROOT = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR).lower() == "patch" else SCRIPT_DIR
BACKUP_ROOT = os.path.join(ROOT, "_patch_backup")
PATCH_FILES = ["minicut/render/renderer.py", "minicut/render/media.py"]
# Static metadata consumed by MiniCut Launcher. base=None marks these as
# script-managed soft updates; the installer itself performs strict layout checks.
FILES = {
    "minicut/render/debug_trace.py": {"base": None, "new": "c004e5a2da85b51d28f7f10920e5b02109ba80623c338333f2f2c04ea6ddb187", "soft": True},
}
MARK = "# MINI CUT PATCH 36 RENDER DIAGNOSTICS"

RENDER_HOOK = r'''

# MINI CUT PATCH 36 RENDER DIAGNOSTICS
try:
    from .debug_trace import trace_event, trace_timing
    _mc36_orig_render_cached = Renderer.render_cached
    def _mc36_render_cached(self, proj, t, q, fast=False, ver=None, fp=None):
        _mc36_t0 = time.perf_counter()
        _mc36_frame = int(round(max(0.0, float(t)) * max(1, proj.fps)))
        _mc36_key = None
        try:
            _mc36_fp = fp
            if _mc36_fp is None:
                _mc36_fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", None)], sort_keys=True, default=str))
            _mc36_key = ((_mc36_fp, self.version if ver is None else ver), _mc36_frame, round(float(q), 3), bool(fast))
            with self._cache_lock:
                _mc36_hit = _mc36_key in self.preview_cache
        except Exception:
            _mc36_hit = None
        try:
            return _mc36_orig_render_cached(self, proj, t, q, fast, ver, fp)
        finally:
            trace_timing("preview_frame", (time.perf_counter() - _mc36_t0) * 1000.0,
                         cache_hit=_mc36_hit, t=round(float(t), 4), frame=_mc36_frame,
                         q=round(float(q), 3), fast=bool(fast), clips=len(getattr(proj, "clips", [])))
    Renderer.render_cached = _mc36_render_cached

    _mc36_orig_render = Renderer.render
    def _mc36_render(self, proj, t, q, fast=False):
        _mc36_t0 = time.perf_counter()
        try:
            return _mc36_orig_render(self, proj, t, q, fast)
        finally:
            trace_timing("composite_render", (time.perf_counter() - _mc36_t0) * 1000.0,
                         t=round(float(t), 4), q=round(float(q), 3), fast=bool(fast))
    Renderer.render = _mc36_render

    _mc36_orig_submit = RenderWorker.submit
    def _mc36_submit(self, proj, t, q, fast):
        try:
            with self.cv:
                _mc36_replaced = self.job is not None
            if _mc36_replaced:
                trace_event("preview_request_replaced", t=round(float(t), 4), q=round(float(q), 3))
        except Exception: pass
        return _mc36_orig_submit(self, proj, t, q, fast)
    RenderWorker.submit = _mc36_submit

    _mc36_orig_snapshot = RenderWorker._snapshot_for
    def _mc36_snapshot(self, live):
        _mc36_t0 = time.perf_counter()
        try:
            return _mc36_orig_snapshot(self, live)
        finally:
            trace_timing("project_snapshot", (time.perf_counter() - _mc36_t0) * 1000.0,
                         version=getattr(self.r, "version", None), clips=len(getattr(live, "clips", [])))
    RenderWorker._snapshot_for = _mc36_snapshot
except Exception as _mc36_hook_error:
    try: trace_event("instrumentation_error", error=repr(_mc36_hook_error))
    except Exception: pass
# END MINI CUT PATCH 36 RENDER DIAGNOSTICS
'''

MEDIA_HOOK = r'''

# MINI CUT PATCH 36 RENDER DIAGNOSTICS
try:
    from .debug_trace import trace_timing
    _mc36_orig_raw_frame = VideoSource.raw_frame
    def _mc36_raw_frame(self, t):
        _mc36_t0 = time.perf_counter()
        _mc36_idx = int(max(0.0, float(t)) * max(1.0, float(getattr(self, "fps", 30))))
        _mc36_hit = False
        try:
            _mc36_cache = getattr(self, "rawc", {})
            _mc36_hit = any(isinstance(_mc36_k, tuple) and _mc36_k and _mc36_k[0] == _mc36_idx for _mc36_k in _mc36_cache)
        except Exception: pass
        try:
            return _mc36_orig_raw_frame(self, t)
        finally:
            trace_timing("video_raw_frame", (time.perf_counter() - _mc36_t0) * 1000.0,
                         cache_hit=_mc36_hit, frame=_mc36_idx, fps=round(float(getattr(self, "fps", 0) or 0), 3),
                         size="%sx%s" % (getattr(self, "w", 0), getattr(self, "h", 0)))
    VideoSource.raw_frame = _mc36_raw_frame
except Exception as _mc36_media_hook_error:
    try: trace_timing("media_instrumentation_error", 0, error=repr(_mc36_media_hook_error))
    except Exception: pass
# END MINI CUT PATCH 36 RENDER DIAGNOSTICS
'''

TRACE_MODULE = r'''"""Low-overhead append-only diagnostic logger for MiniCut Patch 36."""
import json, os, threading, time, datetime
_LOCK = threading.Lock()
_COUNTS = {}
_LAST_SUMMARY = 0.0
_LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "minicut_render_debug.log"))

def trace_event(event, **fields):
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
'''

def sha(b): return hashlib.sha256(b).hexdigest()
def path(rel): return os.path.join(ROOT, *rel.split('/'))
def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    found=[]
    for d in os.listdir(BACKUP_ROOT):
        mf=os.path.join(BACKUP_ROOT,d,"MANIFEST.json")
        if os.path.isfile(mf):
            try:
                with open(mf,encoding='utf-8') as f: m=json.load(f)
                if m.get('patch')==PATCH_NAME: found.append(d)
            except Exception: pass
    return os.path.join(BACKUP_ROOT, sorted(found)[-1]) if found else None

def main():
    revert='--revert' in sys.argv; check='--check' in sys.argv
    if revert:
        b=latest_backup()
        if not b: print('No Patch 36 backup found.'); return 2
        for rel in PATCH_FILES:
            src=os.path.join(b,*rel.split('/'))
            if os.path.isfile(src): shutil.copy2(src,path(rel))
        try: os.remove(path('minicut/render/debug_trace.py'))
        except OSError: pass
        print('Patch 36 reverted.'); return 0
    missing=[r for r in PATCH_FILES if not os.path.isfile(path(r))]
    if missing: print('Missing required file(s):', ', '.join(missing)); return 2
    contents={r:open(path(r),'rb').read() for r in PATCH_FILES}
    for rel,data in contents.items():
        if MARK.encode() in data:
            print('Patch 36 already installed in',rel); return 2
    rs=contents[PATCH_FILES[0]].decode('utf-8-sig'); ms=contents[PATCH_FILES[1]].decode('utf-8-sig')
    if 'class Renderer:' not in rs or 'def render_cached(' not in rs or 'class RenderWorker' not in rs or 'def _snapshot_for(' not in rs:
        print('Renderer layout not recognized; no files changed.'); return 2
    if 'class VideoSource' not in ms or 'def raw_frame(self, t):' not in ms:
        print('Media layout not recognized; no files changed.'); return 2
    if check:
        print('Patch 36 check passed: renderer/media hooks fit; no files changed.'); return 0
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S'); backup=os.path.join(BACKUP_ROOT,stamp)
    os.makedirs(backup,exist_ok=True)
    for rel,data in contents.items():
        dest=os.path.join(backup,*rel.split('/')); os.makedirs(os.path.dirname(dest),exist_ok=True); open(dest,'wb').write(data)
    with open(os.path.join(backup,'MANIFEST.json'),'w',encoding='utf-8') as f: json.dump({'patch':PATCH_NAME,'files':PATCH_FILES,'created':stamp},f,indent=2)
    trace_path=path('minicut/render/debug_trace.py'); os.makedirs(os.path.dirname(trace_path),exist_ok=True)
    with open(trace_path,'w',encoding='utf-8') as f: f.write(TRACE_MODULE+'\n')
    rs += RENDER_HOOK
    ms += MEDIA_HOOK
    for rel,txt in [(PATCH_FILES[0],rs),(PATCH_FILES[1],ms)]:
        with open(path(rel),'w',encoding='utf-8',newline='\n') as f: f.write(txt)
    try:
        for rel in PATCH_FILES+['minicut/render/debug_trace.py']: py_compile.compile(path(rel),doraise=True)
    except Exception as ex:
        for rel,data in contents.items(): open(path(rel),'wb').write(data)
        try: os.remove(trace_path)
        except OSError: pass
        print('Compile failed; original files restored:',ex); return 2
    print('Patch 36 installed. Reproduce the stutter for 20–40 seconds, then inspect minicut_render_debug.log.'); print('Backup:',backup); return 0
if __name__=='__main__': sys.exit(main())

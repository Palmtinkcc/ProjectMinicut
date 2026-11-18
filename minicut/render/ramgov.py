"""RAM governor (Patch 46): one number - "Max RAM" (default 1 GB) - keeps the whole program, an export included, under it.

Where the memory went (measured on a 1080p / 4K export):
  * every parallel export piece starts its own ffmpeg: libx264 holds ~235-295 MB at 1080p and ~930-1000 MB at 4K, `slow` presets more;
    4 pieces were already more than 1 GB before one frame was rendered;
  * every render thread also has its own caches (decoded frames, effect pictures, Bone2D pictures, decoded rig images);
  * the Bone2D frame cache counted pictures (48), not bytes.
This module (a) splits the limit between the caches, (b) says how many export pieces fit, (c) trims the caches when the process
gets near the limit while it runs. Plain Python, no Qt.
"""
import gc
import os
import sys
import threading
import time
import weakref

LIMIT_MB = [1024]                 # 0 = no limit
_STATE = {"base_mb": 0.0, "last": 0.0, "trims": 0}
_RENDERERS = weakref.WeakSet()
_LOCK = threading.Lock()


# ───────────────────────── measuring ─────────────────────────
def rss_mb(pid=None):
    """Resident memory of a process in MB (this one by default)."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k32 = ctypes.windll.kernel32; psapi = ctypes.windll.psapi
            h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x1010, False, int(pid))
            pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
            ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
            if pid is not None: k32.CloseHandle(h)
            return pmc.WorkingSetSize / 1048576.0 if ok else 0.0
        with open("/proc/%s/statm" % ("self" if pid is None else int(pid))) as f:
            return int(f.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") / 1048576.0)
    except Exception:
        try:
            import psutil
            return psutil.Process(pid).memory_info().rss / 1048576.0
        except Exception:
            return 0.0


def tree_mb():
    """This process plus the encoders it started (what the task manager shows for the program)."""
    try:
        import psutil
        me = psutil.Process()
        return (me.memory_info().rss + sum(c.memory_info().rss for c in me.children(recursive=True))) / 1048576.0
    except Exception:
        return rss_mb()


# ───────────────────────── the limit and how it is split ─────────────────────────
def limit_mb():
    return int(LIMIT_MB[0] or 0)


def set_limit(mb):
    LIMIT_MB[0] = max(0, int(mb or 0))


def base_mb():
    """What the program needs with nothing open (Python, Qt, libraries): measured once, early."""
    if _STATE["base_mb"] <= 0:
        _STATE["base_mb"] = max(150.0, rss_mb() or 300.0)
    return _STATE["base_mb"]


def budgets():
    """Bytes for each cache. The caches share what is left of the limit after the program itself (never less than 160 MB)."""
    lim = limit_mb()
    if lim <= 0:
        return {"preview": None, "fx": 200e6, "rig": 150e6, "img": 256e6, "mip": 96e6, "tex": 128e6, "frames": None}
    free = max(160.0, lim - base_mb()) * 1e6
    return {"preview": free * 0.30, "fx": free * 0.10, "rig": min(150e6, free * 0.08), "img": free * 0.10, "mip": free * 0.05,
            "tex": free * 0.12, "frames": free * 0.20}


def frame_cache_count(proj_w, proj_h, wanted):
    """How many decoded video frames each source may keep (CFG["frame_cache"] says what the user asked for): limited by the bytes."""
    b = budgets()["frames"]
    if not b: return wanted
    per = max(1, int(proj_w)) * max(1, int(proj_h)) * 4
    return max(2, min(int(wanted), int(b // per)))


def apply(renderer=None):
    """Push the budgets into the caches (called when the settings change and at start-up)."""
    b = budgets()
    try:
        from . import bone2d as B
        B.IMG_BUDGET = int(b["img"]); B.MIP_BUDGET = int(b["mip"]); B.RigSource.RIG_CACHE_BYTES = int(b["rig"])
    except Exception:
        pass
    try:
        from .renderer import Renderer
        Renderer.FX_BYTES = int(b["fx"])
        if b["preview"] is not None:
            for r in list(_RENDERERS) + ([renderer] if renderer is not None else []):
                if not getattr(r, "export_mode", False):
                    r.preview_cache_bytes = min(float(getattr(r, "preview_cache_bytes", b["preview"])), b["preview"])
    except Exception:
        pass
    try:
        from . import meshgl
        meshgl.TEX_BUDGET[0] = int(b["tex"])
    except Exception:
        pass


def register(renderer):
    _RENDERERS.add(renderer)


# ───────────────────────── trimming while it runs ─────────────────────────
def trim(level=1):
    """Give memory back: level 1 = the preview picture cache and effect pictures, 2 = everything that can be made again."""
    _STATE["trims"] += 1
    try:
        from . import bone2d as B
        with B._IMG_LOCK:
            B._IMG_CACHE.clear(); B._IMG_BYTES[0] = 0; B._MIP.clear(); B._MIP_BYTES[0] = 0
        with B._RIGS_LOCK:
            for rs in list(B._RIGS.values()):
                try:
                    with rs.lock: rs.cache.clear(); rs._cache_bytes = 0
                except Exception:
                    pass
    except Exception:
        pass
    for r in list(_RENDERERS):
        try:
            with r._cache_lock:
                keep = 0 if level >= 2 else max(1, len(r.preview_cache) // 4)
                while len(r.preview_cache) > keep: r._pc_bytes -= r.preview_cache.popitem(last=False)[1].nbytes
            r._fx_cache.clear(); r._fx_bytes = 0
            if level >= 2:
                for s in list(getattr(r.pool, "src", {}).values()):
                    for name in ("cache", "rawc"):
                        c = getattr(s, name, None)
                        if c is not None: c.clear()
        except Exception:
            pass
    gc.collect()
    _release_to_os()


def _release_to_os():
    """Python / numpy free memory to the C heap, which does not always return it to the system: ask it to."""
    try:
        if sys.platform.startswith("linux"):
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        elif os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetProcessWorkingSetSize(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


def check(force=False):
    """Cheap (reads the process size at most once a second). Trims the caches when the program is above its limit."""
    lim = limit_mb()
    if lim <= 0: return False
    now = time.monotonic()
    if not force and now - _STATE["last"] < 1.0: return False
    _STATE["last"] = now
    use = tree_mb()
    if use > lim:
        trim(2 if use > lim * 1.15 else 1); return True
    return False


# ───────────────────────── export ─────────────────────────
def encoder_mb(w, h, vcodec="libx264", preset="veryfast", hw=False):
    """Typical size of one encoder process (measured: x264 veryfast 1080p 235-295 MB, 4K 930-1000 MB, slow 1080p 480 MB)."""
    mp = max(0.1, w * h / 1e6)
    if hw: return 120.0 + 30.0 * mp
    k = {"ultrafast": 0.8, "superfast": 0.9, "veryfast": 1.0, "faster": 1.1, "fast": 1.2, "medium": 1.4, "slow": 1.6}.get(preset, 1.2)
    if vcodec in ("libsvtav1", "libaom-av1"): k = 1.8
    if vcodec == "libx265": k = max(k, 1.5)
    return (110.0 + 100.0 * mp) * k


def worker_mb(w, h):
    """One export thread: its frame queue, the decoders' read-ahead, the render buffers and its caches (all kept small in export mode)."""
    mp = max(0.1, w * h / 1e6)
    return 45.0 + mp * 3.0 * 14.0


def export_workers(wanted, w, h, vcodec="libx264", preset="veryfast", hw=False, gpu_composes=False):
    """How many pieces may be rendered at once so that the program plus its encoders stay under the limit (at least 1)."""
    lim = limit_mb()
    if lim <= 0: return max(1, int(wanted))
    free = lim - max(base_mb(), rss_mb()) - 40.0
    per = encoder_mb(w, h, vcodec, preset, hw) + worker_mb(w, h)
    return max(1, min(int(wanted), int(free // per)))

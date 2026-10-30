"""Performance helpers: how many threads the picture work may use, a lower priority for the render thread, and one
place that applies the performance settings (called at start and after the Settings window)."""
import os
import cv2
from ..shared.core import CFG


def cpu_count(): return os.cpu_count() or 4


def render_threads(setting):
    """0 = automatic: leave two hardware threads free for the window, audio and decoding."""
    n = int(setting or 0)
    return n if n > 0 else max(1, min(8, cpu_count() - 2))


def bg_threads(): return max(1, cpu_count() // 2)


def lower_thread_priority():
    """The render thread runs below the window thread, so the window stays smooth when the preview is heavy."""
    if os.name != "nt": return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k.SetThreadPriority(k.GetCurrentThread(), -1)      # THREAD_PRIORITY_BELOW_NORMAL
    except Exception: pass


def apply_perf(settings, renderer=None):
    try: cv2.setNumThreads(render_threads(settings["render_threads"]))
    except Exception: pass
    CFG["bg_threads"] = bg_threads()
    CFG["low_priority"] = bool(settings["low_priority"])
    CFG["proxy_hw"] = settings["proxy_hw"]
    CFG["audio_cache_gb"] = float(settings["audio_cache_gb"])
    if renderer is not None:
        renderer.preview_cache_bytes = float(settings["preview_ram_mb"]) * 1e6 * 0.6
    from .gpu import GPU
    GPU.set_mode(settings["gpu_compose"])

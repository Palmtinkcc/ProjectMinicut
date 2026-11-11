"""'Optimize for me': picks every render-related setting that suits this computer (GPU, CPU threads, RAM, disk, screen)."""
from . import sysinfo

EXPORT_PRESETS = [("quality", "Quality"), ("balance", "Balance"), ("fast", "Fast"), ("ultra", "Ultra fast"), ("rush", "Just don't waste my time")]
EXPORT_SPACE = [("Full space", 14), ("80%", 18), ("50%", 22), ("40%", 26), ("Space save", 30)]      # label, x264 CRF (lower = bigger file, better picture)
X264_PRESET = {"quality": "slow", "balance": "medium", "fast": "veryfast", "ultra": "ultrafast", "rush": "ultrafast"}
SVT_PRESET = {"quality": "4", "balance": "6", "fast": "8", "ultra": "10", "rush": "12"}
AOM_CPU_USED = {"quality": "3", "balance": "4", "fast": "6", "ultra": "8", "rush": "8"}
NVENC_PRESET = {"quality": "p7", "balance": "p5", "fast": "p4", "ultra": "p2", "rush": "p1"}
QSV_PRESET = {"quality": "slow", "balance": "medium", "fast": "fast", "ultra": "veryfast", "rush": "veryfast"}
AMF_QUALITY = {"quality": "quality", "balance": "balanced", "fast": "speed", "ultra": "speed", "rush": "speed"}
THREAD_CHOICES = (1, 2, 3, 4, 6, 8)
FPS_CHOICES = (24, 30, 60)
RAM_CHOICES = (128, 256, 512, 1024, 2048)


def export_crf(space_index):
    return EXPORT_SPACE[max(0, min(len(EXPORT_SPACE) - 1, int(space_index)))][1]


def _pick(choices, want, lowest_ok=False):
    ok = [c for c in choices if c <= want]
    return max(ok) if ok else min(choices)


def tier(hw):
    """0 = modest, 1 = middle, 2 = strong: GPU counts most, then the CPU, then the memory."""
    g = 2 if sysinfo.is_discrete(hw.gpu) else (1 if hw.gpu else 0)
    c = 2 if hw.cores >= 16 else (1 if hw.cores >= 8 else 0)
    r = 2 if (hw.ram or 8) >= 30 else (1 if (hw.ram or 8) >= 14 else 0)
    score = g * 0.5 + c * 0.3 + r * 0.2
    return 2 if score >= 1.45 else (1 if score >= 0.7 else 0)


def recommend(hw, screen_hz, gpu_status, free_gb):
    """-> (values, lines). values: settings key -> value (what 'Use this Setting' applies). lines: [(label, text)] for the summary box."""
    t = tier(hw); ram = hw.ram or 8.0; cores = max(1, hw.cores); st = (gpu_status or "").lower()
    gl_bad = st.startswith("off") and "cpu only" not in st and "no opengl surface" not in st
    api = "off" if gl_bad else "auto"
    pq = (0.5, 0.75, 1.0)[t]
    fps = _pick(FPS_CHOICES, min(60, int(screen_hz or 60)) if t >= 1 else 30)
    cache = (24, 48, 96)[t]
    if ram < 8: cache = min(cache, 16)
    ram_mb = 256 if ram < 8 else 512 if ram < 16 else 1024 if ram < 32 else 2048
    threads = 0 if cores >= 8 else max(1, cores - 1)
    threads = threads if threads == 0 else _pick(THREAD_CHOICES, threads)
    v = {"gpu_compose": api, "preview_quality": pq, "preview_fps": fps, "frame_cache": cache, "preview_ram_mb": ram_mb,
         "render_threads": threads, "proxy_preview": True, "proxy_height": (360, 540, 720)[t], "proxy_quality": (28, 23, 23)[t],
         "play_reduce": t == 0, "bake": t >= 1, "adaptive_preview": True, "fx_adapt": True, "fit_viewport": True, "low_priority": True,
         "hw_decode": sysinfo.vendor(hw.gpu) in ("nvidia", "amd", "intel"), "encode_hw": "auto",
         "export_parallel": max(1, min((1, 2, 3)[t], cores // 4)), "export_preset": ("fast", "balance", "quality")[t], "export_space": 2 if t < 2 else 1}
    if free_gb is not None: v["proxy_budget_gb"] = int(max(25, min(50, free_gb * 0.1)))
    crf = export_crf(v["export_space"])
    lines = [("API", "OpenGL" if api != "off" else "CPU"), ("Quality", "%d" % round(pq * 100)),
             ("Export", "%s \u00b7 CRF %d" % (dict(EXPORT_PRESETS)[v["export_preset"]], crf)),
             ("Proxy", "on \u00b7 %dp" % v["proxy_height"]), ("Adaptive Proxy", "on" if v["bake"] else "off")]
    return v, lines

"""The GPU memory ceiling for THIS machine (Patch 58). Pure arithmetic: no Qt, no GL, no psutil import at module level, so every kind of machine can be tested with numbers.

Inputs (all optional, any may be None):
  snap       the dict of vram.VramInfo.snapshot(): total (dedicated bytes), budget (what Windows lets this program use now), shared (True = integrated GPU)
  ram_total, ram_avail   system memory in bytes
  env_mb     MINICUT_VRAM_CAP_MB (the user's own number always wins)

Rules (the result is the HARD ceiling of gpuledger.py: it is not a target, it is where leaks and loops are stopped; the cache plans with 80 % of it):
  discrete card     0.75 x budget (or 0.60 x total when no budget is known), never above 0.80 x total   4 GB RX 580 -> ~2.5 GB, 2 GB card -> ~1.3 GB, 1 GB card -> ~0.6 GB
  integrated GPU    its "video memory" IS system RAM: 0.25 x the RAM that is free now, at most 1.5 GB      8 GB machine with 5 GB free -> 1.25 GB
  nothing known     1 GB
  always            at least 256 MB (less and nothing works), at most 6 GB
"""
MB = 1024 * 1024
FLOOR = 256 * MB
CEIL = 6 * 1024 * MB
UNKNOWN = 1024 * MB
IGPU_MAX = int(1.5 * 1024 * MB)
IGPU_FRAC_OF_FREE_RAM = 0.25
CACHE_FRAC = 0.80                         # the picture cache plans with this share of the ceiling (rmgr.ResourceManager.allowed)
RAM_NEEDED_FOR_CPU = 1536 * MB            # free RAM that must be there before the program moves its drawing to the CPU


def compute(snap=None, ram_total=None, ram_avail=None, env_mb=None):
    if env_mb:
        try: return max(64, int(env_mb)) * MB
        except Exception: pass
    snap = snap or {}; total = snap.get("total"); budget = snap.get("budget"); shared = bool(snap.get("shared"))
    if shared:
        base = ram_avail * IGPU_FRAC_OF_FREE_RAM if ram_avail else (ram_total * 0.12 if ram_total else UNKNOWN)
        cap = min(base, IGPU_MAX)
        if budget: cap = min(cap, 0.75 * budget)
    elif total or budget:
        cap = 0.75 * budget if budget else 0.60 * total
        if total: cap = min(cap, 0.80 * total)
    else:
        cap = UNKNOWN
    return int(min(CEIL, max(FLOOR, cap)))


def ram_ok(ram_avail):
    """May the drawing move to the CPU? Only when the machine has the memory for it (the CPU path lives in RAM)."""
    return ram_avail is not None and ram_avail >= RAM_NEEDED_FOR_CPU


def system_ram():
    """(total, available) bytes from psutil, or (None, None)."""
    try:
        import psutil
        m = psutil.virtual_memory(); return int(m.total), int(m.available)
    except Exception: return None, None

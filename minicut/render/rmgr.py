"""Resource Manager (render core, step 2): how much video memory the engine of one render thread may hold.

The limit is not a number written in the program. It is worked out from what the machine says (render/vram.py), again every half second:

    allowed = what this program holds now + the headroom the system reports - a reserve left to the system and the other programs
    capped at 70 % (preview) / 50 % (export) of the budget the system gives this program
    scaled down by `penalty` after the driver ran out of memory (it recovers slowly)
    an integrated GPU, or a machine that tells nothing: the RAM governor's number (meshgl.TEX_BUDGET, set from "Max RAM") is the cap, as before

cache_budget() is what is left for the picture-texture cache after the render targets and pools (which cannot be given back mid-frame).
Plain Python, no OpenGL here: the engine asks and obeys. Everything is cheap to call (the system is asked at most every `period` seconds).
"""
import time

MB = 2 ** 20


class ResourceManager:
    FLOOR = 96 * MB              # the least that is ever allowed on a machine that reports a size (a 1080p frame is 8 MB)
    CACHE_FLOOR = 32 * MB        # the least that is left for the picture cache
    RESERVE_MIN = 256 * MB       # always left to the system and the other programs
    RESERVE_FRAC = 0.12
    CAP_PREVIEW = 0.70
    CAP_EXPORT = 0.50

    def __init__(self, vram, export=False, ram_cap=None, clock=time.monotonic, period=0.5, hard_cap=None):
        self.hard_cap = hard_cap; self.vram = vram; self.export = bool(export); self.ram_cap = ram_cap or (lambda: 128 * MB)
        self.clock = clock; self.period = period
        self.penalty = 1.0; self.ooms = 0; self._last_oom = -1e9
        self._snap = None; self._snap_t = -1e9; self._used0 = 0.0        # _used0: what the engine held when the snapshot was taken

    def snapshot(self, used=0.0):
        now = self.clock()
        if self._snap is None or now - self._snap_t >= self.period:
            self._snap = self.vram.snapshot() if self.vram is not None else {"total": None, "budget": None, "usage": None, "headroom": None, "shared": False, "source": "none"}
            self._snap_t = now; self._used0 = float(used)
            if self.penalty < 1.0 and now - self._last_oom > 30.0: self.penalty = min(1.0, self.penalty * 1.15)       # slow recovery
        return self._snap

    def allowed(self, used):
        """Bytes of video memory this engine may hold in total (cached for `period` seconds)."""
        s = self.snapshot(used)
        ram = float(self.ram_cap())
        if s["headroom"] is not None and not s["shared"]:
            ref = s["budget"] or s["total"] or 0
            reserve = max(self.RESERVE_MIN, self.RESERVE_FRAC * ref)
            a = self._used0 + s["headroom"] - reserve               # (the headroom belongs to the moment of the snapshot)
            if ref: a = min(a, (self.CAP_EXPORT if self.export else self.CAP_PREVIEW) * ref)
            a = max(a, self.FLOOR)
        elif s["headroom"] is not None:                            # an integrated GPU: the RAM governor's number is the cap
            reserve = max(self.RESERVE_MIN, self.RESERVE_FRAC * (s["budget"] or 0))
            a = min(self._used0 + s["headroom"] - reserve, ram); a = max(a, 48 * MB)
        else:                                                       # nothing is known: the RAM governor's number, as before Patch 51
            a = max(ram, 48 * MB)
        if self.hard_cap is not None:                               # Patch 58: never plan above the ceiling the ledger enforces (else the cache and the ledger fight)
            try: a = min(a, 0.80 * float(self.hard_cap()))
            except Exception: pass
        return a * self.penalty

    def cache_budget(self, used, fixed):
        """Bytes the picture-texture cache may hold: the allowed total minus the targets and pools (`fixed`)."""
        return max(self.CACHE_FLOOR * self.penalty, self.allowed(used) - fixed)

    def note_oom(self):
        """The driver said out of memory: take less from now on (the engine also empties its caches)."""
        self.ooms += 1; self.penalty = max(0.25, self.penalty * 0.6); self._last_oom = self.clock()

    def stats(self, used):
        s = self.snapshot(used); a = self.allowed(used)
        mb = lambda v: None if v is None else round(v / MB)
        return {"source": s["source"], "allowed_mb": mb(a), "used_mb": mb(used), "headroom_mb": mb(s["headroom"]), "budget_mb": mb(s["budget"]), "total_mb": mb(s["total"]),
                "shared": bool(s["shared"]), "penalty": round(self.penalty, 3), "ooms": self.ooms}

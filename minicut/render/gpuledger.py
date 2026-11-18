"""GPU memory ledger (Patch 57): every texture / buffer / renderbuffer made through a moderngl context is counted, and a hard ceiling is enforced.

Why: the Resource Manager (rmgr.py) only limits the picture-texture cache. Rig atlases, render targets and pools were not counted, so a leak (Patch 56) or a
runaway loop could take all of the video memory and freeze Windows. Windows has no per-process video-memory limit, so the limit has to be ours:

    before a resource is made:  live bytes + the new bytes > cap  ->  on_pressure() (the engine gives back idle caches / pools)  ->  still over?
                                raise GpuBudgetError. The message contains "memory", so meshgl._alloc() also runs its own shrink-and-retry, and
                                the error goes to the error hub (pop-up + circuit breaker) instead of reaching the driver.

What it counts: objects made by ctx.texture / buffer / renderbuffer / depth_texture / depth_renderbuffer / simple_framebuffer (their size is computed from
the arguments, mipmaps not included: a mipmapped texture is really ~34 % bigger, so keep the cap below what you can really afford).
What it does not count: Qt's own OpenGL contexts (the Bone2D editor canvas and the Qt compositor) and what the driver keeps for itself.
A resource counts until it is released with release(). The ledger keeps a strong reference to every live object (moderngl's default gc_mode None never frees a
dropped object, so a leaked object really keeps its video memory; forgetting it would hide the leak). Only when the ceiling would be crossed, and after the engine
gave back its idle caches, the objects that nobody else references are released (reap): that is a leak by definition, and it is reported through on_reap.
No Qt, no moderngl import here: it works on any object that has the moderngl attributes (tested with fakes).
"""
import os, re, sys, threading

MB = 1024 * 1024
DEFAULT_CAP_MB = 6144


class GpuBudgetError(RuntimeError):
    """Raised instead of making a resource that would cross the ceiling. Not a driver error: nothing was allocated."""


def _bytes_per_component(dtype):
    m = re.search(r"(\d+)$", str(dtype or "f1")); return max(1, int(m.group(1))) if m else 1


def est_texture(size, components=4, dtype="f1", samples=0, **kw):
    w, h = int(size[0]), int(size[1]); return w * h * int(components or 4) * _bytes_per_component(dtype) * max(1, int(samples or 1))


def est_renderbuffer(size, components=4, samples=0, dtype="f1", **kw): return est_texture(size, components, dtype, samples)
def est_depth(size, samples=0, **kw): return int(size[0]) * int(size[1]) * 4 * max(1, int(samples or 1))


def _alive(obj):
    """moderngl swaps `mglo` for an InvalidObject when an object is released."""
    return type(getattr(obj, "mglo", None)).__name__ != "InvalidObject"


class Ledger:
    def __init__(self, cap_bytes=DEFAULT_CAP_MB * MB, is_alive=_alive):
        self.cap = int(cap_bytes); self.is_alive = is_alive; self.peak = 0; self.refused = 0
        self._objs = {}; self._lock = threading.RLock(); self._pressure_busy = threading.local(); self.on_reap = None; self.reaped = 0; self.cap_provider = None

    def limit(self):
        """The ceiling in force now: the smaller of the fixed `cap` and what the machine allows (cap_provider: render/gpucap.py, set by the engine)."""
        lim = self.cap
        if self.cap_provider is not None:
            try: lim = min(lim, int(self.cap_provider()))
            except Exception: pass
        return lim

    def set_cap(self, cap_bytes):
        with self._lock: self.cap = max(64 * MB, int(cap_bytes))

    def live_bytes(self):
        with self._lock:
            dead = [k for k, (o, n, kind) in self._objs.items() if not self.is_alive(o)]
            for k in dead: del self._objs[k]
            return sum(n for _, n, _k in self._objs.values())

    def by_kind(self):
        with self._lock:
            self.live_bytes(); out = {}
            for _, n, kind in self._objs.values(): out[kind] = out.get(kind, 0) + n
            return out

    def _refcounts(self):
        """[(key, reference count)] of the live objects, counted in ONE fixed code shape so that _base (measured below with a probe) is exact on this Python version."""
        out = []
        for k, (o, n, kind) in list(self._objs.items()):
            if self.is_alive(o): out.append((k, sys.getrefcount(o)))
        return out

    def _orphans(self):
        base = _base_refs()
        return [k for k, c in self._refcounts() if c <= base]

    def orphan_bytes(self):
        """Bytes of objects that only the ledger still references (leaked: nobody can use or release them any more)."""
        with self._lock: return sum(self._objs[k][1] for k in self._orphans())

    def reap(self):
        """Release every orphan. Returns (bytes, count). Only called under pressure: an object nobody references cannot be drawn with any more."""
        freed = cnt = 0
        with self._lock:
            for k in self._orphans():
                o, n, kind = self._objs[k]
                try: o.release()
                except Exception: continue
                freed += n; cnt += 1; del self._objs[k]
        if cnt:
            self.reaped += cnt
            if self.on_reap is not None:
                try: self.on_reap(freed, cnt)
                except Exception: pass
        return freed, cnt

    def register(self, obj, nbytes, kind):
        with self._lock:
            self._objs[id(obj)] = (obj, int(nbytes), kind); self.peak = max(self.peak, self.live_bytes())

    def check(self, nbytes, kind, on_pressure=None):
        """Raise GpuBudgetError when `nbytes` more would cross the cap. Before refusing: the owner gives idle memory back, then leaked objects are released."""
        nbytes = int(nbytes); lim = self.limit()
        if self.live_bytes() + nbytes <= lim: return
        if on_pressure is not None and not getattr(self._pressure_busy, "on", False):
            self._pressure_busy.on = True
            try: on_pressure(nbytes)
            except Exception: pass
            finally: self._pressure_busy.on = False
            if self.live_bytes() + nbytes <= lim: return
        self.reap()
        if self.live_bytes() + nbytes <= lim: return
        self.refused += 1
        raise GpuBudgetError("GPU memory budget exceeded: %s of %.0f MB would make %.0f MB, the ceiling is %.0f MB" % (kind, nbytes / MB, (self.live_bytes() + nbytes) / MB, lim / MB))

    def wrap(self, ctx, on_pressure=None):
        """Replace the creating methods of `ctx` by counting ones (instance attributes; the class is untouched). Safe to call once per context."""
        if getattr(ctx, "_ledger_wrapped", False): return ctx
        led = self

        def counted(name, kind, estimate):
            orig = getattr(ctx, name)
            def fn(*a, **kw):
                try: nbytes = estimate(*a, **kw)
                except Exception: nbytes = 0
                led.check(nbytes, kind, on_pressure)
                obj = orig(*a, **kw)
                if nbytes: led.register(obj, nbytes, kind)
                return obj
            setattr(ctx, name, fn)

        def e_texture(size, components=4, data=None, samples=0, alignment=1, dtype="f1", **kw): return est_texture(size, components, dtype, samples)
        def e_buffer(data=None, reserve=0, dynamic=False, **kw):
            if data is not None:
                try: return memoryview(data).nbytes
                except Exception:
                    try: return len(data)
                    except Exception: return 0
            return int(reserve or 0)
        def e_rbuf(size, components=4, samples=0, dtype="f1", **kw): return est_renderbuffer(size, components, samples, dtype)
        def e_depth_tex(size, data=None, samples=0, alignment=4, **kw): return est_depth(size, samples)
        def e_depth_rb(size, samples=0, **kw): return est_depth(size, samples)
        def e_simple_fb(size, components=4, samples=0, dtype="f1", **kw): return est_renderbuffer(size, components, samples, dtype) + est_depth(size, samples)
        for name, kind, est in (("texture", "texture", e_texture), ("buffer", "buffer", e_buffer), ("renderbuffer", "renderbuffer", e_rbuf),
                                ("depth_texture", "depth texture", e_depth_tex), ("depth_renderbuffer", "depth renderbuffer", e_depth_rb), ("simple_framebuffer", "framebuffer", e_simple_fb)):
            if hasattr(ctx, name):
                try: counted(name, kind, est)
                except Exception: pass
        try: ctx._ledger_wrapped = True
        except Exception: pass
        return ctx


class _Probe:
    def __init__(self): self.mglo = object()


_BASE = []


def _base_refs():
    """The reference count an object has when ONLY the ledger holds it. Measured, not assumed: the count differs between Python versions."""
    if not _BASE:
        t = Ledger(); p = _Probe(); t.register(p, 1, "probe"); del p
        _BASE.append(t._refcounts()[0][1])
    return _BASE[0]


def _cap_from_env():
    """MINICUT_VRAM_CAP_MB is a fixed cap; without it only the machine's own ceiling (gpucap.compute) applies. 6 GB is the absolute top."""
    try: return max(64, int(os.environ["MINICUT_VRAM_CAP_MB"])) * MB
    except Exception: return 6 * 1024 * MB


LEDGER = Ledger(_cap_from_env())

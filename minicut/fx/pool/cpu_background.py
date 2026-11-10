"""Background effects: patterns made from nothing. They replace the picture, go behind it or blend with it (Blend)."""
from .cpu_kit import *

BG = "Background"
def BGP(extra=(), speed=0.5): return list(extra) + [F("scale", "Scale", 50, 5, 200), SPEED(speed, 10), MODE("replace"), OPAC(100), SEED()]


def bgfx(gen):
    def fn(img, p, ctx):
        h, w = img.shape[:2]; pat, pa = gen(h, w, p, ctx, ctx.lt * p["speed"]); return blend(img, np.clip(pat, 0, 1).astype(np.float32), pa, p["mode"], p["opacity"] / 100.0)
    return fn
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def sc(ctx, p): return S(ctx, p["scale"]) * 2.0          # a feature of about this many pixels
def pal3(p, v): return ramp(v, [(0.0, p["c1"]), (0.5, p["c2"]), (1.0, p["c3"])])
CP3 = [C("c1", "Color 1", "#0b1026"), C("c2", "Color 2", "#7b2ff7"), C("c3", "Color 3", "#22d3ee")]


_PAL = {"thermal": [(0, "#050018"), (0.25, "#4b00a0"), (0.5, "#e0004b"), (0.75, "#ffb000"), (1, "#ffffe0")], "viridis": [(0, "#440154"), (0.5, "#21908d"), (1, "#fde725")], "cool": [(0, "#03045e"), (0.5, "#00b4d8"), (1, "#caf0f8")]}


# ------------------------------------------------------------------ procedural
PR = "Procedural"


def _bolt(r, a, b, n, jit):
    pts = [np.array(a, np.float32), np.array(b, np.float32)]
    for _ in range(n):
        new = [pts[0]]
        for i in range(len(pts) - 1):
            m = (pts[i] + pts[i + 1]) / 2; d = pts[i + 1] - pts[i]; nrm = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6); new += [m + nrm * r.normal(0, jit * np.linalg.norm(d) * 0.35), pts[i + 1]]
        pts = new
    return np.array(pts)


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

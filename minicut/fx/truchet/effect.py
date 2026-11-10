"""truchet: Truchet checker board. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_truchet(h, w, p, ctx, t):
    x, y = coords(h, w); s = sc(ctx, p) * 0.45; u = x / s + t * 0.2; v = y / s; i = np.floor(u).astype(int); j = np.floor(v).astype(int); fx = u - i; fy = v - j
    bit = ((i * 73856093) ^ (j * 19349663) ^ (int(p["seed"]) * 83492791)) & 1; d1 = np.where(bit == 0, np.hypot(fx, fy), np.hypot(1 - fx, fy)); d2 = np.where(bit == 0, np.hypot(1 - fx, 1 - fy), np.hypot(fx, 1 - fy))
    d = np.minimum(np.abs(d1 - 0.5), np.abs(d2 - 0.5)); line = 1 - sm(d, p["thick"] / 200.0 - 0.02, p["thick"] / 200.0 + 0.02)
    if p["fill"]: ins = ((np.minimum(d1, d2) < 0.5) ^ (((i + j) & 1) == 1)).astype(np.float32); m = np.clip(ins * (1 - 0.0) + 0 * line, 0, 1)
    else: m = line
    m = np.asarray(m, np.float32)[..., None]; return bgr(p["c1"]) * (1 - m) + bgr(p["c2"]) * m, None

reg("truchet", BG, "Truchet checker board", BGP([F("thick", "Line width", 20, 2, 100), B("fill", "Filled checker", False), C("c1", "Color 1", "#0d1321"), C("c2", "Color 2", "#f0a202")]), bgfx(g_truchet), "A maze of arcs made from tiles, or a checker board with curved edges.", "maze arcs tiles")

ID = "truchet"

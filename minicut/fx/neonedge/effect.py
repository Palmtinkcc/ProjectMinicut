"""neonedge: Neon edge. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_neonedge(img, p, ctx):
    e = edges(img, ctx, 1.2); col = bgr(p["color"]); core = sm(e, 0.08, 0.35); gl = glow_of(core, p["glow"] * ctx.k * 0.3) * 2.2 + glow_of(core, p["glow"] * ctx.k) * 1.4; f = f3(img) * (1 - p["dim"] / 100.0)
    return pack(np.clip(f + (gl[..., None] * col) + core[..., None] * 0.7, 0, 1), like=img)

reg("neonedge", SS, "Neon edge", [C("color", "Color", "#ff2bd6"), F("glow", "Glow", 12, 1, 60), F("dim", "Darken picture", 70, 0, 100)], fx_neonedge, "The edges glow like neon tubes on a darkened picture.", "glow outline tron")

ID = "neonedge"

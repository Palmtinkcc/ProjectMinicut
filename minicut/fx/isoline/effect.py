"""isoline: Isoline. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_iso(h, w, p, ctx, t):
    f = fbm(h, w, sc(ctx, p) * 2, int(p["seed"]), t, 3); v = np.abs(np.sin(f * np.pi * p["levels"])); line = 1 - sm(v, 0.0, p["width"] / 100.0 * 0.6 + 0.03); return bgr(p["c1"]) * (1 - line[..., None]) + bgr(p["c2"]) * line[..., None], None

reg("isoline", BG, "Isoline", BGP([I("levels", "Lines", 8, 2, 40), F("width", "Line width", 20, 1, 100), C("c1", "Background", "#0e1a14"), C("c2", "Lines", "#6dffb0")]), bgfx(g_iso), "Contour lines like a map of hills, slowly changing.", "contour topographic map")

ID = "isoline"

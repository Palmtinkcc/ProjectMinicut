"""cosweb: Cosine web. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_cosweb(h, w, p, ctx, t):
    x, y = norm_coords(h, w); k = 130.0 / max(5.0, p["scale"])
    v = np.cos(x * k * 6 + t) + np.cos(y * k * 6 - t * 0.8) + np.cos((x + y) * k * 4 + t * 0.5) + np.cos(np.sqrt(x * x + y * y) * k * 8 - t); lines = 1 - sm(np.abs(v), 0.02, 0.02 + p["width"] / 100.0 * 0.5)
    return bgr(p["c1"]) * (1 - lines[..., None]) + bgr(p["c2"]) * lines[..., None], None

reg("cosweb", BG, "Cosine web", BGP([F("width", "Line width", 30, 2, 100), C("c1", "Background", "#070b1f"), C("c2", "Lines", "#4fd1ff")]), bgfx(g_cosweb), "A web of glowing lines made from overlapping waves.", "lines waves interference")

ID = "cosweb"

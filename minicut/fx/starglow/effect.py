"""starglow: Star glow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_starglow(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); t = ctx.lt * p["speed"]
    for i in range(int(p["count"])):
        x, y = r.random() * w, r.random() * h; ph = r.random() * 6.28; tw = max(0, np.sin(t * 2 + ph)); rad = S(ctx, p["size"]) * (0.5 + r.random()) * 2.5 * tw
        if rad > 1: _star(cv, x, y, rad, tw, col)
    return _fin(img, cv, 4, p, ctx)

reg("starglow", PT, "Star glow", PTP(), fx_starglow, "Twinkling four-point stars with a soft glow.", "sparkle twinkle")

ID = "starglow"

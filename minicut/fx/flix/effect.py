"""flix: Flix texture. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_flix(h, w, p, ctx, t):
    s = sc(ctx, p); f = noise2(h, w, s * 8, s * 0.15 + 2, int(p["seed"]), t) * 0.6 + noise2(h, w, s * 3, s * 0.1 + 2, int(p["seed"]) + 3, t * 1.5) * 0.4; fl = 0.85 + 0.15 * np.sin(ctx.lt * 40) * p["flicker"] / 100.0
    return pal3(p, np.clip(f * fl, 0, 1)), None

reg("flix", BG, "Flix texture", BGP([F("flicker", "Flicker", 40, 0, 100)] + CP3), bgfx(g_flix), "Streaky, flickering light bars like a projected film leader or light leak.", "streaks light leak film")

ID = "flix"

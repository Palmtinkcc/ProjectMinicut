"""warptex: Warp texture. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_warptex(h, w, p, ctx, t):
    s = sc(ctx, p); x, y = coords(h, w); wx = (fbm(h, w, s * 3, int(p["seed"]), t, 3) - 0.5) * s * p["warp"] / 10.0; wy = (fbm(h, w, s * 3, int(p["seed"]) + 7, t, 3) - 0.5) * s * p["warp"] / 10.0
    u = (x + wx) / s; v = (y + wy) / s
    m = (np.floor(u) + np.floor(v)) % 2 if p["pattern"] == "checker" else (np.sin(u * np.pi * 2) > 0).astype(np.float32); m = np.asarray(m, np.float32)[..., None]; return bgr(p["c1"]) * (1 - m) + bgr(p["c2"]) * m, None

reg("warptex", BG, "Warp texture", BGP([F("warp", "Warp", 40, 0, 100), CH("pattern", "Pattern", "checker", [("checker", "Checker"), ("stripes", "Stripes")]), C("c1", "Color 1", "#1a1a2e"), C("c2", "Color 2", "#e94560")]), bgfx(g_warptex), "A checker or stripe pattern bent and swirled by noise.", "distorted checker")

ID = "warptex"

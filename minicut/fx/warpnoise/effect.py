"""warpnoise: Warped noise field. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_warpnoise(h, w, p, ctx, t):
    s = sc(ctx, p) * 2; sd = int(p["seed"]); q = np.stack([fbm(h, w, s, sd, t * 0.5, 3), fbm(h, w, s, sd + 5, t * 0.5, 3)], -1)
    f = fbm(h, w, s * 0.7, sd + 11, t * 0.3 + float(q[..., 0].mean()) * 3, 3); f = f * 0.6 + q[..., 0] * 0.25 + q[..., 1] * 0.25 + (q[..., 0] - 0.5) * p["warp"] / 80.0; f = np.clip((f - 0.5) * 3.0 + 0.5, 0, 1); return pal3(p, f), None

reg("warpnoise", BG, "Warped noise field", BGP([F("warp", "Warp", 50, 0, 100)] + CP3), bgfx(g_warpnoise), "Smoke-like colored noise that is twisted by more noise.", "domain warp marble smoke")

ID = "warpnoise"

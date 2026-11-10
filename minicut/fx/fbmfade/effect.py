"""fbmfade: FBM time displace fade. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_fbmfade(img, p, ctx):
    h, w = img.shape[:2]; per = max(0.2, p["period"]); env = 0.5 - 0.5 * np.cos(2 * np.pi * ctx.lt / per); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; dx = (fbm(h, w, s, int(p["seed"]), t, 4) - 0.5) * 2; dy = (fbm(h, w, s, int(p["seed"]) + 4, t, 4) - 0.5) * 2
    return displace(img, dx * p["amount"] * ctx.k * env, dy * p["amount"] * ctx.k * env)

reg("fbmfade", LN, "FBM time displace fade", [F("amount", "Amount", 70, 0, 300), F("size", "Size", 130, 10, 600), F("period", "Fade in and out every (s)", 4, 0.5, 30), F("speed", "Speed", 0.5, 0, 6), SEED()], fx_fbmfade, "A swirling distortion that fades in and out over time.", "noise warp pulse")

ID = "fbmfade"

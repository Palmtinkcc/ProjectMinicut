"""liquidwipe: Liquid wipe. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_liquidwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); a = np.deg2rad(p["angle"]); d = (x - w / 2) * np.cos(a) + (y - h / 2) * np.sin(a); ext = abs(w * np.cos(a)) + abs(h * np.sin(a)); wob = (fbm(h, w, S(ctx, 70), int(p["seed"]), ctx.lt * 0.8, 3) - 0.5) * ext * p["wobble"] / 100.0 + np.sin(coords(h, w)[1] / S(ctx, 40) + ctx.lt * 3) * ext * 0.01
    pos = (pr * 1.2 - 0.1) * ext - ext / 2; m = sm(d + wob, pos - 1.5, pos + 1.5); rim = np.clip(1 - np.abs(d + wob - pos) / (S(ctx, 10)), 0, 1) ** 2; out = _am(img, m); return blend(out, np.ones((h, w, 3), np.float32), rim * 0.6 * m, "add", 1.0)

reg("liquidwipe", WP, "Liquid wipe", WIPE(40) + [F("angle", "Direction", 0, -180, 180), F("wobble", "Wobble", 25, 0, 100), SEED()], fx_liquidwipe, "A wavy, liquid edge sweeps across and removes the picture.", "wave transition sweep")

ID = "liquidwipe"

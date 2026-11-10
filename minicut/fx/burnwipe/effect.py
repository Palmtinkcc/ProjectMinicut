"""burnwipe: Burning wipe. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_burnwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = fbm(h, w, S(ctx, p["scale"]) * 2, int(p["seed"]), 0, 5); y = 1 - coords(h, w)[1] / h; f = n * 0.55 + y * 0.45; t = pr * 1.3 - 0.15; burnt = f < t; edge = np.clip(1 - np.abs(f - t) / (p["edge"] / 100.0 * 0.12 + 1e-3), 0, 1)
    out = _am(img, (~burnt).astype(np.float32)); ember = ramp(edge, [(0, "#1a0500"), (0.4, "#ff2a00"), (0.75, "#ff9a00"), (1.0, "#fff1a8")]); inside = (edge > 0) & (~burnt | (edge > 0.5)); lay = np.where(inside[..., None], ember, 0)
    ch = np.clip((f - t) / 0.06, 0, 1) < 1; return blend(out, lay.astype(np.float32), np.clip(edge * 1.3, 0, 1) * (img[..., 3] * (1 / 255)), "over", 1.0)

reg("burnwipe", WP, "Burning wipe", WIPE(40) + [F("scale", "Noise size", 30, 5, 200), F("edge", "Fire width", 50, 5, 100), SEED()], fx_burnwipe, "The picture burns away from the bottom with a glowing fire edge.", "fire burn")

ID = "burnwipe"

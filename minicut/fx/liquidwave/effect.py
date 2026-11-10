"""liquidwave: Liquid wave. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_liquidwave(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; s = S(ctx, p["length"]); a = p["amount"] * ctx.k
    dx = (np.sin(y / s + t) + np.sin(x / (s * 1.7) - t * 0.8) * 0.6) * a; dy = (np.sin(x / s + t * 1.2) + np.sin(y / (s * 1.4) + t * 0.5) * 0.6) * a; return remap(img, x + dx, y + dy)

reg("liquidwave", WG, "Liquid wave", [F("amount", "Amount", 10, 0, 100), F("length", "Wave length", 50, 5, 400), F("speed", "Speed", 0.5, 0, 5)], fx_liquidwave, "A slow liquid wobble across the whole picture.", "jelly wobble")

ID = "liquidwave"

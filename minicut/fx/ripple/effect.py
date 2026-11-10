"""ripple: Circular ripple. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_ripple(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); L = S(ctx, p["length"]); t = ctx.lt * p["speed"]; env = np.exp(-r / (min(w, h) * p["reach"] / 100.0 * 2)) if p["reach"] < 200 else 1.0
    return sample_polar(img, cx, cy, np.maximum(0, r + np.sin(r / L * 2 * np.pi - t * 2 * np.pi) * p["amount"] * ctx.k * env), a)

reg("ripple", DW, "Circular ripple", [F("amount", "Height", 12, 0, 100), F("length", "Wave length", 40, 5, 300), F("speed", "Speed", 1.0, -5, 5), F("reach", "Reach", 100, 10, 200)] + CEN(), fx_ripple, "Rings spread from a point like a stone dropped in water.", "concentric shockwave")

ID = "ripple"

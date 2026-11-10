"""waterwave: Water wave. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_waterwave(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; s = S(ctx, p["length"]); wx = np.sin(y / s + t) * p["ax"] * ctx.k; wy = np.sin(x / s * 0.8 - t) * p["ay"] * ctx.k; out = remap(img, x + wx, y + wy); sh = np.cos(y / s + t) * p["shade"] / 100.0 * 0.15; f = f3(out) * (1 + sh[..., None]); return pack(np.clip(f, 0, 1), like=out)

reg("waterwave", WG, "Water wave", [F("ax", "Sideways", 8, 0, 100), F("ay", "Up and down", 6, 0, 100), F("length", "Wave length", 45, 5, 300), F("shade", "Light and dark", 40, 0, 100), F("speed", "Speed", 0.6, 0, 5)], fx_waterwave, "Looking at the picture through gently moving water.", "underwater")

ID = "waterwave"

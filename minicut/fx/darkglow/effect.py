"""darkglow: Dark glow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_darkglow(img, p, ctx):
    f = f3(img); d = np.clip((1 - lum(f) - p["threshold"] / 100.0) / max(1e-3, 1 - p["threshold"] / 100.0), 0, 1); g = np.clip(glow_of(d, p["radius"] * ctx.k) * 3, 0, 1)[..., None] * (p["amount"] / 100.0)
    col = bgr(p["color"]); return pack(f * (1 - g) + col * g, like=img)

reg("darkglow", C1, "Dark glow", [F("amount", "Amount", 70, 0, 100), F("radius", "Radius", 25, 1, 100), F("threshold", "Dark from", 55, 0, 95), C("color", "Color", "#000000")], fx_darkglow, "A glow of darkness around the dark parts (the opposite of Glow).", "shadow halo")

ID = "darkglow"

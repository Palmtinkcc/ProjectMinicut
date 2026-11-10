"""scanline: Scanline. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_scanline(img, p, ctx):
    h, w = img.shape[:2]; y = np.arange(h, dtype=np.float32); sp = S(ctx, p["spacing"]); ph = (y / sp + ctx.lt * p["roll"]) % 1.0; dark = np.clip(1 - np.abs(ph - 0.5) * 2 * (1 / max(0.05, p["thickness"] / 100.0)) + 0.0, 0, 1)
    m = 1 - (1 - dark) * (p["intensity"] / 100.0); f = f3(img) * m[:, None, None] + bgr(p["color"]) * ((1 - m)[:, None, None] * 0); return pack(np.clip(f, 0, 1), like=img)

reg("scanline", V, "Scanline", [F("spacing", "Spacing", 4, 2, 40), F("thickness", "Line thickness", 50, 5, 100), F("intensity", "Darkness", 55, 0, 100), F("roll", "Lines move", 0.0, -20, 20), C("color", "Color", "#000000")], fx_scanline, "Dark horizontal lines over the picture, like a TV screen.", "lines tv crt")

ID = "scanline"

"""crt: CRT emulator. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_crt(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x / w - 0.5) * 2; ny = (y / h - 0.5) * 2; c = p["curve"] / 100.0 * 0.25; r2 = nx * nx + ny * ny; f = 1 + c * r2
    out = remap_clear(img, (nx * f / 1.0 / (1 + c * 0.5) * 0.5 + 0.5) * w, (ny * f / (1 + c * 0.5) * 0.5 + 0.5) * h)
    fl = f3(out); sp = S(ctx, 3); s = 1 - (p["lines"] / 100.0) * (0.5 + 0.5 * np.cos(2 * np.pi * y / sp)) * 0.6; fl = fl * s[..., None]
    tri = np.stack([(np.cos(2 * np.pi * (x / (sp)) + k * 2.094) * 0.5 + 0.5) for k in (0, 1, 2)], -1); fl = fl * (1 - p["mask"] / 100.0 * 0.5 + p["mask"] / 100.0 * 0.5 * tri * 1.6)
    if p["bloom"] > 0: fl = fl + glow_of(np.clip(fl - 0.6, 0, 1), 6 * ctx.k) * (p["bloom"] / 100.0) * 1.5
    v = 1 - np.clip(r2 - 0.5, 0, 1) * (p["vignette"] / 100.0) * 1.2; fl = fl * v[..., None] * (1 - 0.04 * (0.5 + 0.5 * np.sin(ctx.lt * 60)) * p["flicker"] / 100.0)
    return pack(np.clip(fl, 0, 1), out[..., 3])

reg("crt", V, "CRT emulator", [F("curve", "Screen curve", 50, 0, 100), F("lines", "Scanlines", 45, 0, 100), F("mask", "Color dots", 40, 0, 100), F("bloom", "Bloom", 35, 0, 100), F("vignette", "Dark corners", 50, 0, 100), F("flicker", "Flicker", 20, 0, 100)], fx_crt,
    "An old curved TV tube: curved glass, scanlines, red-green-blue dots, glow and dark corners.", "old tv monitor tube")

ID = "crt"

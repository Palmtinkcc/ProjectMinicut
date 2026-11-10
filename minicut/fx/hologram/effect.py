"""hologram: Hologram. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_hologram(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], 20); f = f3(img); col = bgr(p["color"]); g = lum(f)[..., None]; y = np.arange(h, dtype=np.float32)
    jit = (np.sin(y * 0.15 + ctx.lt * 9) * 0.5 + r.normal(0, 0.5, h)) * (p["jitter"] / 100.0) * w * 0.02; base = shift_rows(img, jit.astype(np.float32)); f = f3(base); g = lum(f)[..., None]
    holo = (f * 0.35 + g * col * 1.1 + col * 0.12); sp = S(ctx, p["lines"]); sl = 0.65 + 0.35 * np.sin((y[:, None] / sp + ctx.lt * p["roll"]) * 2 * np.pi)[..., None]
    e = edges(base, ctx, 1.5)[..., None] * col * 1.5 * (p["glow"] / 100.0); fl = 1 - (p["flicker"] / 100.0) * (0.5 + 0.5 * np.sin(ctx.lt * 47) * r.random())
    a = base[..., 3].astype(np.float32) / 255 * (p["opacity"] / 100.0) * fl * (0.7 + 0.3 * sl[..., 0]); return pack(np.clip(holo * sl + e, 0, 1), a)

reg("hologram", G, "Hologram", [C("color", "Color", "#34e0ff"), F("lines", "Line spacing", 4, 2, 20), F("roll", "Lines move", 3.0, -20, 20), F("jitter", "Jitter", 40, 0, 100), F("flicker", "Flicker", 35, 0, 100), F("glow", "Edge glow", 60, 0, 100), OPAC(80), SEED()], fx_hologram,
    "Turns the picture into a see-through blue-green hologram with moving lines and flicker.", "sci-fi projection")

ID = "hologram"

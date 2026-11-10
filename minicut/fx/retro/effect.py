"""retro: Retro. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_retro(img, p, ctx):
    f = f3(img); g = lum(f)[..., None]; f = f * (1 - p["fade"] / 200.0) + g * (p["fade"] / 300.0); f = f * (1 - p["lift"] / 100.0 * 0.3) + p["lift"] / 100.0 * 0.12
    wm = p["warmth"] / 100.0; f[..., 2] *= 1 + wm * 0.15; f[..., 0] *= 1 - wm * 0.15; o = pack(np.clip(f, 0, 1), like=img)
    if p["soft"] > 0: o = blend(o, f3(blur_bgra(o, p["soft"] * ctx.k * 0.4)), None, "replace", 0.7)
    if p["bleed"] > 0:
        o2 = o.copy(); o2[..., 2] = np.roll(cv2.GaussianBlur(o[..., 2], (0, 0), max(0.5, p["bleed"] * ctx.k * 0.4)), int(p["bleed"] * ctx.k * 0.5), axis=1); o = o2
    return o

reg("retro", V, "Retro", [F("fade", "Faded colors", 45, 0, 100), F("lift", "Lifted blacks", 40, 0, 100), F("warmth", "Warmth", 30, -100, 100), F("soft", "Softness", 25, 0, 100), F("bleed", "Color bleed", 30, 0, 100)], fx_retro, "Soft, faded, warm colors like an old tape or a faded photo.", "vintage old tape")

ID = "retro"

"""puddle: Puddle. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_puddle(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); n = fbm(h, w, S(ctx, p["size"]) * 3, int(p["seed"]), 0, 3); base = h * p["level"] / 100.0; mask = sm(n * 0.7 + (y / h) * 0.6, 0.62 - p["spread"] / 400.0, 0.7 - p["spread"] / 400.0 + 0.06) * (y > base)
    t = ctx.lt * p["speed"] * 2 * np.pi; rip = (np.sin(x / S(ctx, 14) + t + y / S(ctx, 20)) * p["ripple"] * ctx.k * (0.3 + (y - base) / h)); refl = remap(img, x + rip, 2 * base - y + rip * 0.5, cv2.BORDER_REFLECT)
    if p["blur"] > 0: refl = blur_bgra(refl, p["blur"] * ctx.k * 0.2)
    f = f3(img); r = f3(refl) * 0.75 + bgr("#2a3540") * 0.15; out = f * (1 - mask[..., None]) + r * mask[..., None]; edge = np.clip(1 - np.abs(mask - 0.5) * 2, 0, 1) * 0.15; return pack(np.clip(out + edge[..., None], 0, 1), like=img)

reg("puddle", WG, "Puddle", [F("level", "Ground line", 60, 20, 95), F("spread", "Puddle size", 60, 0, 100), F("size", "Puddle shape", 40, 5, 200), F("ripple", "Ripples", 5, 0, 40), F("blur", "Soft reflection", 15, 0, 100), F("speed", "Speed", 0.6, 0, 4), SEED()], fx_puddle, "Puddles on the ground that reflect the picture above them.", "reflection wet floor")

ID = "puddle"

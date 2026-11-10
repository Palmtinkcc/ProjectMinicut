"""lensorb: Lens orb. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_lensorb(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["size"] / 100.0 * 0.5; ins = r < R; t = np.clip(r / R, 0, 1); z = np.sqrt(np.clip(1 - t * t, 0, 1)); rs = np.where(ins, r * (1 - p["power"] / 100.0 * z * 0.9) * 0.55 + 0 * r, r)
    out = sample_polar(img, cx, cy, np.where(ins, R * t ** (1 + p["power"] / 100.0) * 0.8, r), a); f = f3(out); rim = np.clip(1 - np.abs(r - R) / (S(ctx, 2.5)), 0, 1); spec = np.exp(-(((dx + R * 0.35) ** 2 + (dy + R * 0.4) ** 2) / (R * 0.18) ** 2)) * ins * p["shine"] / 100.0
    shade = 1 - (t ** 3) * 0.35 * ins; res = f * np.where(ins, shade, 1)[..., None] + (rim + spec)[..., None] * 0.7; return pack(np.clip(res, 0, 1), like=out)

reg("lensorb", LN, "Lens orb", [F("size", "Size", 55, 10, 140), F("power", "Magnify", 60, 0, 100), F("shine", "Shine", 60, 0, 100)] + CEN(), fx_lensorb, "A glass ball over the picture that magnifies what is behind it.", "magnifier sphere bubble")

ID = "lensorb"

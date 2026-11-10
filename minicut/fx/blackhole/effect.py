"""blackhole: Black hole. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_blackhole(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["size"] / 100.0 * 0.5; k = p["strength"] / 100.0; sw = k * (R / np.maximum(r, 1.0)) * 1.2 * np.sign(p["spin"] if p["spin"] else 1)
    rs = r * (1 + k * 1.2 * (R / np.maximum(r, R * 0.2)) ** 2); out = sample_polar(img, cx, cy, rs, a + sw * (1 + 0.5 * np.sin(ctx.lt * abs(p["spin"]) * 0.2)), cv2.BORDER_REFLECT)
    f = f3(out); hole = sm(r, R * 0.28, R * 0.32); ring_r = R * 0.5; ring = np.exp(-((r - ring_r) / (R * 0.07)) ** 2) * (0.6 + 0.4 * np.sin(a * 2 + ctx.lt * 3)) * p["glow"] / 100.0; col = ramp(ring, [(0, "#000000"), (0.4, "#ff5a00"), (1, "#fff0c0")])
    return pack(np.clip(f * hole[..., None] + col * (1 - 0.0) * (ring[..., None] > 0.02) * np.clip(ring[..., None] * 1.5, 0, 1), 0, 1), like=out)

reg("blackhole", LN, "Black hole", [F("size", "Size", 55, 10, 150), F("strength", "Pull", 60, 0, 150), F("spin", "Swirl", 40, -100, 100), F("glow", "Glowing ring", 80, 0, 100)] + CEN(), fx_blackhole, "Space bends around a black hole with a glowing ring.", "gravity lens space interstellar")

ID = "blackhole"

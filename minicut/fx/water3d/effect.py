"""water3d: 3D water. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_water3d(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); hz = h * p["horizon"] / 100.0; t = ctx.lt * p["speed"] * 2 * np.pi; d = np.maximum(y - hz, 0.0) / max(1.0, h - hz); depth = 1.0 / (0.25 + d)
    wave = (np.sin(x / (S(ctx, p["length"]) * (0.4 + d * 0.9)) + t + d * 6) + 0.5 * np.sin(x / (S(ctx, p["length"]) * 0.6 * (0.4 + d)) - t * 1.3)) * p["ripple"] * ctx.k * (0.2 + d)
    sy = hz - (y - hz) * (0.6 + 0.8 * p["depth"] / 100.0) * 1.0 + wave * 0.6; sx = x + wave; refl = remap(img, sx, sy, cv2.BORDER_REFLECT); f = f3(refl); tint = bgr(p["color"]); res = f * (p["reflect"] / 100.0) * (1 - d[..., None] * 0.3) + tint * (1 - p["reflect"] / 100.0) * 0.5 + tint * 0.25 * d[..., None]
    sp = np.clip(np.sin(x / 40 + t * 2 + d * 10) * np.sin(d * 30 - t), 0, 1) ** 8 * 0.3 * d; res = res + sp[..., None]; below = (y > hz)[..., None]; out = np.where(below, res, f3(img)); return pack(np.clip(out, 0, 1), like=img)

reg("water3d", WG, "3D water", [F("horizon", "Water line", 55, 10, 95), F("ripple", "Waves", 10, 0, 60), F("length", "Wave length", 40, 5, 200), F("depth", "Depth", 60, 0, 100), F("reflect", "Reflection", 70, 0, 100), C("color", "Water color", "#0b4f6c"), F("speed", "Speed", 0.5, 0, 4)], fx_water3d, "The lower part becomes a lake with perspective waves that reflect the top part.", "lake sea reflection ocean")

ID = "water3d"

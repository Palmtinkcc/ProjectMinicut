"""lensflare: Lens flare. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_lensflare(img, p, ctx):
    h, w = img.shape[:2]; cx, cy = w * p["x"] / 100.0, h * p["y"] / 100.0; col = bgr(p["color"]); s = p["size"] / 100.0 * h; ang = ctx.lt * p["drift"] * 0.2
    cx += np.sin(ang) * w * 0.05 * (p["drift"] > 0)
    # The glow and the rings are soft: they are worked out on a grid with half as many points each way and enlarged. The thin streak is a product of one
    # curve across and one down (no 2-D grid needed), so it is made at full size, exactly.
    hh, ww = (h + 1) // 2, (w + 1) // 2; xx = (np.arange(ww, dtype=np.float32) * 2 + 0.5)[None, :]; yy = (np.arange(hh, dtype=np.float32) * 2 + 0.5)[:, None]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2); fl = np.exp(-d / (s * 0.18)) * 1.2 + np.exp(-(d / (s * 0.55)) ** 2) * 0.35
    out = fl[..., None] * col; ox, oy = w / 2 - cx, h / 2 - cy
    for k, (pos, rad, a) in enumerate(((0.5, 0.09, 0.35), (1.0, 0.16, 0.28), (1.5, 0.07, 0.4), (2.1, 0.22, 0.2), (-0.4, 0.12, 0.25))):
        gx, gy = cx + ox * pos * 2, cy + oy * pos * 2; dd = np.sqrt((xx - gx) ** 2 + (yy - gy) ** 2); ring = np.exp(-((dd - rad * h) / (h * 0.012)) ** 2) * 0.6 + sm(rad * h - dd, 0, rad * h) * 0.25
        out += ring[..., None] * (col * 0.6 + np.array([0.5 * (k % 2), 0.3, 0.5 * ((k + 1) % 2)], np.float32) * 0.5) * a * p["ghosts"] / 50.0
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
    fx1 = np.arange(w, dtype=np.float32); fy1 = np.arange(h, dtype=np.float32)
    streak = np.multiply.outer(np.exp(-np.abs(fy1 - cy) / (s * 0.02)), np.exp(-np.abs(fx1 - cx) / (s * 1.6))) * np.float32(p["streak"] / 100.0)
    out += streak[..., None] * col
    return blend(img, np.clip(out * (p["amount"] / 100.0), 0, 2), None, "add", 1.0)

reg("lensflare", PR, "Lens flare", [F("x", "Light X", 25, -20, 120), F("y", "Light Y", 25, -20, 120), F("size", "Size", 45, 5, 120), F("amount", "Brightness", 90, 0, 200), F("streak", "Streak", 50, 0, 100), F("ghosts", "Reflections", 50, 0, 100), F("drift", "Drift", 0, 0, 10), C("color", "Color", "#ffd9a0")], fx_lensflare, "A bright light with a long streak and the colored rings that a camera lens makes.", "light sun flare anamorphic")

ID = "lensflare"

"""raindrop: Rain drop. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_raindrop(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); out = img.copy(); t = ctx.lt * p["speed"]
    for i in range(int(p["count"])):
        rad = S(ctx, p["size"]) * r.uniform(0.5, 1.3); px = r.random() * w; py0 = r.random() * h; slide = (t * r.uniform(0.0, 14) * ctx.k) % (h + rad * 4); py = (py0 + slide) % (h + 2 * rad) - rad
        x0, x1, y0, y1 = int(max(0, px - rad * 1.6)), int(min(w, px + rad * 1.6)), int(max(0, py - rad * 2.2)), int(min(h, py + rad * 1.8))
        if x1 <= x0 or y1 <= y0: continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32); nx = (xx - px) / rad; ny = (yy - py) / (rad * 1.25); r2 = nx * nx + ny * ny; ins = r2 < 1; z = np.sqrt(np.clip(1 - r2, 0, 1))
        sx = px - nx * rad * (0.4 + 0.6 * p["refract"] / 100.0) * 1.4 * 1; sy = py - ny * rad * 1.25 * (0.4 + 0.6 * p["refract"] / 100.0) * 1.4
        win = cv2.remap(np.ascontiguousarray(img), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); a = np.clip((1 - np.sqrt(r2)) * rad / 1.2, 0, 1)[..., None]
        hi = np.exp(-(((nx + 0.35) ** 2 + (ny + 0.4) ** 2) / 0.04)) * 0.7; win = win.astype(np.float32); win[..., :3] = win[..., :3] * (0.75 + 0.25 * z[..., None]) + hi[..., None] * 255
        out[y0:y1, x0:x1] = (win * a + out[y0:y1, x0:x1].astype(np.float32) * (1 - a)).astype(np.uint8)
    return out

reg("raindrop", WG, "Rain drop", [I("count", "Drops", 30, 1, 150), F("size", "Drop size", 12, 3, 60), F("refract", "Upside-down lens", 70, 0, 100), F("speed", "Slide speed", 1.0, 0, 8), SEED()], fx_raindrop, "Drops on a window, each one showing a tiny upside-down copy of the world.", "rain window glass droplets")

ID = "raindrop"

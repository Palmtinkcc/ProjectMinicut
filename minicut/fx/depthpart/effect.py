"""depthpart: Depth particles. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_depthpart(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); L = lum8(img); t = ctx.lt * p["speed"]; cv = np.zeros((h, w, 3), np.float32); f = f3(img)
    for i in range(n):
        x0, y0 = r.random() * w, r.random() * h; ph = r.random() * 6.28; xi, yi = int(np.clip(x0, 0, w - 1)), int(np.clip(y0, 0, h - 1)); d = float(L[yi, xi]); x = (x0 + np.sin(t + ph) * w * 0.05 * (0.3 + d)) % w; y = (y0 - t * h * 0.05 * (0.3 + d)) % h
        c = f[yi, xi] * (0.6 + 0.6 * d) if p["from_picture"] else bgr(p["color"]) * (0.4 + 0.6 * d); cv2.circle(cv, (int(x), int(y)), max(1, int(S(ctx, p["size"]) * (0.3 + d * 1.4))), tuple(float(v) for v in c), -1, cv2.LINE_AA)
    return _fin(img, cv, 2.5, p, ctx)

reg("depthpart", PT, "Depth particles", [I("count", "Amount", 120, 10, 500), F("size", "Size", 4, 0.5, 30), F("speed", "Speed", 1.0, 0, 10), B("from_picture", "Use the picture's colors", True), C("color", "Color", "#ffffff"), MODE("add"), OPAC(100), SEED()], fx_depthpart, "Particles that are bigger, brighter and faster over the bright (near) parts of the picture.", "parallax dust")

ID = "depthpart"

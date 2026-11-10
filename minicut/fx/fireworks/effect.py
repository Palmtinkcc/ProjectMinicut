"""fireworks: Fireworks particle. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_fireworks(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col0 = bgr(p["color"]); n = int(p["bursts"]); t = ctx.lt * p["speed"]
    for b in range(n):
        r = np.random.default_rng(int(p["seed"]) * 100 + b); per = r.uniform(1.6, 2.6); cyc = int((t + b * 0.7) // per); ph = ((t + b * 0.7) % per) / per; rr = np.random.default_rng(int(p["seed"]) * 100 + b * 7 + cyc)
        cx, cy = rr.uniform(0.2, 0.8) * w, rr.uniform(0.2, 0.55) * h; hue = rr.random(); col = hsv_bgr(hue, 0.5, 1.0) * 0.7 + col0 * 0.3 if p["rainbow"] else col0; ang = rr.random(int(p["count"])) * 6.28; spd = rr.uniform(0.4, 1.0, int(p["count"])) * h * 0.4
        if ph < 0.18: cv2.circle(cv, (int(cx), int(h - (h - cy) * ph / 0.18)), max(1, int(S(ctx, 2))), (1, 1, 1), -1, cv2.LINE_AA)
        else:
            u = (ph - 0.18) / 0.82; fade = (1 - u) ** 1.5
            for k in range(len(ang)):
                x = cx + np.cos(ang[k]) * spd[k] * u ** 0.6; y = cy + np.sin(ang[k]) * spd[k] * u ** 0.6 + u * u * h * 0.25; cv2.circle(cv, (int(x), int(y)), max(1, int(S(ctx, p["size"] * 0.5))), tuple(float(c * fade) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 4, p, ctx)

reg("fireworks", PT, "Fireworks particle", [I("bursts", "Fireworks", 3, 1, 8), I("count", "Sparks each", 70, 10, 250), F("size", "Size", 4, 1, 20), F("speed", "Speed", 1.0, 0.2, 5), C("color", "Color", "#ffd27a"), B("rainbow", "Every one a different color", True), MODE("add"), OPAC(100), SEED()], fx_fireworks, "Rockets that burst into sparks.", "explosion sparks")

ID = "fireworks"

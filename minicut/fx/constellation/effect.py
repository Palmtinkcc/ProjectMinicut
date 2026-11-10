"""constellation: Constellation. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_constellation(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); ph = r.random((n, 2)) * 6.28; t = ctx.lt * p["speed"]; P = np.stack([(r.random(n) * w + np.sin(t * 0.7 + ph[:, 0]) * w * 0.04), (r.random(n) * h + np.cos(t * 0.6 + ph[:, 1]) * h * 0.04)], 1)
    cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); R = w * p["reach"] / 100.0 * 0.3
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(*(P[i] - P[j]))
            if d < R: a = 1 - d / R; cv2.line(cv, tuple(P[i].astype(int)), tuple(P[j].astype(int)), tuple(float(c * a * 0.8) for c in col), 1, cv2.LINE_AA)
    for i in range(n): cv2.circle(cv, tuple(P[i].astype(int)), max(1, int(S(ctx, p["size"]))), tuple(float(c) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)

reg("constellation", PT, "Constellation", [I("count", "Stars", 40, 5, 140), F("reach", "Line reach", 50, 5, 100), F("size", "Star size", 2.5, 0.5, 15), F("speed", "Speed", 1.0, 0, 10), C("color", "Color", "#dbeaff"), MODE("add"), OPAC(100), SEED()], fx_constellation, "Stars joined by thin lines when they are close to each other.", "network dots lines")

ID = "constellation"

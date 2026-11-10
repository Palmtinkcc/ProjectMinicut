"""dotsfield: Dots field. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_dotsfield(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); s = S(ctx, p["spacing"]); t = ctx.lt * p["speed"]; yy, xx = np.mgrid[0:int(h / s) + 2, 0:int(w / s) + 2]
    for j in range(yy.shape[0]):
        for i in range(xx.shape[1]):
            ph = np.sin(i * 1.7 + j * 2.3) * 6.28; k = 0.5 + 0.5 * np.sin(t * 2 + ph); cx, cy = i * s + np.sin(t + ph) * s * 0.3, j * s + np.cos(t * 0.8 + ph) * s * 0.3
            if p["layout"] == "random": cx, cy = (np.sin(i * 12.9 + j * 78.2) * 43758 % 1) * w, (np.sin(i * 39.3 + j * 11.1) * 43758 % 1) * h
            cv2.circle(cv, (int(cx), int(cy)), max(1, int(S(ctx, p["size"]) * (0.4 + k * 0.8))), tuple(float(c * k) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 2, p, ctx)

reg("dotsfield", PT, "Dots field", [F("spacing", "Spacing", 28, 8, 120), F("size", "Dot size", 4, 1, 30), F("speed", "Speed", 1.0, 0, 10), CH("layout", "Layout", "grid", [("grid", "Grid"), ("random", "Random")]), C("color", "Color", "#9be7ff"), MODE("add"), OPAC(100), SEED()], fx_dotsfield, "A field of dots that breathe and drift.", "points grid")

ID = "dotsfield"

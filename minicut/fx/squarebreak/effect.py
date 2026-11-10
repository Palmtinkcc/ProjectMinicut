"""squarebreak: Square break 3D. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_squarebreak(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); nx = int(p["cols"]); s = w / nx; ny = int(np.ceil(h / s)); r = np.random.default_rng(int(p["seed"])); canvas = np.zeros_like(img); order = []
    for j in range(ny):
        for i in range(nx):
            dd = np.hypot((i + 0.5) / nx - p["x"] / 100.0, ((j + 0.5) * s - h * p["y"] / 100.0) / w); lp = np.clip((pr * (1 + 0.8) - dd * 0.9 - r.random() * 0.25) / 0.8, 0, 1); order.append((lp, i, j, r.normal(0, 1)))
    for lp, i, j, rv in sorted(order, key=lambda o: -o[0]):
        x0, y0 = int(i * s), int(j * s); x1, y1 = int(min(w, (i + 1) * s)) + 1, int(min(h, (j + 1) * s)) + 1; tile = img[y0:y1, x0:x1]
        if tile.size == 0: continue
        if lp <= 0: canvas[y0:y1, x0:x1] = tile; continue
        if lp >= 1: continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; sc_ = 1 - lp * 0.7; M = cv2.getRotationMatrix2D((cx, cy), rv * 60 * lp, sc_); M[1, 2] += lp * lp * h * p["fall"] / 100.0 * (0.5 + 0.5 * abs(rv)); M[0, 2] += rv * lp * s * 0.8
        piece = _am(tile, 1 - lp * 0.6); canvas = _paste(canvas, piece, x0, y0, M)
    return canvas

reg("squarebreak", WP, "Square break 3D", WIPE(40) + [I("cols", "Squares across", 12, 3, 30), F("fall", "Fall", 60, 0, 200), F("x", "Starts at X", 50, 0, 100), F("y", "Starts at Y", 50, 0, 100), SEED()], fx_squarebreak, "The picture breaks into squares that turn, shrink and fall away, starting from a point.", "tiles fall cubes")

ID = "squarebreak"

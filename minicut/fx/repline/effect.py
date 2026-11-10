"""repline: Line repeat. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_repline(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); ang = np.deg2rad(p["angle"]); step = p["distance"] * ctx.k; copies = []
    for i in range(n - 1, -1, -1):
        sc_ = p["size"] / 100.0 * (1 - p["shrink"] / 100.0 * i / max(1, n - 1)); M = xform(h, w, np.cos(ang) * step * i - np.cos(ang) * step * (n - 1) / 2 * p["center"], np.sin(ang) * step * i - np.sin(ang) * step * (n - 1) / 2 * p["center"], 0, sc_); c = _place(img, M)
        c[..., 3] = (c[..., 3] * (1 - p["fade"] / 100.0 * i / max(1, n - 1))).astype(np.uint8); copies.append(c)
    return _comp(copies, h, w)

reg("repline", RP, "Line repeat", [I("count", "Copies", 6, 2, 30), F("size", "Size", 50, 5, 120), F("distance", "Distance", 60, 0, 400), F("angle", "Angle", 0, -180, 180), F("shrink", "Shrink", 25, 0, 90), F("fade", "Fade", 30, 0, 100), F("center", "Centered", 1, 0, 1)], fx_repline, "Copies of the picture in a row, each smaller and fainter.", "array row copies")

ID = "repline"

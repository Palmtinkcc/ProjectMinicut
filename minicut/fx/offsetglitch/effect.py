"""offsetglitch: Offset glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_offsetglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); sh = np.zeros(h, np.float32)
    for y0, y1 in _rows(r, h, a, 0.18):
        if r.random() < 0.15 + 0.6 * a: sh[y0:y1] = r.normal(0, w * 0.12 * a)
    return shift_rows(img, sh)

reg("offsetglitch", G, "Offset glitch", GP(), fx_offsetglitch, "Horizontal strips of the picture are shifted left and right.", "tear shift")

ID = "offsetglitch"

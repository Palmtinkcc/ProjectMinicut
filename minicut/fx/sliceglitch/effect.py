"""sliceglitch: Slice glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_sliceglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); n = int(p["slices"]); vert = p["direction"] == "vertical"; src = np.ascontiguousarray(np.swapaxes(img, 0, 1)) if vert else img
    hh = src.shape[0]; cuts = np.sort(r.integers(0, hh, n)); sh = np.zeros(hh, np.float32); prev = 0
    for c in list(cuts) + [hh]:
        if r.random() < 0.3 + 0.6 * a: sh[prev:c] = r.normal(0, src.shape[1] * 0.1 * a)
        prev = c
    out = shift_rows(src, sh); return np.ascontiguousarray(np.swapaxes(out, 0, 1)) if vert else out

reg("sliceglitch", G, "Slice glitch", GP([I("slices", "Slices", 14, 2, 60), CH("direction", "Direction", "horizontal", [("horizontal", "Horizontal"), ("vertical", "Vertical")])]), fx_sliceglitch, "The picture is cut into thin slices that slide out of place.", "cut slices")

ID = "sliceglitch"

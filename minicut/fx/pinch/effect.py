"""pinch: Pinch / Bulge. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_pinch(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["radius"] / 100.0 * 0.5 * 2; t = np.clip(r / R, 0, 1); k = p["amount"] / 100.0
    rs = np.where(r < R, r * (1 - k * (1 - t * t)), r); return sample_polar(img, cx, cy, rs, a)

reg("pinch", DW, "Pinch / Bulge", [F("amount", "Bulge (+) / Pinch (-)", 60, -95, 95), F("radius", "Size", 60, 5, 200)] + CEN(), fx_pinch, "Swells a round part of the picture like a bubble, or sucks it in.", "bulge magnify")

ID = "pinch"

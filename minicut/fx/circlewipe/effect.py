"""circlewipe: Circle wipe mask. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_circlewipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); cx, cy = w * p["cx"] / 100.0, h * p["cy"] / 100.0; far = max(np.hypot(cx, cy), np.hypot(w - cx, cy), np.hypot(cx, h - cy), np.hypot(w - cx, h - cy)); r = pr * far
    m = disc(h, w, cx, cy, r, max(1.0, p["feather"] * ctx.k)); return _am(img, m if p["hole"] else 1 - m)

reg("circlewipe", WP, "Circle wipe mask", WIPE(40) + [F("cx", "Center X", 50, 0, 100), F("cy", "Center Y", 50, 0, 100), F("feather", "Soft edge", 8, 0, 100), B("hole", "A hole opens (off: the picture shrinks to the circle)", True)], fx_circlewipe, "A circle grows and wipes the picture away.", "iris round")

ID = "circlewipe"

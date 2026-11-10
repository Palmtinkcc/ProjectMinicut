"""feather: Feather. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_feather(img, p, ctx):
    h, w = img.shape[:2]; size = p["size"] / 100.0; x, y = coords(h, w)
    if p["shape"] == "ellipse": r = np.sqrt(((x / w - 0.5) * 2) ** 2 + ((y / h - 0.5) * 2) ** 2); m = np.clip((1 - r) / max(size * 2, 1e-3), 0, 1)
    else: d = np.minimum(np.minimum(x, w - 1 - x) / w, np.minimum(y, h - 1 - y) / h) * 2; m = np.clip(d / max(size, 1e-3), 0, 1)
    return _alpha_mul(img, m ** p["curve"])

reg("feather", C2, "Feather", [F("size", "Size", 25, 0, 100), CH("shape", "Shape", "rect", [("rect", "Rectangle"), ("ellipse", "Ellipse")]), F("curve", "Curve", 1.0, 0.3, 4)], fx_feather, "Fades the edges of the media into see-through.", "soft edge fade vignette alpha")

ID = "feather"

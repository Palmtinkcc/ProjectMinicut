"""spinblur: Spin blur. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_spinblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; return _avg(img, [xform(h, w, 0, 0, p["angle"] * (i / (n - 1) - 0.5), 1.0, cx, cy) for i in range(n)], w, h)

reg("spinblur", BL, "Spin blur", [F("angle", "Angle", 12, 0, 90), I("steps", "Quality", 16, 4, 40)] + CEN(), fx_spinblur, "A blur that turns around a center, like a spinning wheel.", "rotational radial")

ID = "spinblur"

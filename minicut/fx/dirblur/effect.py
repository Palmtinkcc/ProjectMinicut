"""dirblur: Directional blur. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_dirblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); a = np.deg2rad(p["angle"]); L = p["length"] * ctx.k
    return _avg(img, [np.float32([[1, 0, np.cos(a) * L * (i / (n - 1) - (0 if p["onesided"] else 0.5))], [0, 1, np.sin(a) * L * (i / (n - 1) - (0 if p["onesided"] else 0.5))]]) for i in range(n)], w, h)

reg("dirblur", BL, "Directional blur", [F("length", "Length", 40, 0, 300), F("angle", "Direction", 0, -180, 180), I("steps", "Quality", 16, 4, 40), B("onesided", "Comet (one direction)", False)], fx_dirblur, "Blurs in one direction, both ways or like a comet tail.", "motion line")

ID = "dirblur"

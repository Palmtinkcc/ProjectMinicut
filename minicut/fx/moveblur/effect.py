"""moveblur: Pulsing directional blur (old move blur). CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_moveblur(img, p, ctx):
    h, w = img.shape[:2]; k = 0.5 - 0.5 * np.cos(2 * np.pi * ctx.lt / max(0.2, p["period"])); L = p["length"] * k * ctx.k; a = np.deg2rad(p["angle"] + ctx.lt * p["turn"]); n = 14 if ctx.fast else 20
    if L < 0.5: return img
    return _avg(img, [np.float32([[1, 0, np.cos(a) * L * (i / (n - 1) - 0.5)], [0, 1, np.sin(a) * L * (i / (n - 1) - 0.5)]]) for i in range(n)], w, h)

reg("moveblur", BL, "Pulsing directional blur (old move blur)", [F("length", "Most blur", 60, 0, 300), F("angle", "Direction", 0, -180, 180), F("period", "Blur comes and goes every (s)", 1.5, 0.3, 20), F("turn", "Direction turns (deg / s)", 0, -360, 360)], fx_moveblur, "A motion blur that swells and fades by itself, like a camera whip.", "whip pan camera move")

ID = "moveblur"

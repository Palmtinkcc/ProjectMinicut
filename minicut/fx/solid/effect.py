"""solid: Solid color. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_solid(img, p, ctx):
    return blend(img, np.broadcast_to(bgr(p["color"]), img.shape[:2] + (3,)), None, p["mode"], p["opacity"] / 100.0)

reg("solid", C1, "Solid color", [C("color", "Color", "#ff3b6b"), MODE("behind"), OPAC(100)], fx_solid, "Covers the picture, or the empty space behind it, with one color.", "fill flat")

ID = "solid"

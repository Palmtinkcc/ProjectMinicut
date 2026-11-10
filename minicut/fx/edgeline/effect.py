"""edgeline: Edge line. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_edgeline(img, p, ctx):
    e = sm(edges(img, ctx, p["width"]), p["threshold"] / 100.0 * 0.4, p["threshold"] / 100.0 * 0.4 + 0.15); return blend(img, np.broadcast_to(bgr(p["color"]), e.shape + (3,)), e * _alpha(img), "over", p["opacity"] / 100.0)

reg("edgeline", SS, "Edge line", [F("width", "Line width", 1.5, 0.5, 8), F("threshold", "Sensitivity", 40, 0, 100), C("color", "Color", "#ffffff"), OPAC(100)], fx_edgeline, "Draws lines along the edges it finds in the picture.", "outline contour")

ID = "edgeline"

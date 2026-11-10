"""lensdist: Lens distortion. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_lensdist(img, p, ctx):
    sx, sy = _barrel(img, {"k2": p["k2"]}, ctx, p["k1"] / 100.0, 1.0 / (1 + max(0, p["k1"]) / 100.0 * 0.5) if p["fit"] else 1.0); return remap_clear(img, sx, sy)

reg("lensdist", LN, "Lens distortion", [F("k1", "Barrel (+) / Pincushion (-)", 40, -100, 100), F("k2", "Edge correction", 0, -100, 100), B("fit", "Zoom in to fill", True)], fx_lensdist, "Bends the picture like a wide or telephoto lens.", "barrel pincushion")

ID = "lensdist"

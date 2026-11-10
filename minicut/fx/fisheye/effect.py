"""fisheye: Fisheye. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_fisheye(img, p, ctx):
    sx, sy = _barrel(img, p, ctx, p["amount"] / 100.0 * 1.2, 1.0 / (1 + p["amount"] / 100.0 * 0.6) if p["fit"] else 1.0); return remap_clear(img, sx, sy)

reg("fisheye", LN, "Fisheye", [F("amount", "Amount", 60, 0, 150), B("fit", "Zoom in to fill", True)], fx_fisheye, "A wide-angle bubble look.", "wide angle barrel gopro")

ID = "fisheye"

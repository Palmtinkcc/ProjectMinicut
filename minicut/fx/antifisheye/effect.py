"""antifisheye: Anti fisheye. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_antifisheye(img, p, ctx):
    sx, sy = _barrel(img, p, ctx, -p["amount"] / 100.0 * 0.6, 1.0 / max(0.4, 1 - p["amount"] / 100.0 * 0.3) if p["fit"] else 1.0); return remap_clear(img, sx, sy)

reg("antifisheye", LN, "Anti fisheye", [F("amount", "Amount", 30, 0, 150), B("fit", "Zoom in to fill", True)], fx_antifisheye, "The opposite of fisheye: straightens a bent picture (or pinches the corners).", "pincushion undistort")

ID = "antifisheye"

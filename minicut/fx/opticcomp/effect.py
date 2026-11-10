"""opticcomp: Optic compensation. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_opticcomp(img, p, ctx):
    k = p["amount"] / 100.0 * (-0.8 if p["reverse"] else 0.8); sx, sy = _barrel(img, {"k2": 0}, ctx, k, 1.0 / (1 + max(0, k) * 0.5) if k > 0 else 1.0 / max(0.3, 1 + k * 0.5)); return remap_clear(img, sx, sy)

reg("opticcomp", LN, "Optic compensation", [F("amount", "Amount", 40, 0, 100), B("reverse", "Add distortion instead of removing it", False)], fx_opticcomp, "Straightens the curved lines made by a wide-angle lens (or adds the curve).", "lens correction wide angle")

ID = "opticcomp"

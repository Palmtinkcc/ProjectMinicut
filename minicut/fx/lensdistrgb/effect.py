"""lensdistrgb: Lens distortion RGB. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_lensdistrgb(img, p, ctx):
    out = img.copy(); h, w = img.shape[:2]
    for c, d in ((2, -1), (1, 0), (0, 1)):
        sx, sy = _barrel(img, {"k2": p["k2"]}, ctx, (p["k1"] + d * p["split"]) / 100.0, 1.0 / (1 + max(0, p["k1"]) / 100.0 * 0.5) if p["fit"] else 1.0); out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return out

reg("lensdistrgb", LN, "Lens distortion RGB", [F("k1", "Barrel (+) / Pincushion (-)", 30, -100, 100), F("split", "Color split", 6, 0, 30), F("k2", "Edge correction", 0, -100, 100), B("fit", "Zoom in to fill", True)], fx_lensdistrgb, "Lens distortion where each color is bent a little differently.", "barrel chromatic")

ID = "lensdistrgb"

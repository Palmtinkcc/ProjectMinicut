"""vignettepro: Vignette Pro. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_vignettepro(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x / w - 0.5 - p["cx"] / 100.0) * 2; ny = (y / h - 0.5 - p["cy"] / 100.0) * 2; rd = p["round"] / 100.0
    if p["shape"] == "rect": d = np.maximum(np.abs(nx) ** (2 + 6 * (1 - rd)) , np.abs(ny) ** (2 + 6 * (1 - rd))) ** (1.0 / (2 + 6 * (1 - rd)))
    else: d = np.sqrt((nx * (1 if rd > 0.5 else 0.7 + 0.6 * rd)) ** 2 + ny ** 2) if False else np.sqrt((nx * (w / h) ** (-(1 - rd))) ** 2 * 1.0 + ny ** 2) * (1 + 0.0)
    s = p["size"] / 100.0; m = sm(d, s * 1.2 - p["feather"] / 100.0 * 1.0, s * 1.2 + 0.001 + 0.0) if False else sm(d, s - p["feather"] / 100.0 * s + 0.001, s + 0.5 * p["feather"] / 100.0 + 0.002)
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m * p["strength"] / 100.0, "over" if not p["multiply"] else "multiply", 1.0)

reg("vignettepro", SS, "Vignette Pro", [F("size", "Size", 85, 20, 150), F("feather", "Feather", 60, 0, 100), F("round", "Roundness", 100, 0, 100), CH("shape", "Shape", "ellipse", [("ellipse", "Ellipse"), ("rect", "Rounded square")]), F("cx", "Center X", 0, -50, 50), F("cy", "Center Y", 0, -50, 50), F("strength", "Strength", 75, 0, 100), C("color", "Color", "#000000"), B("multiply", "Multiply (darken only)", False)], fx_vignettepro, "A dark frame around the picture with full control of its shape, softness and center.", "darken corners")

ID = "vignettepro"

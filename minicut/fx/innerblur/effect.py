"""innerblur: Inner blur. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_innerblur(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); d = np.minimum(np.minimum(x, w - 1 - x) / w, np.minimum(y, h - 1 - y) / h) * 2; edge = sm(d, p["border"] / 100.0 * 0.5, p["border"] / 100.0 * 0.5 + p["feather"] / 100.0 * 0.5 + 1e-3); bl = blur_bgra(img, p["amount"] * ctx.k * 0.5)
    return blend(img, f3(bl), edge * (bl[..., 3].astype(np.float32) / 255.0 * 0 + 1), "replace", 1.0)

reg("innerblur", BL, "Inner blur", [F("amount", "Blur", 40, 0, 150), F("border", "Sharp border", 25, 0, 100), F("feather", "Soft transition", 50, 0, 100)], fx_innerblur, "Blurs the inside of the picture and keeps the edges sharp (the opposite of a vignette blur).", "tilt shift focus edge sharp")

ID = "innerblur"

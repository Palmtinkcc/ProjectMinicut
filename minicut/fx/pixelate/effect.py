"""pixelate: Pixelate / Mosaic. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_pixelate(img, p, ctx):
    s = max(1, int(round(p["size"] * ctx.k))); h, w = img.shape[:2]
    if s <= 1: return img
    small = cv2.resize(img, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

register("pixelate", "Distort", "Pixelate / Mosaic",
         [("size", "Block size", "float", 14.0, 1.0, 120.0)],
         fx_pixelate,
         help="Pixelate the image into square blocks — classic mosaic censor effect.")

ID = "pixelate"

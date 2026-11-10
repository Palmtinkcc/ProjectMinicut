"""threshold: Threshold. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_threshold(img, p, ctx):
    thr = int(p["level"])
    invert = p.get("invert", False)
    rgb = img[..., :3].astype(np.float32)
    lum = (rgb @ np.array([0.114, 0.587, 0.299], np.float32))
    mask = (lum >= thr).astype(np.uint8) * 255
    if invert: mask = 255 - mask
    out = img.copy(); out[..., :3] = mask[..., None]; return out

register("threshold", "Color", "Threshold",
         [("level",  "Level",  "int",  128, 0, 255),
          ("invert", "Invert", "bool", False, None, None)],
         fx_threshold,
         help="High-contrast black-and-white by luminance threshold.")

ID = "threshold"

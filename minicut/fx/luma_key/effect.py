"""luma_key: Luma Key. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_luma_key(img, p, ctx):
    """Key out pixels by luminance. Mode bright = keep brights, dark = keep darks."""
    thr  = p["threshold"] / 100.0
    soft = max(0.001, p.get("softness", 10.0) / 100.0)
    mode = p.get("mode", "dark")   # dark | bright
    rgb  = img[..., :3].astype(np.float32) * (1 / 255)
    lum  = rgb[..., 0] * 0.114 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.299
    if mode == "bright":
        alpha = np.clip((thr - lum) / soft, 0, 1)
    else:  # dark: key out darks
        alpha = np.clip((lum - thr) / soft, 0, 1)
    out = img.copy()
    out[..., 3] = (img[..., 3].astype(np.float32) * alpha + .5).astype(np.uint8)
    return out

register("luma_key", "Key", "Luma Key",
         [("threshold", "Threshold", "float", 50.0, 0.0, 100.0),
          ("softness",  "Softness",  "float", 10.0, 0.1, 50.0),
          ("mode",      "Mode",      "choice", "dark",
           [("dark", "Key darks out"), ("bright", "Key brights out")], None)],
         fx_luma_key,
         help="Remove pixels by luminance. Key darks out = keep bright areas; Key brights out = keep darks.")

ID = "luma_key"

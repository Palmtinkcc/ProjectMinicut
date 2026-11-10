"""dark_glow: Dark Glow. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _gauss, register

def fx_dark_glow(img, p, ctx):
    """Shadow-side glow: multiplies dark areas — inverse of Glow."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k)
    thr    = p.get("threshold", 40.0) / 100.0
    f = img[..., :3].astype(np.float32)
    lum = (f @ np.array([0.114, 0.587, 0.299], np.float32)) * (1 / 255)
    dark_mask = np.clip((thr - lum) / max(1e-3, thr), 0, 1)[..., None]
    dark_px   = dark_mask * (255 - f)
    spread    = _gauss(dark_px, radius)
    out = img.copy()
    out[..., :3] = np.clip(f - spread * amount + .5, 0, 255).astype(np.uint8)
    return out

register("dark_glow", "Stylize", "Dark Glow",
         [("amount",    "Amount",    "float", 60.0, 0.0, 100.0),
          ("radius",    "Radius",    "float", 20.0, 0.0, 100.0),
          ("threshold", "Threshold", "float", 40.0, 0.0, 100.0)],
         fx_dark_glow,
         help="Inverse glow that spreads from shadows — creates moody, smoky dark edges.")

ID = "dark_glow"

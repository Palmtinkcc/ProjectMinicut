"""inner_glow: Inner Glow. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_inner_glow(img, p, ctx):
    """Glow that emanates inward from the alpha edge of the layer."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k)
    col    = p.get("color", "#ffffff")
    from ...shared.deps import QColor as _QC
    c = _QC(col); tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32) * 255
    alpha  = img[..., 3].astype(np.float32) / 255.0
    # Erode alpha and subtract — difference is the inner edge region
    eroded = cv2.GaussianBlur(alpha, (0, 0), radius)
    inner  = np.clip(alpha - eroded, 0, 1) * amount * 2
    inner  = np.clip(inner, 0, 1)
    out    = img.copy()
    f      = img[..., :3].astype(np.float32)
    for ch in range(3):
        out[..., ch] = np.clip(f[..., ch] + inner * tc[ch], 0, 255).astype(np.uint8)
    return out

register("inner_glow", "Stylize", "Inner Glow",
         [("amount", "Amount", "float", 60.0, 0.0, 100.0),
          ("radius", "Radius", "float", 20.0, 0.0, 100.0),
          ("color",  "Color",  "color", "#ffffff", None, None)],
         fx_inner_glow,
         help="Glow emitted inward from the layer's alpha edge.")

ID = "inner_glow"

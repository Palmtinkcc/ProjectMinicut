"""soft_glow: Soft Glow. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _gauss, register

def fx_soft_glow(img, p, ctx):
    """Dreamy soft glow: blurred screen overlay — AM's Soft Glow."""
    amount   = p["amount"] / 100.0
    if amount <= 0: return img
    radius   = max(0.5, p["radius"] * ctx.k)
    softness = p.get("softness", 50.0) / 100.0
    f    = img[..., :3].astype(np.float32)
    soft = _gauss(f, radius)
    # Screen blend of soft over original
    screened = 255 - (255 - f) * (255 - soft * softness) / 255
    blended  = f + (screened - f) * amount
    out = img.copy(); out[..., :3] = np.clip(blended + .5, 0, 255).astype(np.uint8); return out

register("soft_glow", "Stylize", "Soft Glow",
         [("amount",   "Amount",   "float", 60.0, 0.0, 100.0),
          ("radius",   "Radius",   "float", 25.0, 0.0, 100.0),
          ("softness", "Softness", "float", 50.0, 0.0, 100.0)],
         fx_soft_glow,
         help="Dreamy blurred screen-blend glow — softer and more diffuse than Glow.")

ID = "soft_glow"

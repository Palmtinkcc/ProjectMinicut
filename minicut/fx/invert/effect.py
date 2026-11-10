"""invert: Invert. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_invert(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    f = img[..., :3].astype(np.float32); out = img.copy(); out[..., :3] = np.clip(f + (255 - 2 * f) * a + .5, 0, 255).astype(np.uint8); return out

register("invert", "Color", "Invert",
         [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
         fx_invert)

ID = "invert"

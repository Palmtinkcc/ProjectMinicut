"""noise: Noise. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_noise(img, p, ctx):
    """Block noise / TV static — different from film grain."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    h, w   = img.shape[:2]
    rng    = np.random.default_rng(int(ctx.lt * 30) * 48611 + 7)
    noise  = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    out    = img.copy()
    out[..., :3] = np.clip(img[..., :3].astype(np.float32) * (1 - amount) +
                           noise.astype(np.float32) * amount + .5, 0, 255).astype(np.uint8)
    return out

register("noise", "Stylize", "Noise",
         [("amount", "Amount", "float", 30.0, 0.0, 100.0)],
         fx_noise,
         help="Additive white noise / TV static.")

ID = "noise"

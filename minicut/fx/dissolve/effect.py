"""dissolve: Dissolve. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_dissolve(img, p, ctx):
    """Random pixel alpha dissolve — AM's Dissolve/Block Dissolve."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    h, w   = img.shape[:2]
    rng    = np.random.default_rng(int(ctx.lt * 24) * 65537 + 13)
    mask   = rng.random((h, w), dtype=np.float32)
    keep   = (mask >= amount).astype(np.uint8) * 255
    out    = img.copy()
    out[..., 3] = (img[..., 3].astype(np.float32) * (keep / 255.0) + .5).astype(np.uint8)
    return out

register("dissolve", "Stylize", "Dissolve",
         [("amount", "Amount", "float", 50.0, 0.0, 100.0)],
         fx_dissolve,
         help="Random pixel dissolve using the layer's existing alpha.")


# ------------------------------------------------------------------ GPU version
from ..pool.cpu_color import *

def fx_dissolve(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = fbm(h, w, S(ctx, p["scale"]), int(p["seed"]), 0, 4); soft = p["soft"] / 100.0 * 0.3 + 0.002; t = pr * (1 + soft) - soft * 0.5
    m = np.clip((n - t) / soft, 0, 1); out = _alpha_mul(img, m)
    if p["edge"] > 0:
        e = np.clip(1 - np.abs(n - t) / (p["edge"] / 100.0 * 0.12 + 1e-3), 0, 1) * (pr > 0) * (img[..., 3] * (1 / 255)); out = blend(out, np.broadcast_to(bgr(p["color"]), (h, w, 3)), e * (m > 0.01), "add", 1.0)
    return out

reg("dissolve", C2, "Dissolve", WIPE(50) + [F("scale", "Noise size", 60, 6, 400), F("soft", "Softness", 30, 0, 100), F("edge", "Glowing edge", 40, 0, 100), C("color", "Edge color", "#ffb347"), SEED()], fx_dissolve, "The picture dissolves like smoke or paper, with a glowing edge.", "burn noise fade")

ID = "dissolve"

"""grain: Film Grain. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_grain(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]; s = max(1, int(round(p["size"] * ctx.k)))
    color_grain = p.get("color_grain", False)
    rng = np.random.default_rng(int(ctx.lt * 24) * 104729 + 17)
    gh, gw = max(1, h // s), max(1, w // s)
    if color_grain:
        n = rng.standard_normal((gh, gw, 3)).astype(np.float32)
    else:
        n = rng.standard_normal((gh, gw)).astype(np.float32)[..., None] * np.ones(3, np.float32)
    if s > 1: n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)
    if n.ndim == 2: n = n[..., None]
    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) + n * 40 * a + .5, 0, 255).astype(np.uint8); return out

register("grain", "Stylize", "Film Grain",
         [("amount",      "Amount",      "float", 25.0, 0.0, 100.0),
          ("size",        "Grain size",  "float", 1.0,  1.0, 10.0),
          ("color_grain", "Color grain", "bool",  False, None, None)],
         fx_grain,
         help="Film grain noise. Color grain adds per-channel color noise like real film stock.")

ID = "grain"

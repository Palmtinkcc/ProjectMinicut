"""distortrgb: Distort RGB. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_distortrgb(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; out = img.copy(); x, y = coords(h, w)
    for c, off in ((2, 0), (1, 5), (0, 11)):
        if p["kind"] == "wave": dx = np.sin(y / s * 2 * np.pi + t * 2 + off) * p["amount"] * ctx.k; dy = np.sin(x / s * 2 * np.pi + t * 2 + off * 0.7) * p["amount"] * ctx.k * 0.5
        else: dx = (fbm(h, w, s, int(p["seed"]) + off, t, 3) - 0.5) * 2 * p["amount"] * ctx.k; dy = (fbm(h, w, s, int(p["seed"]) + off + 1, t, 3) - 0.5) * 2 * p["amount"] * ctx.k
        out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), (x + dx).astype(np.float32), (y + dy).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out

reg("distortrgb", LN, "Distort RGB", [F("amount", "Amount", 14, 0, 100), F("size", "Size", 90, 10, 500), CH("kind", "Pattern", "noise", [("noise", "Noise"), ("wave", "Waves")]), F("speed", "Speed", 0.6, 0, 8), SEED()], fx_distortrgb, "The red, green and blue parts of the picture are bent differently, so colors split apart.", "rgb wobble separation")

ID = "distortrgb"

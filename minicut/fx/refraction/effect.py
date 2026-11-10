"""refraction: Refraction warp. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_refraction(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; n = fbm(h, w, s, int(p["seed"]), t, 3); gy, gx = np.gradient(cv2.GaussianBlur(n, (0, 0), 1.2)); k = p["strength"] * ctx.k * 60; out = img.copy(); x, y = coords(h, w); sp = p["dispersion"] / 10.0
    for c, m in ((2, 1 + sp), (1, 1.0), (0, 1 - sp)): out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), (x + gx * k * m).astype(np.float32), (y + gy * k * m).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out

reg("refraction", WG, "Refraction warp", [F("strength", "Strength", 10, 0, 100), F("size", "Size", 60, 5, 400), F("dispersion", "Color split", 20, 0, 100), F("speed", "Speed", 0.4, 0, 5), SEED()], fx_refraction, "Light bends through uneven glass or water, splitting the colors a little.", "caustics distortion lens")

ID = "refraction"

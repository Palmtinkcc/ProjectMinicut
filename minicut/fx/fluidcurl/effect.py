"""fluidcurl: Fluid distortion (curl noise). CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_fluidcurl(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); psi = fbm(h, w, s, int(p["seed"]), ctx.lt * p["speed"], 4); gy, gx = np.gradient(psi); n = max(1e-4, float(np.abs(gx).max() + np.abs(gy).max()) / 2); vx, vy = gy / n, -gx / n
    return displace(img, vx * p["amount"] * ctx.k, vy * p["amount"] * ctx.k)

reg("fluidcurl", LN, "Fluid distortion (curl noise)", [F("amount", "Amount", 22, 0, 300), F("size", "Size", 150, 10, 600), F("speed", "Speed", 0.5, 0, 6), SEED()], fx_fluidcurl, "Flows like a liquid, using swirls that never bunch up or stretch the picture too much.", "smoke flow")

ID = "fluidcurl"

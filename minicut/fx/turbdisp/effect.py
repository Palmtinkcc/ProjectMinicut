"""turbdisp: Turbulent displace. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_turbdisp(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; dx = (fbm(h, w, s, int(p["seed"]), t, int(p["detail"])) - 0.5) * 2; dy = (fbm(h, w, s, int(p["seed"]) + 9, t, int(p["detail"])) - 0.5) * 2; return displace(img, dx * p["amount"] * ctx.k, dy * p["amount"] * ctx.k)

reg("turbdisp", DW, "Turbulent displace", [F("amount", "Amount", 40, 0, 300), F("size", "Size", 120, 5, 600), I("detail", "Detail", 3, 1, 6), F("speed", "Evolution speed", 0.6, 0, 8), SEED()], fx_turbdisp, "Pushes the pixels with swirling noise, like heat haze.", "turbulence heat haze")

ID = "turbdisp"

"""wavewarp: Wave warp. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_wavewarp(img, p, ctx):
    t = ctx.lt * p["speed"] * 2 * np.pi; h, w = img.shape[:2]; x, y = coords(h, w); L = S(ctx, p["length"]); return remap(img, x + np.sin(y / L * 2 * np.pi + t) * p["ax"] * ctx.k, y + np.sin(x / L * 2 * np.pi * 0.9 - t) * p["ay"] * ctx.k)

reg("wavewarp", DW, "Wave warp", [F("ax", "Sideways", 12, 0, 200), F("ay", "Up and down", 0, 0, 200), F("length", "Wave length", 80, 5, 600), F("speed", "Speed", 0.5, -5, 5)], fx_wavewarp, "The picture ripples like a flag in the wind.", "wobble flag sine")

ID = "wavewarp"

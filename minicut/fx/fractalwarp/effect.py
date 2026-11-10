"""fractalwarp: Fractal warp. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_fractalwarp(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; px, py = x.copy(), y.copy(); amp = p["amount"] * ctx.k; sd = int(p["seed"])
    for i in range(int(p["iterations"])):
        nx = remap(fbm(h, w, s / (1 + i * 0.7), sd + i * 3, t + i, 3), px, py, cv2.BORDER_REFLECT) if False else fbm(h, w, s / (1 + i * 0.7), sd + i * 3, t + i, 3); ny = fbm(h, w, s / (1 + i * 0.7), sd + i * 3 + 1, t + i, 3)
        px = px + (nx - 0.5) * amp / (1 + i * 0.5); py = py + (ny - 0.5) * amp / (1 + i * 0.5)
    return remap(img, px, py)

reg("fractalwarp", DW, "Fractal warp", [F("amount", "Amount", 80, 0, 400), F("size", "Size", 160, 10, 600), I("iterations", "Layers", 3, 1, 6), F("speed", "Speed", 0.4, 0, 6), SEED()], fx_fractalwarp, "Layers of noise bend the picture again and again into organic shapes.", "organic liquid marble")

ID = "fractalwarp"

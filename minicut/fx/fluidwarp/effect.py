"""fluidwarp: Fluid warp. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_fluidwarp(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; px, py = x.copy(), y.copy(); fa = (fbm(h, w, s, int(p["seed"]), t, 3) - 0.5) * 2 * np.pi * 2; vx, vy = np.cos(fa), np.sin(fa); st = p["amount"] * ctx.k / int(p["steps"])
    for _ in range(int(p["steps"])): ux = cv2.remap(vx.astype(np.float32), px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); uy = cv2.remap(vy.astype(np.float32), px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); px = px + ux * st; py = py + uy * st
    return remap(img, px, py)

reg("fluidwarp", LN, "Fluid warp", [F("amount", "Amount", 45, 0, 600), F("size", "Size", 160, 20, 600), I("steps", "Smoothness", 6, 2, 14), F("speed", "Speed", 0.4, 0, 6), SEED()], fx_fluidwarp, "The picture is dragged along swirling currents, like paint stirred in water.", "marbling stir")

ID = "fluidwarp"

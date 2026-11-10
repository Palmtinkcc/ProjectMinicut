"""dispmap: Displacement map. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_dispmap(img, p, ctx):
    h, w = img.shape[:2]
    if p["source"] == "self": m = lum8(img)
    else: m = fbm(h, w, S(ctx, p["scale"]), int(p["seed"]), ctx.lt * p["speed"], 3)
    if p["smooth"] > 0: m = cv2.GaussianBlur(m, (0, 0), p["smooth"] * ctx.k * 0.5)
    a = np.deg2rad(p["angle"]); d = (m - 0.5) * p["strength"] * ctx.k; return displace(img, np.cos(a) * d, np.sin(a) * d)

reg("dispmap", DW, "Displacement map", [CH("source", "Map made from", "noise", [("noise", "Noise"), ("self", "The picture's brightness")]), F("strength", "Strength", 40, -300, 300), F("angle", "Direction", 45, -180, 180), F("scale", "Noise size", 40, 3, 300), F("smooth", "Smooth the map", 2, 0, 40), F("speed", "Speed", 0.5, 0, 8), SEED()], fx_dispmap, "Pushes the pixels around following a map: noise, or the brightness of the picture itself.", "displace")

ID = "dispmap"

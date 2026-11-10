"""repradial: Radial repeat. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_repradial(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); R = p["radius"] * ctx.k; copies = []
    for i in range(n):
        a = 2 * np.pi * i / n + np.deg2rad(p["start"] + ctx.lt * p["spin"]); M = xform(h, w, np.cos(a) * R, np.sin(a) * R, np.rad2deg(a) * p["turn"] / 100.0, p["size"] / 100.0); copies.append(_place(img, M))
    return _comp(copies, h, w)

reg("repradial", RP, "Radial repeat", [I("count", "Copies", 6, 2, 36), F("radius", "Radius", 90, 0, 600), F("size", "Size of each", 45, 5, 150), F("turn", "Turn each", 100, 0, 100), F("start", "Start angle", 0, -180, 180), F("spin", "Spin (deg / s)", 20, -360, 360)], fx_repradial, "Copies of the picture placed around a circle.", "circle kaleidoscope ring")

ID = "repradial"

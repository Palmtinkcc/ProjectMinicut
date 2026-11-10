"""reppath: Repeat along path. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_reppath(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); copies = []
    for i in range(n):
        u = i / max(1, n - 1) + ctx.lt * p["speed"] * 0.1; u -= np.floor(u) if p["loop"] else 0
        if p["path"] == "wave": px = (u - 0.5) * w * 0.9; py = np.sin(u * 2 * np.pi * 2) * h * 0.25; rot = np.cos(u * 4 * np.pi) * 25
        elif p["path"] == "circle": px = np.cos(u * 2 * np.pi) * w * 0.3; py = np.sin(u * 2 * np.pi) * h * 0.3; rot = np.rad2deg(u * 2 * np.pi)
        else: rr = u * min(w, h) * 0.45; px = np.cos(u * 6 * np.pi) * rr; py = np.sin(u * 6 * np.pi) * rr; rot = np.rad2deg(u * 6 * np.pi)
        copies.append(_place(img, xform(h, w, px, py, rot * p["turn"] / 100.0, p["size"] / 100.0)))
    return _comp(copies, h, w)

reg("reppath", RP, "Repeat along path", [I("count", "Copies", 10, 2, 40), CH("path", "Path", "wave", [("wave", "Wave"), ("circle", "Circle"), ("spiral", "Spiral")]), F("size", "Size of each", 35, 5, 120), F("turn", "Turn with the path", 100, 0, 100), F("speed", "Speed", 1.0, -10, 10), B("loop", "Loop", True)], fx_reppath, "Copies of the picture placed along a wave, a circle or a spiral (and they can travel along it).", "trail curve snake")

ID = "reppath"

"""ghost: Ghost. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_ghost(img, p, ctx):
    out = img; n = int(p["count"]); ang = np.deg2rad(p["angle"]); step = p["distance"] * ctx.k
    for i in range(n, 0, -1):
        M = np.float32([[1, 0, np.cos(ang) * step * i], [0, 1, np.sin(ang) * step * i]]); lay = affine(img, M)
        if p["tint"] != "#ffffff": t = bgr(p["tint"]); lay[..., :3] = np.clip(lay[..., :3].astype(np.float32) * t[None, None] + 0, 0, 255).astype(np.uint8)
        out = _under(out, lay, (p["fade"] / 100.0) ** i * 1.0 + 0.0)
    return out

reg("ghost", V, "Ghost", [I("count", "Copies", 3, 1, 8), F("distance", "Distance", 14, 1, 120), F("angle", "Angle", 0, -180, 180), F("fade", "Visibility", 70, 5, 100), C("tint", "Tint", "#ffffff")], fx_ghost, "Faint copies of the picture trailing behind it (turn on Spill outside the media to see them past the edges).", "echo trail double")

ID = "ghost"

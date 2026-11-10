"""scatterglitch: Scatter glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_scatterglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); s = S(ctx, p["cell"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); mx = a * w * 0.12
    dx = r.normal(0, mx, (gh, gw)).astype(np.float32); dy = r.normal(0, mx * 0.5, (gh, gw)).astype(np.float32); z = r.random((gh, gw)) > a * 0.9
    dx[z] = 0; dy[z] = 0; up = lambda g: cv2.resize(g, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]
    return displace(img, up(dx), up(dy), cv2.BORDER_REFLECT)

reg("scatterglitch", G, "Scatter glitch", GP([F("cell", "Piece size", 12, 2, 80)]), fx_scatterglitch, "Small pieces of the picture are thrown a little away from where they belong.", "scatter pieces")

ID = "scatterglitch"

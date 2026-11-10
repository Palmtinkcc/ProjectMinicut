"""noiseglitch: Noise glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_noiseglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(1 + a * 10)):
        bw = int(w * r.uniform(0.1, 0.6)); bh = int(h * r.uniform(0.01, 0.12)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh)))
        nz = r.integers(0, 256, (bh, bw, 1), dtype=np.uint8) if p["mono"] else r.integers(0, 256, (bh, bw, 3), dtype=np.uint8)
        out[y0:y0 + bh, x0:x0 + bw, :3] = (out[y0:y0 + bh, x0:x0 + bw, :3] * (1 - a * 0.6) + nz * (a * 0.6)).astype(np.uint8)
    return out

reg("noiseglitch", G, "Noise glitch", GP([B("mono", "Gray noise", False)]), fx_noiseglitch, "Bursts of digital noise cover strips of the picture.", "static burst")

ID = "noiseglitch"

"""noiseline: Noise line. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_noiseline(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy(); col = (np.array(bgr(p["color"])) * 255).astype(np.uint8)
    for _ in range(int(2 + a * 60)):
        y = int(r.integers(0, h)); th = max(1, int(S(ctx, r.integers(1, 3)))); x0 = int(r.integers(0, w)); ln = int(w * r.uniform(0.05, 0.6) * (0.4 + a)); x1 = min(w, x0 + ln)
        nz = r.integers(0, 256, (th, x1 - x0, 1), dtype=np.uint8); out[y:y + th, x0:x1, :3] = (nz * 0.5 + col * 0.5).astype(np.uint8) if p["tinted"] else nz
    return out

reg("noiseline", G, "Noise line", GP([C("color", "Color", "#ffffff"), B("tinted", "Tint the lines", False)]), fx_noiseline, "Thin lines of noise flash across the picture.", "static lines")

ID = "noiseline"

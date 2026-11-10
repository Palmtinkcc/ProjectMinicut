"""glitchbox: Glitch box. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_glitchbox(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(1 + a * 16)):
        bw = int(w * r.uniform(0.05, 0.4)); bh = int(h * r.uniform(0.02, 0.22)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh))); k = int(r.integers(0, 4))
        reg_ = out[y0:y0 + bh, x0:x0 + bw]; src = img[y0:y0 + bh, :]; dx = int(r.normal(0, w * 0.1 * a))
        if k == 0: reg_[:] = np.roll(src, dx, axis=1)[:, x0:x0 + bw]
        elif k == 1: reg_[..., :3] = 255 - reg_[..., :3]
        elif k == 2: reg_[..., :3] = reg_[..., ::-1][..., 1:4][..., ::-1][..., :3] if False else reg_[..., [2, 0, 1]]
        else: reg_[..., 2] = np.roll(src, dx, axis=1)[:, x0:x0 + bw][..., 2]
    return out

reg("glitchbox", G, "Glitch box", GP(), fx_glitchbox, "Random rectangles slide sideways, flip their colors or swap channels.", "block blocks digital")

ID = "glitchbox"

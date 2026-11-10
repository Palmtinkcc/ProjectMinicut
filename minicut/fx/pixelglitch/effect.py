"""pixelglitch: Pixel glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_pixelglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(2 + a * 14)):
        bw = int(w * r.uniform(0.08, 0.5)); bh = int(h * r.uniform(0.05, 0.3)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh))); s = S(ctx, r.integers(4, 40))
        blk = out[y0:y0 + bh, x0:x0 + bw]
        if blk.size == 0: continue
        sm = cv2.resize(blk, (max(1, int(blk.shape[1] / s)), max(1, int(blk.shape[0] / s))), interpolation=cv2.INTER_AREA); out[y0:y0 + bh, x0:x0 + bw] = cv2.resize(sm, (blk.shape[1], blk.shape[0]), interpolation=cv2.INTER_NEAREST)
    return out

reg("pixelglitch", G, "Pixel glitch", GP(), fx_pixelglitch, "Parts of the picture turn into big blocky pixels for a moment.", "pixelate blocks")

ID = "pixelglitch"

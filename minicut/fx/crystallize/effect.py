"""crystallize: Crystallize. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_crystallize(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); gx, gy = int(np.ceil(w / s)) + 2, int(np.ceil(h / s)) + 2; r = np.random.default_rng(int(p["seed"])); jx = (r.random((gy, gx)) - 0.5) * p["jitter"] / 100.0 * s * 1.6; jy = (r.random((gy, gx)) - 0.5) * p["jitter"] / 100.0 * s * 1.6
    sx = (np.arange(gx)[None, :] + 0.5) * s - s + jx; sy = (np.arange(gy)[:, None] + 0.5) * s - s + jy; x1 = np.arange(w, dtype=np.float32); y1 = np.arange(h, dtype=np.float32); ci = (x1 // s).astype(int) + 1; cj = (y1 // s).astype(int) + 1; lab = np.zeros((h, w), np.int32)
    for b0 in range(0, h, 32):          # the nearest of the 9 candidate sites, band by band (the same sums and comparisons as one pass over the whole picture, without the big temporaries)
        b1 = min(h, b0 + 32); yb = y1[b0:b1, None]; xb = x1[None, :]; best = np.full((b1 - b0, w), 1e18, np.float32); lb = np.zeros((b1 - b0, w), np.int32)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                ii = np.clip(ci + di, 0, gx - 1); jj = np.clip(cj[b0:b1] + dj, 0, gy - 1); d = (xb - sx[jj][:, ii]) ** 2 + (yb - sy[jj][:, ii]) ** 2; upd = d < best
                best = np.where(upd, d.astype(np.float32), best); lb = np.where(upd, jj[:, None] * gx + ii[None, :], lb)
        lab[b0:b1] = lb
    n = gx * gy; cnt = np.bincount(lab.ravel(), minlength=n).astype(np.float32); out = np.zeros_like(img, np.float32)
    for c in range(4): out[..., c] = (np.bincount(lab.ravel(), img[..., c].astype(np.float32).ravel(), minlength=n) / np.maximum(cnt, 1))[lab]
    if p["edge"] > 0:
        e = (lab != np.roll(lab, 1, 0)) | (lab != np.roll(lab, 1, 1)); out[e, :3] *= 1 - p["edge"] / 100.0 * 0.7
    return np.clip(out, 0, 255).astype(np.uint8)

reg("crystallize", IK, "Crystallize", [F("size", "Cell size", 22, 4, 120), F("jitter", "Irregularity", 80, 0, 100), F("edge", "Cell edges", 30, 0, 100), SEED()], fx_crystallize, "The picture becomes flat-colored crystal cells.", "voronoi mosaic stained glass")

ID = "crystallize"

"""vcr: VCR glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_vcr(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 15); sh = np.zeros(h, np.float32); y0 = int(h * (0.78 + 0.18 * r.random())); sh[y0:] = r.normal(0, w * 0.05 * a, h - y0)
    for _ in range(int(a * 4)): yy = int(r.integers(0, h)); sh[yy:yy + int(r.integers(2, 10))] += r.normal(0, w * 0.1 * a)
    out = shift_rows(img, sh); out[..., 0] = np.roll(out[..., 0], int(-3 * ctx.k * a), axis=1); out[..., 2] = np.roll(out[..., 2], int(3 * ctx.k * a), axis=1)
    nz = (r.random((h - y0, w, 1)) * 255 * a * 0.7).astype(np.uint8); out[y0:, :, :3] = np.clip(out[y0:, :, :3].astype(np.int16) * 0.5 + nz, 0, 255).astype(np.uint8); return out

reg("vcr", V, "VCR glitch", [F("amount", "Amount", 55, 0, 100), SEED()], fx_vcr, "A tracking error at the bottom of the picture with torn lines and colored edges.", "tracking error tape")

ID = "vcr"

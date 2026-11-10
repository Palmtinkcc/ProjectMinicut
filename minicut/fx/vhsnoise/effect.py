"""vhsnoise: VHS noise. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_vhsnoise(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 30); out = img.copy(); f = f3(out)
    nz = r.random((h, w, 1)).astype(np.float32); f = f + (nz - 0.5) * 0.35 * a; y = np.arange(h)
    for _ in range(int(1 + a * 4)):
        y0 = int(r.integers(0, h)); hh = int(r.integers(2, max(3, h // 14))); f[y0:y0 + hh] = f[y0:y0 + hh] * 0.4 + r.random((min(hh, h - y0), w, 1)).astype(np.float32) * 0.6 * (0.5 + a)
    return pack(np.clip(f, 0, 1), like=img)

reg("vhsnoise", V, "VHS noise", [F("amount", "Amount", 50, 0, 100), SEED()], fx_vhsnoise, "Grainy video noise with a few horizontal static bands.", "vsh static")

ID = "vhsnoise"

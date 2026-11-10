"""tapenoise: Tape noise. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_tapenoise(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 24); out = img.copy()
    for _ in range(int(2 + a * 40)):
        y = int(r.integers(0, h)); x0 = int(r.integers(0, w)); ln = int(w * r.uniform(0.02, 0.25)); x1 = min(w, x0 + ln); th = max(1, int(S(ctx, r.integers(1, 3)))); v = int(r.integers(140, 256))
        out[y:y + th, x0:x1, :3] = (out[y:y + th, x0:x1, :3] * 0.3 + v * 0.7).astype(np.uint8)
    dark = (r.random((h, w)) < a * 0.01); out[dark, :3] = 0; return out

reg("tapenoise", V, "Tape noise", [F("amount", "Amount", 50, 0, 100), SEED()], fx_tapenoise, "Short white dashes and dark specks, like dropouts on magnetic tape.", "dropout dashes")

ID = "tapenoise"

"""jitter: Random jitter. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_jitter(img, p, ctx):
    r = rng(ctx, p["seed"], p["rate"]); t = ctx.lt * p["rate"]; i = int(t); f = t - i; a = np.random.default_rng(int(p["seed"]) * 7 + i); b = np.random.default_rng(int(p["seed"]) * 7 + i + 1)
    va = a.uniform(-1, 1, 3); vb = b.uniform(-1, 1, 3); v = va * (1 - f) + vb * f; return _tf(img, ctx, v[0] * p["amount"], v[1] * p["amount"], v[2] * p["tilt"])

reg("jitter", MV, "Random jitter", [F("amount", "Amount", 8, 0, 100), F("tilt", "Tilt", 0.8, 0, 10), F("rate", "Speed", 10, 0.5, 40), SEED()], fx_jitter, "A small, nervous, smooth trembling.", "tremble")

ID = "jitter"

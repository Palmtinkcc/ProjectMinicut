"""shake: Simple shake. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_shake(img, p, ctx):
    r = rng(ctx, p["seed"], p["speed"]); a = p["amount"]; return _tf(img, ctx, r.normal(0, a * 0.5), r.normal(0, a * 0.5), r.normal(0, p["tilt"] * 0.4))

reg("shake", SH, "Simple shake", [F("amount", "Strength", 12, 0, 100), F("tilt", "Tilt", 1.5, 0, 15), F("speed", "Shakes / s", 24, 1, 60), SEED()], fx_shake, "A quick random shake.", "jitter vibrate")

ID = "shake"

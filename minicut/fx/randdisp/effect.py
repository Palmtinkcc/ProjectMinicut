"""randdisp: Random displacement. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_randdisp(img, p, ctx):
    r = rng(ctx, p["seed"], p["rate"]); return _tf(img, ctx, r.uniform(-1, 1) * p["x"], r.uniform(-1, 1) * p["y"])

reg("randdisp", MV, "Random displacement", [F("x", "Distance X", 80, 0, 600), F("y", "Distance Y", 50, 0, 600), F("rate", "Jumps / s", 4, 0.2, 30), SEED()], fx_randdisp, "The picture jumps to a new random place again and again.", "jump teleport")

ID = "randdisp"

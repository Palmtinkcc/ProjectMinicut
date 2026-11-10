"""handheld: Handheld camera. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_handheld(img, p, ctx):
    h, w = img.shape[:2]; t = ctx.lt * p["speed"]; sd = int(p["seed"]); n = lambda k: (noise(8, 8, 2, sd + k, t)[4, 4] - 0.5) * 2 * 2.2
    s = 1 + p["amount"] / 400.0; return _tf(img, ctx, n(1) * p["amount"], n(2) * p["amount"], n(3) * p["amount"] * 0.04, s)

reg("handheld", SH, "Handheld camera", [F("amount", "Amount", 14, 0, 100), F("speed", "Speed", 1.5, 0.1, 10), SEED()], fx_handheld, "A smooth, slow wobble like a camera held in the hands.", "camera shake smooth")

ID = "handheld"

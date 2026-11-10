"""bounce: Bounce. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_bounce(img, p, ctx):
    ph = (ctx.lt * p["speed"]) % 1.0; y = -abs(np.sin(ph * np.pi)) * p["height"]; sq = 1 - 0.12 * p["squash"] / 100.0 * (1 - abs(np.sin(ph * np.pi))); return _tf(img, ctx, 0, y, 0, 1.0 / sq if False else 1.0, 0.5, 1.0) if p["squash"] <= 0 else affine(img, np.float32([[1 + (1 - sq), 0, -img.shape[1] * (1 - sq) / 2], [0, sq, y * ctx.k + img.shape[0] * (1 - sq)]]))

reg("bounce", SH, "Bounce", [F("height", "Height", 60, 0, 400), F("speed", "Bounces / s", 1.2, 0.1, 6), F("squash", "Squash", 40, 0, 100)], fx_bounce, "The picture bounces up and down and squashes when it lands.", "jump ball")

ID = "bounce"

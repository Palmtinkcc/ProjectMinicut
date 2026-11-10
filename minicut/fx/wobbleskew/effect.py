"""wobbleskew: Skew wobble. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_wobbleskew(img, p, ctx):
    h, w = img.shape[:2]; k = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["amount"] / 100.0 * 0.35; M = np.float32([[1, k, -k * h / 2], [np.sin(ctx.lt * p["speed"] * 2 * np.pi + 1) * p["amount"] / 100.0 * 0.08, 1, 0]]); return affine(img, M)

reg("wobbleskew", SH, "Skew wobble", [F("amount", "Amount", 40, 0, 100), F("speed", "Wobbles / s", 0.8, 0.1, 6)], fx_wobbleskew, "The picture leans left and right like jelly.", "jelly lean")

ID = "wobbleskew"

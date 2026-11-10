"""sortglitch: Sort glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_sortglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy(); vert = p["direction"] == "vertical"; n = w if vert else h
    for _ in range(int(1 + a * 8)):
        s0 = int(r.integers(0, n)); s1 = min(n, s0 + int(n * r.uniform(0.03, 0.25))); lo = r.uniform(0.0, 0.5); hi = min(1.0, lo + r.uniform(0.2, 0.7)); key = ("lum", "hue", "red")[int(r.integers(0, 3))]
        if vert: out[:, s0:s1] = _sort(out[:, s0:s1], lo, hi, key, bool(r.integers(0, 2)), True)
        else: out[s0:s1] = _sort(out[s0:s1], lo, hi, key, bool(r.integers(0, 2)), False)
    return out

reg("sortglitch", G, "Sort glitch", GP([CH("direction", "Direction", "horizontal", [("horizontal", "Horizontal"), ("vertical", "Vertical")])]), fx_sortglitch, "Random bands of the picture get sorted, each one differently, and change over time.", "pixel sort random")

ID = "sortglitch"

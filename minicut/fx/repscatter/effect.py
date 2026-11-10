"""repscatter: Scatter repeat. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_repscatter(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); copies = []; t = ctx.lt * p["drift"]
    for i in range(n):
        ph = r.random(3) * 6.28; sc_ = r.uniform(min(p["min"], p["max"]), max(p["min"], p["max"], 1e-3)) / 100.0
        copies.append(_place(img, xform(h, w, (r.uniform(-0.5, 0.5) * w * p["spread"] / 50.0) + np.sin(t + ph[0]) * w * 0.02, (r.uniform(-0.5, 0.5) * h * p["spread"] / 50.0) + np.cos(t + ph[1]) * h * 0.02, r.normal(0, p["rot"]), sc_)))
    return _comp(copies, h, w)

reg("repscatter", RP, "Scatter repeat", [I("count", "Copies", 14, 2, 80), F("spread", "Spread", 60, 0, 100), F("min", "Smallest", 15, 2, 100), F("max", "Biggest", 40, 2, 150), F("rot", "Tilt", 20, 0, 90), F("drift", "Drift", 1.0, 0, 10), SEED()], fx_repscatter, "Copies scattered at random places, sizes and angles.", "random confetti copies")

ID = "repscatter"

"""impact: Impact shake. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_impact(img, p, ctx):
    ph = (ctx.lt * p["rate"]) % 1.0; k = np.exp(-ph * p["decay"]); r = np.random.default_rng(int(p["seed"]) + int(ctx.lt * p["rate"]) * 31); ang = r.uniform(0, 6.28)
    d = p["strength"] * k * np.cos(ph * 60); return _tf(img, ctx, np.cos(ang) * d, np.sin(ang) * d, r.normal(0, 1) * k * p["tilt"], 1 + p["zoom"] / 100.0 * k)

reg("impact", SH, "Impact shake", [F("strength", "Strength", 50, 0, 300), F("rate", "Hits / s", 1.0, 0.1, 8), F("decay", "Calms down", 6, 1, 20), F("tilt", "Tilt", 3, 0, 20), F("zoom", "Punch zoom", 6, 0, 40), SEED()], fx_impact, "A hard hit: a strong shake and a little zoom that calms down, over and over.", "punch hit bang")

ID = "impact"

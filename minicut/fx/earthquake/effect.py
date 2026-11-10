"""earthquake: Earthquake. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_earthquake(img, p, ctx):
    t = ctx.lt * p["speed"]; a = p["amount"]; return _tf(img, ctx, np.sin(t * 7.1) * a * 0.6 + np.sin(t * 17.3) * a * 0.4, np.sin(t * 11.7 + 1) * a, np.sin(t * 5.3) * p["tilt"])

reg("earthquake", SH, "Earthquake", [F("amount", "Strength", 30, 0, 200), F("tilt", "Tilt", 2, 0, 15), F("speed", "Speed", 2.0, 0.2, 10)], fx_earthquake, "A heavy, rumbling shake.", "rumble")

ID = "earthquake"

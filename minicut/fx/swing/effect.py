"""swing: Swing. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_swing(img, p, ctx):
    ang = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["angle"]; return _tf(img, ctx, 0, 0, ang, 1.0, 0.5, p["pivot"] / 100.0)

reg("swing", SH, "Swing", [F("angle", "Angle", 12, 0, 90), F("speed", "Swings / s", 0.7, 0.05, 8), F("pivot", "Pivot height (0 = top)", 0, -50, 150)], fx_swing, "The picture swings from a point like a pendulum.", "pendulum rotate sway")

ID = "swing"

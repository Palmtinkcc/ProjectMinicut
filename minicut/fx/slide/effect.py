"""slide: Swing (slide). CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_slide(img, p, ctx):
    a = np.deg2rad(p["angle"]); d = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["distance"]; return _tf(img, ctx, np.cos(a) * d, np.sin(a) * d)

reg("slide", MV, "Swing (slide)", [F("distance", "Distance", 60, 0, 600), F("angle", "Direction", 0, -180, 180), F("speed", "Cycles / s", 0.5, 0.05, 6)], fx_slide, "The picture slides back and forth in a straight line.", "sway pendulum move left right")

ID = "slide"

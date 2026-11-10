"""spin: Spin. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_spin(img, p, ctx): return _tf(img, ctx, 0, 0, ctx.lt * p["speed"], 1.0, p["cx"] / 100.0, p["cy"] / 100.0)

reg("spin", MV, "Spin", [F("speed", "Speed (deg / s)", 90, -720, 720), F("cx", "Center X", 50, -50, 150), F("cy", "Center Y", 50, -50, 150)], fx_spin, "The picture turns around and around.", "rotate")

ID = "spin"

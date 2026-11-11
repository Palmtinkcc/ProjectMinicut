"""Mirror left/right, right/left, top/bottom, bottom/top or four ways around a centre. The kaleidoscope mode is left to the CPU (build returns None)."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "mirror"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    m = {"lr": 0, "rl": 1, "tb": 2, "bt": 3, "quad": 4}.get(p["mode"])
    if m is None: return None                                        # kaleidoscope: the CPU does it
    return Built([Pass(SH["main"], {"u_mode": m, "u_c": (w * float(p["cx"]) / 100.0, h * float(p["cy"]) / 100.0)})])

"""Emboss from the luminance, 3x3 kernel with the OpenCV default border (reflect 101). Scales above k = 1.5 are left to the CPU (it smooths first)."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "emboss"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    if c.k > 1.5: return None                                        # the CPU smooths the picture first at this scale
    a = math.radians(float(p["angle"])); sa, ca = math.sin(a), math.cos(a); d = float(p["depth"]) / 30.0
    rows = [[-sa - ca, -sa, ca - sa], [-ca, 1.0, ca], [sa - ca, sa, sa + ca]]
    # GLSL mat3 is column-major: u_kern[i][j] = rows[j][i]
    flat = [rows[j][i] * d for i in range(3) for j in range(3)]
    return Built([Pass(SH["main"], {"u_kern": tuple(flat), "u_mix": float(p["mix"]) / 100.0, "u_color": 1 if p["color"] else 0})])

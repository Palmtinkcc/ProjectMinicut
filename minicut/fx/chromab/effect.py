"""Chromatic aberration: red and blue are scaled and shifted in opposite directions, green stays."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "chromab"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    a = math.radians(float(p["angle"])); sh = float(p["shift"]) * c.k
    return Built([Pass(SH["main"], {"u_k": float(p["amount"]) / 1000.0, "u_o": (math.cos(a) * sh, math.sin(a) * sh)})])

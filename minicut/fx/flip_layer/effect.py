"""Flip the layer horizontally, vertically or both (exact pixel copy)."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "flip_layer"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    ax = p.get("axis", "horizontal")
    f = (1, 0) if ax == "horizontal" else ((0, 1) if ax == "vertical" else (1, 1))
    return Built([Pass(SH["main"], {"u_f": f})])

"""Flip the layer horizontally, vertically or both (exact pixel copy)."""
from ...shared.deps import *
from ...render.effects import register

def fx_flip_layer(img, p, ctx):
    axis = p.get("axis", "horizontal")
    if axis == "horizontal": return cv2.flip(img, 1)
    if axis == "vertical":   return cv2.flip(img, 0)
    return cv2.flip(img, -1)   # both

register("flip_layer", "Distort", "Flip Layer",
         [("axis", "Axis", "choice", "horizontal",
           [("horizontal", "Horizontal"), ("vertical", "Vertical"), ("both", "Both")], None)],
         fx_flip_layer,
         help="Flip the layer horizontally, vertically, or both.")


# ------------------------------------------------------------------ GPU version
import math

from ..pool.gl import Pass, Built, shaders

ID = "flip_layer"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    ax = p.get("axis", "horizontal")
    f = (1, 0) if ax == "horizontal" else ((0, 1) if ax == "vertical" else (1, 1))
    return Built([Pass(SH["main"], {"u_f": f})])

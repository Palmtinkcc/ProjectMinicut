"""Exposure (EV), gamma and offset."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "exposure"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    return Built([Pass(SH["main"], {"u_ev": 2.0 ** float(p["exposure"]), "u_off": float(p["offset"]) / 100.0, "u_ig": 1.0 / max(0.05, float(p["gamma"]))})])

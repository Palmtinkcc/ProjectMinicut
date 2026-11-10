"""Exposure (EV), gamma and offset."""
from ..pool.cpu_color import *

def fx_exposure(img, p, ctx):
    f = f3(img); f = np.power(np.clip(f * (2.0 ** p["exposure"]) + p["offset"] / 100.0, 0, 8), 1.0 / max(0.05, p["gamma"])); return pack(np.clip(f, 0, 1), like=img)

reg("exposure", C1, "Exposure / Gamma", [F("exposure", "Exposure (stops)", 0, -4, 4), F("gamma", "Gamma", 1.0, 0.2, 3), F("offset", "Offset", 0, -50, 50)], fx_exposure, "Exposure makes everything brighter or darker; gamma changes the middle tones only.", "brightness levels")


# ------------------------------------------------------------------ GPU version
import math

from ..pool.gl import Pass, Built, shaders

ID = "exposure"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    return Built([Pass(SH["main"], {"u_ev": 2.0 ** float(p["exposure"]), "u_off": float(p["offset"]) / 100.0, "u_ig": 1.0 / max(0.05, float(p["gamma"]))})])

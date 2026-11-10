"""Chromatic aberration: red and blue are scaled and shifted in opposite directions, green stays."""
from ..pool.cpu_warp import *

def fx_chroma(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; k = p["amount"] / 1000.0; out = img.copy(); a = np.deg2rad(p["angle"]); ox, oy = np.cos(a) * p["shift"] * ctx.k, np.sin(a) * p["shift"] * ctx.k
    for c, s_ in ((2, 1 - k), (0, 1 + k)):
        sx = cx + (x - cx) * s_ + (ox if c == 2 else -ox); sy = cy + (y - cy) * s_ + (oy if c == 2 else -oy); out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out

reg("chromab", LN, "Chromatic aberration", [F("amount", "Edge split", 25, 0, 100), F("shift", "Straight shift", 0, 0, 40), F("angle", "Shift direction", 0, -180, 180)], fx_chroma, "Red and blue fringes at the edges, like a cheap lens.", "color fringe rgb split lens")


# ------------------------------------------------------------------ GPU version
import math

from ..pool.gl import Pass, Built, shaders

ID = "chromab"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    a = math.radians(float(p["angle"])); sh = float(p["shift"]) * c.k
    return Built([Pass(SH["main"], {"u_k": float(p["amount"]) / 1000.0, "u_o": (math.cos(a) * sh, math.sin(a) * sh)})])

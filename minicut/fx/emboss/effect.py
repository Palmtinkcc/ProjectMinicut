"""Emboss from the luminance, 3x3 kernel with the OpenCV default border (reflect 101). Scales above k = 1.5 are left to the CPU (it smooths first)."""
from ..pool.cpu_strokes import *

def fx_emboss(img, p, ctx):
    a = np.deg2rad(p["angle"]); k = np.array([[-np.sin(a) - np.cos(a), -np.sin(a), np.cos(a) - np.sin(a)], [-np.cos(a), 1, np.cos(a)], [np.sin(a) - np.cos(a), np.sin(a), np.sin(a) + np.cos(a)]], np.float32)
    L = lum8(img); g = cv2.filter2D(L if ctx.k <= 1.5 else cv2.GaussianBlur(L, (0, 0), ctx.k * 0.5), -1, k * (p["depth"] / 30.0)); rel = np.clip(0.5 + g * 0.5, 0, 1); f = f3(img); m = p["mix"] / 100.0
    return pack(np.clip(f * (1 - m) + (rel[..., None] if not p["color"] else f * rel[..., None] * 2.0) * m, 0, 1), like=img)

reg("emboss", SS, "Emboss", [F("angle", "Light direction", 135, -180, 180), F("depth", "Depth", 40, 1, 150), F("mix", "Amount", 100, 0, 100), B("color", "Keep the colors", False)], fx_emboss, "The picture looks like it is pressed into metal or paper.", "relief 3d")


# ------------------------------------------------------------------ GPU version
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

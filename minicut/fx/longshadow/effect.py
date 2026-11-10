"""longshadow: Long shadow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_longshadow(img, p, ctx):
    a = np.deg2rad(p["angle"]); n = int(max(1, p["length"] * ctx.k)); al = _alpha(img); h, w = al.shape; acc = al.copy(); step = 1; d = np.array([np.cos(a), np.sin(a)])
    covered = 1
    while covered < n:
        s = min(step, n - covered); M = np.float32([[1, 0, d[0] * s], [0, 1, d[1] * s]]); acc = np.maximum(acc, cv2.warpAffine(acc, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)); covered += s; step *= 2
    return _shadow_under(img, acc, p["color"], p["opacity"] / 100.0)

reg("longshadow", SS, "Long shadow", [F("length", "Length", 120, 1, 600), F("angle", "Angle", 45, -180, 180), C("color", "Color", "#111111"), OPAC(80)], fx_longshadow, "A long flat shadow stretching away (turn on Spill outside the media).", "flat design extrude")

ID = "longshadow"

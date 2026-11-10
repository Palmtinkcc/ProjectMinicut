"""gradshadow: Gradient shadow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_gradshadow(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); a = np.deg2rad(p["angle"]); d = (x * np.cos(a) + y * np.sin(a)); e = (abs(np.cos(a)) * w / h + abs(np.sin(a))) / 2; t = np.clip((d / e + 1) / 2, 0, 1); m = sm(t, 1 - p["size"] / 100.0, 1.0) ** p["curve"]
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m, "over", p["opacity"] / 100.0)

reg("gradshadow", SS, "Gradient shadow", [F("angle", "Direction", 90, -180, 180), F("size", "Size", 60, 5, 100), F("curve", "Curve", 1.0, 0.3, 4), C("color", "Color", "#000000"), OPAC(80)], fx_gradshadow, "A smooth dark gradient from one side, good for text under the picture.", "fade dark side")

ID = "gradshadow"

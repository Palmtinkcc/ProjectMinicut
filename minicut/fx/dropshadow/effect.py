"""dropshadow: Drop shadow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_dropshadow(img, p, ctx):
    a = np.deg2rad(p["angle"]); d = p["distance"] * ctx.k; al = affine(_alpha(img)[..., None].repeat(4, 2).astype(np.float32), np.float32([[1, 0, np.cos(a) * d], [0, 1, np.sin(a) * d]]))[..., 0]
    if p["size"] > 0: al = cv2.dilate(al, np.ones((int(p["size"] * ctx.k) * 2 + 1,) * 2, np.uint8))
    al = glow_of(al, max(0.5, p["blur"] * ctx.k * 0.5)); return _shadow_under(img, al, p["color"], p["opacity"] / 100.0)

reg("dropshadow", SS, "Drop shadow", [F("distance", "Distance", 20, 0, 200), F("angle", "Angle", 60, -180, 180), F("blur", "Softness", 20, 0, 100), F("size", "Grow", 0, 0, 50), C("color", "Color", "#000000"), OPAC(70)], fx_dropshadow, "A shadow behind the picture (turn on Spill outside the media to see it past the edges).", "shadow offset")

ID = "dropshadow"

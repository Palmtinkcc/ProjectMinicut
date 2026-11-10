"""gaussshadow: Gaussian shadow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_gaussshadow(img, p, ctx):
    al = _alpha(img); al = cv2.dilate(al, np.ones((int(p["spread"] * ctx.k) * 2 + 1,) * 2, np.uint8)) if p["spread"] > 0 else al; al = np.clip(glow_of(al, p["blur"] * ctx.k * 0.5) * (1 + p["strength"] / 50.0), 0, 1); return _shadow_under(img, al, p["color"], p["opacity"] / 100.0)

reg("gaussshadow", SS, "Gaussian shadow", [F("blur", "Softness", 40, 1, 200), F("spread", "Spread", 4, 0, 60), F("strength", "Strength", 40, 0, 100), C("color", "Color", "#000000"), OPAC(80)], fx_gaussshadow, "A soft shadow all around the picture.", "soft glow around")

ID = "gaussshadow"

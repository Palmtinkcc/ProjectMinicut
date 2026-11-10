"""lumakey: Color / luma key. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_lumakey(img, p, ctx):
    f = f3(img)
    if p["key"] == "color":
        k = bgr(p["color"]); d = np.sqrt(((f - k) ** 2).sum(-1)) / 1.732; m = sm(d, p["tol"] / 100.0 * 0.6, p["tol"] / 100.0 * 0.6 + p["soft"] / 100.0 * 0.4 + 1e-3)
        out = _am(img, 1 - m if p["invert"] else m); return out
    L = lum(f); m = sm(L, p["low"] / 100.0, p["low"] / 100.0 + p["soft"] / 100.0 * 0.3 + 1e-3) * (1 - sm(L, p["high"] / 100.0, p["high"] / 100.0 + p["soft"] / 100.0 * 0.3 + 1e-3)); return _am(img, m if p["invert"] else 1 - m)

reg("lumakey", WP, "Color / luma key", [CH("key", "Key out", "luma", [("luma", "By brightness"), ("color", "By color")]), F("low", "Brightness from", 0, 0, 100), F("high", "Brightness up to", 15, 0, 100), C("color", "Key color", "#00ff00"), F("tol", "Color range", 35, 0, 100), F("soft", "Soft edge", 30, 0, 100), B("invert", "Keep the keyed part instead", False)], fx_lumakey,
    "Makes the dark parts, or one color (green screen), see-through.", "chroma key green screen luminance")

ID = "lumakey"

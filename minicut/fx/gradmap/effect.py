"""gradmap: Gradient map. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_gradmap(img, p, ctx):
    f = f3(img); g = lum(f); m = ramp(g, [(0.0, p["shadow"]), (0.5, p["mid"]), (1.0, p["high"])]); a = p["amount"] / 100.0
    return pack(f * (1 - a) + m * a, like=img)

reg("gradmap", C1, "Gradient map", [C("shadow", "Shadows", "#1b0b3a"), C("mid", "Midtones", "#d6336c"), C("high", "Highlights", "#ffe66d"), F("amount", "Amount", 100, 0, 100)], fx_gradmap, "Paints dark, middle and bright parts with three colors you choose.", "duotone tritone")

ID = "gradmap"

"""contourstrips: Contour strips. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_contourstrips(img, p, ctx):
    f = f3(img); L = lum(f); n = int(p["bands"]); band = np.floor(L * n) / n; edge = np.abs(((L * n) % 1.0) - 0.5) * 2; line = sm(edge, 1 - p["line"] / 100.0 * 0.4, 1.0)[..., None]
    col = ramp(band, [(0, p["c1"]), (0.5, p["c2"]), (1, p["c3"])]); out = col * (1 - line * 0.5) + line * bgr(p["c1"]) * 0.2; a = p["amount"] / 100.0; return pack(np.clip(f * (1 - a) + out * a, 0, 1), like=img)

reg("contourstrips", PR, "Contour strips", [I("bands", "Strips", 10, 2, 40), F("line", "Edge lines", 50, 0, 100), F("amount", "Amount", 100, 0, 100), C("c1", "Dark", "#0b132b"), C("c2", "Middle", "#3a86ff"), C("c3", "Light", "#fefae0")], fx_contourstrips, "Turns the brightness of the picture into flat colored strips, like a topographic map.", "posterize bands")

ID = "contourstrips"

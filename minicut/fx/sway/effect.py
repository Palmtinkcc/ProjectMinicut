"""sway: Sway. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_sway(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; f = (1 - y / h) if p["anchor"] == "bottom" else (y / h); return remap(img, x - np.sin(t + y / h * p["bend"]) * (f ** 1.5) * p["amount"] * ctx.k, y, cv2.BORDER_REFLECT)

reg("sway", LN, "Sway", [F("amount", "Amount", 40, 0, 300), F("speed", "Sways / s", 0.5, 0.05, 5), F("bend", "Bend", 2.0, 0, 8), CH("anchor", "Fixed at the", "bottom", [("bottom", "Bottom"), ("top", "Top")])], fx_sway, "The picture sways like a tree or a curtain, still at one edge.", "wind curtain")

ID = "sway"

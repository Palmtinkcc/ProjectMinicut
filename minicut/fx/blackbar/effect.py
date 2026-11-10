"""blackbar: Black bar. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_blackbar(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); co, ln = (y, h) if p["dir"] == "horizontal" else (x, w); d = np.minimum(co, ln - 1 - co) / ln; m = (d < pr * 0.5).astype(np.float32); m = cv2.GaussianBlur(m, (0, 0), max(0.4, p["soft"] * ctx.k * 0.3))
    if p["cut"]: return _am(img, 1 - m)
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m, "over", 1.0)

reg("blackbar", WP, "Black bar", WIPE(40) + [CH("dir", "Bars", "horizontal", [("horizontal", "Top and bottom"), ("vertical", "Left and right")]), C("color", "Color", "#000000"), F("soft", "Soft edge", 0, 0, 20), B("cut", "Cut away instead of covering", False)], fx_blackbar, "Bars close in from the edges, like the black bars of a film.", "cinema letterbox")

ID = "blackbar"

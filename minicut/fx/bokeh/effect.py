"""bokeh: Bokeh parallax. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_bokeh(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); cv = np.zeros((h, w, 3), np.float32); t = ctx.lt * p["speed"]; cols = [bgr(p["color"]), bgr(p["color2"])]
    for i in range(int(p["count"])):
        dep = r.random(); rad = S(ctx, p["size"]) * (0.5 + dep * 1.6); x = (r.random() * w + t * w * 0.04 * (0.3 + dep) * 1.0 + np.sin(t + r.random() * 6) * w * 0.02) % (w + 2 * rad) - rad; y = (r.random() * h - t * h * 0.02 * (0.3 + dep)) % (h + 2 * rad) - rad
        lay = np.zeros((h, w, 3), np.float32) if False else None; c = cols[i % 2] * (0.25 + 0.5 * dep) * (0.5 + 0.5 * np.sin(t * 1.5 + i)); cv2.circle(cv, (int(x), int(y)), max(2, int(rad)), tuple(float(v) for v in c), -1, cv2.LINE_AA)
    return blend(img, np.clip(cv_blur(cv, 1.5 * ctx.k), 0, 1.5), None, p["mode"], p["opacity"] / 100.0)

reg("bokeh", PT, "Bokeh parallax", [I("count", "Amount", 30, 3, 150), F("size", "Size", 22, 4, 100), F("speed", "Speed", 1.0, 0, 10), C("color", "Color 1", "#ffd27a"), C("color2", "Color 2", "#8fd3ff"), MODE("screen"), OPAC(100), SEED()], fx_bokeh, "Soft glowing circles drifting at different speeds, so near ones move more than far ones.", "lights defocus circles depth")

ID = "bokeh"

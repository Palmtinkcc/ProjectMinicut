"""plasmawipe: Plasma wipe. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_plasmawipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = norm_coords(h, w); t = ctx.lt * p["speed"]; k = 12.0 / max(1.0, p["scale"] / 20.0)
    v = (np.sin(x * k + t) + np.sin(y * k * 0.9 - t * 1.3) + np.sin((x + y) * k * 0.7 + t * 0.7) + np.sin(np.sqrt(x * x + y * y) * k * 1.3 - t)) / 8 + 0.5; f = v * 0.5 + (coords(h, w)[0] / w) * 0.5; th = pr * 1.2 - 0.1
    m = (f > th).astype(np.float32); e = np.clip(1 - np.abs(f - th) / 0.06, 0, 1); out = _am(img, m); return blend(out, ramp(0.5 + 0.5 * np.sin(v * 20 + t), [(0, p["c1"]), (1, p["c2"])]), e, "add", 1.0)

reg("plasmawipe", WP, "Plasma wipe", WIPE(40) + [F("scale", "Pattern size", 30, 3, 100), F("speed", "Speed", 1.5, 0, 10), C("c1", "Color 1", "#ff2bd6"), C("c2", "Color 2", "#27e1ff")], fx_plasmawipe, "A bubbling plasma front eats the picture, glowing at its edge.", "energy transition")

ID = "plasmawipe"

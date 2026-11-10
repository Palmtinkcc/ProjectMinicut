"""psykostripes: Psykostripes. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_psykostripes(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); t = ctx.lt * p["speed"]; a = np.deg2rad(p["angle"]); wv = np.sin(x * 6 + t) * 0.15 * p["wave"] / 50.0 + np.sin(y * 9 - t * 1.3) * 0.1 * p["wave"] / 50.0
    u = (x * np.cos(a) + y * np.sin(a) + wv) * (60.0 / max(3.0, p["size"])); col = hsv_bgr(u * 0.5 + t * 0.2 + p["hue"] / 360.0, 0.9, 1.0); m = 0.5 + 0.5 * np.sin(u * np.pi * 2); return blend(img, col, m * 0.0 + 1.0, p["mode"], p["opacity"] / 100.0)

reg("psykostripes", IK, "Psykostripes", [F("size", "Stripe width", 25, 3, 150), F("angle", "Angle", 20, -180, 180), F("wave", "Waviness", 60, 0, 100), F("hue", "Hue", 0, 0, 360), F("speed", "Speed", 1.0, 0, 8), MODE("over"), OPAC(45)], fx_psykostripes, "Wavy rainbow stripes that flow over the picture.", "psychedelic rainbow lines")

ID = "psykostripes"

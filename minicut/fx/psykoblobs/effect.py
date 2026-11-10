"""psykoblobs: Psykoblobs. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_psykoblobs(img, p, ctx):
    h, w = img.shape[:2]; t = ctx.lt * p["speed"]; f = fbm(h, w, S(ctx, p["scale"]) * 3, int(p["seed"]), t * 0.5, 3); band = (f * p["bands"] + t * 0.3) % 1.0; col = hsv_bgr(band * 0.9 + p["hue"] / 360.0, 0.85, 1.0); m = sm(np.abs(np.sin(f * np.pi * p["bands"])), 0.0, 0.5) * 0 + (0.5 + 0.5 * np.sin(f * 9 + t))
    d = (f - 0.5) * 40 * ctx.k * p["warp"] / 100.0; base = displace(img, d, d * 0.7); return blend(base, col, np.clip(m, 0, 1), p["mode"], p["opacity"] / 100.0)

reg("psykoblobs", IK, "Psykoblobs", [F("scale", "Blob size", 40, 5, 200), I("bands", "Color bands", 3, 1, 12), F("hue", "Hue", 0, 0, 360), F("warp", "Warp the picture", 40, 0, 100), F("speed", "Speed", 0.8, 0, 8), MODE("over"), OPAC(55), SEED()], fx_psykoblobs, "Psychedelic color blobs that ooze over and bend the picture.", "psychedelic trippy lava")

ID = "psykoblobs"

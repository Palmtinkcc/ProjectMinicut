"""turbulence: Turbulence. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_turbulence(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["scale"]) * 4; t = ctx.lt * p["speed"]; f = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for o in range(5): n = noise(h, w, s / 2 ** o, int(p["seed"]) + o * 13, t * (1 + o * 0.3)); f += amp * np.abs(n - 0.5) * 2; tot += amp; amp *= 0.55
    f = np.clip(1 - f / tot * 1.6, 0, 1) ** (1 + p["sharp"] / 30.0); y = coords(h, w)[1] / h; f = f * (1 - y * p["fade"] / 100.0 * 0.8)
    return blend(img, ramp(f, [(0, p["c1"]), (0.5, p["c2"]), (1, p["c3"])]), np.clip(f * 1.4, 0, 1), p["mode"], p["opacity"] / 100.0)

reg("turbulence", PR, "Turbulence", [F("scale", "Scale", 40, 5, 200), F("speed", "Speed", 0.6, 0, 10), F("sharp", "Sharpness", 40, 0, 100), F("fade", "Fade to the bottom", 30, 0, 100), C("c1", "Edge", "#3a0000"), C("c2", "Middle", "#ff6a00"), C("c3", "Core", "#fff3b0"), MODE("screen"), OPAC(100), SEED()], fx_turbulence, "Swirling fire-like turbulence.", "fire smoke plasma")

ID = "turbulence"

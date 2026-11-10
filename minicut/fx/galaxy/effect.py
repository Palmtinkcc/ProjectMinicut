"""galaxy: Galaxy. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_galaxy(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]) * 6; arms = int(p["arms"]); rad = r.random(n) ** 0.7; arm = r.integers(0, arms, n); ang = rad * p["twist"] * 0.2 + arm * 2 * np.pi / arms + r.normal(0, 0.18, n) * (1 - rad * 0.5) + ctx.lt * p["speed"] * 0.3 / (0.3 + rad)
    R = min(w, h) * 0.45 * p["size"] / 50.0; x = w * p["x"] / 100.0 + np.cos(ang) * rad * R * 1.0; y = h * p["y"] / 100.0 + np.sin(ang) * rad * R * 0.55; cv = np.zeros((h, w, 3), np.float32); c0, c1 = bgr(p["core"]), bgr(p["color"])
    ok = (x >= 0) & (x < w) & (y >= 0) & (y < h); xi, yi = x[ok].astype(int), y[ok].astype(int); col = c0[None] * (1 - rad[ok, None]) + c1[None] * rad[ok, None]; np.add.at(cv, (yi, xi), col * (1.2 - rad[ok, None] * 0.6) * 0.6)
    core = disc(h, w, w * p["x"] / 100.0, h * p["y"] / 100.0, R * 0.12, R * 0.25)[..., None] * c0 * 0.9; cv = glow_of(cv, 1.2 * ctx.k) * 1.5 + glow_of(cv, 6 * ctx.k) * 1.5 + core; return blend(img, np.clip(cv, 0, 1.5), None, p["mode"], p["opacity"] / 100.0)

reg("galaxy", PT, "Galaxy", [I("count", "Stars", 600, 50, 4000), I("arms", "Arms", 3, 1, 8), F("twist", "Twist", 40, 0, 100), F("size", "Size", 60, 10, 150), F("speed", "Spin", 1.0, -10, 10), F("x", "Center X", 50, 0, 100), F("y", "Center Y", 50, 0, 100), C("core", "Core", "#fff0c0"), C("color", "Arms", "#6fa8ff"), MODE("add"), OPAC(100), SEED()], fx_galaxy, "A spiral galaxy of stars that slowly turns.", "spiral stars space")

ID = "galaxy"

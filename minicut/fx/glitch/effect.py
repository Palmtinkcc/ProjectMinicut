"""glitch: Glitch. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import fx_rgb_split, register

def fx_glitch(img, p, ctx):
    amt = p["amount"] / 100
    if amt <= 0: return img
    h, w = img.shape[:2]; rng = np.random.default_rng(int(ctx.lt * 12) * 7919 + int(p["seed"])); out = img.copy()
    for _ in range(int(2 + amt * 14)):
        y0 = int(rng.integers(0, h)); hh = int(rng.integers(max(1, h // 80), max(2, h // 8))); sh = int(rng.normal(0, w * 0.08 * amt))
        if hh > 0 and sh: out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], sh, axis=1)
    return fx_rgb_split(out, {"amount": 6 * amt, "angle": 0}, ctx)

register("glitch", "Distort", "Glitch",
         [("amount", "Amount", "float", 40.0, 0.0, 100.0),
          ("seed",   "Seed",   "int",   1,    0,   999)],
         fx_glitch)

ID = "glitch"

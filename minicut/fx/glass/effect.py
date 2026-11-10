"""glass: Glass surface. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_glass(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); st = p["strength"] * ctx.k
    if p["kind"] == "reeded": ph = (x / s) % 1.0; dx = (ph - 0.5) * 2 * st * 1.5; dy = 0 * x; nrm = (ph - 0.5) * 2
    elif p["kind"] == "frosted": dx = (noise(h, w, 2, int(p["seed"]), 0) - 0.5) * 2 * st; dy = (noise(h, w, 2, int(p["seed"]) + 1, 0) - 0.5) * 2 * st; nrm = dx / max(st, 1e-3)
    else: n1 = fbm(h, w, s * 2, int(p["seed"]), ctx.lt * p["speed"], 3); gy, gx = np.gradient(cv2.GaussianBlur(n1, (0, 0), 1.5)); dx = gx * st * 40; dy = gy * st * 40; nrm = gx / (np.abs(gx).max() + 1e-6)
    out = displace(img, dx, dy)
    if p["frost"] > 0: out = blend(out, f3(blur_bgra(out, p["frost"] * ctx.k * 0.15)), None, "replace", 0.8)
    sh = np.clip(nrm, 0, 1) ** 2 * (p["shine"] / 100.0) * 0.6; f = f3(out) + sh[..., None]; return pack(np.clip(f, 0, 1), like=out)

reg("glass", WG, "Glass surface", [CH("kind", "Glass", "reeded", [("reeded", "Ribbed (reeded)"), ("frosted", "Frosted"), ("bumpy", "Bumpy")]), F("size", "Rib / bump size", 24, 4, 150), F("strength", "Refraction", 8, 0, 100), F("frost", "Frost blur", 8, 0, 100), F("shine", "Shine", 40, 0, 100), F("speed", "Speed", 0.2, 0, 4), SEED()], fx_glass, "The picture seen through ribbed, frosted or bumpy glass.", "reeded refraction shower window")

ID = "glass"

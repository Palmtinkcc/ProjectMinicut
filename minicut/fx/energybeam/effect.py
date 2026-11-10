"""energybeam: Energy beam. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_energybeam(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); a = (w * p["x1"] / 100.0, h * p["y1"] / 100.0); b = (w * p["x2"] / 100.0, h * p["y2"] / 100.0); core = np.zeros((h, w), np.float32); th = max(1, int(S(ctx, p["thick"])))
    for k in range(int(p["bolts"])):
        pts = _bolt(r, a, b, 6, p["wobble"] / 100.0 * (0.6 + 0.6 * k)); cv2.polylines(core, [pts.astype(np.int32)], False, 1.0 if k == 0 else 0.6, th if k == 0 else max(1, th // 2), cv2.LINE_AA)
    gl = glow_of(core, 3 * ctx.k * p["glow"] / 30.0) * 2.5 + glow_of(core, 10 * ctx.k * p["glow"] / 30.0) * 1.5; col = bgr(p["color"]); lay = np.clip(gl[..., None] * col + core[..., None] * 0.9, 0, 1.5)
    return blend(img, lay, None, "add", 1.0)

reg("energybeam", PR, "Energy beam", [F("x1", "Start X", 10, 0, 100), F("y1", "Start Y", 50, 0, 100), F("x2", "End X", 90, 0, 100), F("y2", "End Y", 50, 0, 100), I("bolts", "Bolts", 3, 1, 8), F("thick", "Thickness", 2, 1, 12), F("wobble", "Wobble", 45, 0, 100), F("glow", "Glow", 40, 1, 100), F("rate", "Changes / s", 18, 1, 60), C("color", "Color", "#6ec6ff"), SEED()], fx_energybeam, "Crackling electric beams between two points.", "lightning laser electric")

ID = "energybeam"

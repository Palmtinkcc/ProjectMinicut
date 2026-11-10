"""streakstrips: Streak strips. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_streakstrips(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"]) + int(ctx.lt * p["rate"])); n = int(p["strips"]); cuts = np.linspace(0, h, n + 1).astype(int); out = img.copy()
    for i in range(n):
        y0, y1 = cuts[i], cuts[i + 1]; L = int(max(0, r.uniform(0.2, 1.0) * p["length"] * ctx.k))
        if L > 1 and r.random() < p["density"] / 100.0: out[y0:y1] = unpm4(cv2.blur(pm4(img[y0:y1]), (L, 1), borderType=cv2.BORDER_REPLICATE))
    return out

reg("streakstrips", BL, "Streak strips", [I("strips", "Strips", 18, 3, 80), F("length", "Streak length", 90, 2, 500), F("density", "How many are blurred", 70, 0, 100), F("rate", "Changes / s", 6, 0, 30), SEED()], fx_streakstrips, "Horizontal strips, each blurred by a different amount, like speed lines.", "speed lines horizontal")

ID = "streakstrips"

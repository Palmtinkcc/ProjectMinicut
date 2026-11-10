"""part3d: 3D particles. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_part3d(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); P = r.uniform(-1, 1, (n, 3)); t = ctx.lt * p["speed"] * 0.25; z = (P[:, 2] * 0.5 + 0.5 - t) % 1.0; zz = 0.15 + z * 2.0
    sx = w / 2 + P[:, 0] / zz * w * 0.45 * 0.5; sy = h / 2 + P[:, 1] / zz * h * 0.45 * 0.5; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"])
    for i in range(n):
        f = np.clip(1 - z[i], 0, 1); rad = S(ctx, p["size"]) * (0.3 + 1.2 * f); x, y = int(sx[i]), int(sy[i])
        if -rad < x < w + rad and -rad < y < h + rad: cv2.circle(cv, (x, y), max(1, int(rad)), tuple(float(c * (0.2 + 0.8 * f)) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)

reg("part3d", PT, "3D particles", PTP(), fx_part3d, "Particles in 3D space that fly towards you.", "space fly through warp stars")

ID = "part3d"

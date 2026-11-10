"""card: Card flip. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_card(img, p, ctx):
    h, w = img.shape[:2]; Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); rh_, rw_ = ref_size(h, w); s = 0.5 * rw_ / rh_; ti = ref_crop(img)
    V = np.array([[-s, -0.5, 0], [s, -0.5, 0], [s, 0.5, 0], [-s, 0.5, 0]], np.float32); P2, P3 = _project(V, Rm, h, w, p["size"] / 100.0 / (w / h) * 1.0 * (w / h), p["persp"] / 100.0)
    out = _quad(ti, P2, (h, w)); nrm = np.cross(P3[1] - P3[0], P3[2] - P3[1])
    if nrm[2] > 0 and not p["both"]: out[..., 3] = 0
    return _shade(out, np.broadcast_to(-np.abs(nrm) / (np.linalg.norm(nrm) + 1e-6), (h, w, 3)), p["light"] * 0.5)

reg("card", OB, "Card flip", OBP([F("persp", "Perspective", 60, 0, 100), B("both", "Show the back too", True)]), fx_card, "The picture as a flat card that turns and tilts in 3D space.", "flip rotate perspective plane")

ID = "card"

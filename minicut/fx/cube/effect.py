"""cube: Cube. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_cube(img, p, ctx):
    h, w = img.shape[:2]; ti = ref_crop(img); Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); s = 0.5
    V = np.array([[-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s], [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]], np.float32); faces = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
    P2, P3 = _project(V, Rm, h, w, p["size"] / 100.0, p["persp"] / 100.0); out = np.zeros_like(img)
    for fi in sorted(range(6), key=lambda i: np.mean(P3[list(faces[i])][:, 2])):
        q = faces[fi]; nrm = np.cross(P3[q[1]] - P3[q[0]], P3[q[2]] - P3[q[1]])
        if nrm[2] > 0: continue
        r = _face_roi(ti, P2[list(q)], (h, w))
        if r is not None: _paste(out, r[0], r[1], r[2], _shade_k(nrm, p["light"]))
    return out

reg("cube", OB, "Cube", OBP([F("persp", "Perspective", 60, 0, 100)]), fx_cube, "The picture on all six sides of a turning cube.", "box dice")

ID = "cube"

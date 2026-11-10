"""Particle effects (drawn over the picture) and simple 3D shapes."""
from .cpu_kit import *

PT = "Particle"
def PTP(extra=()): return list(extra) + [I("count", "Amount", 60, 1, 400), F("size", "Size", 4, 0.5, 40), F("speed", "Speed", 1.0, 0, 10), C("color", "Color", "#ffffff"), MODE("add"), OPAC(100), SEED()]
def _fin(img, canvas, glow, p, ctx):
    lay = np.clip(canvas + glow_of(canvas, glow * ctx.k) * 1.6, 0, 1.5)
    if lay.ndim == 2: lay = lay[..., None] * bgr(p["color"])
    return blend(img, lay, None, p["mode"], p["opacity"] / 100.0)
def _star(cv, x, y, r, a, col):
    for ang in (0, 90):
        d = np.deg2rad(ang); dx, dy = np.cos(d) * r, np.sin(d) * r; cv2.line(cv, (int(x - dx), int(y - dy)), (int(x + dx), int(y + dy)), (a * col[0], a * col[1], a * col[2]), 1, cv2.LINE_AA)
    r2 = r * 0.5
    for ang in (45, 135):
        d = np.deg2rad(ang); dx, dy = np.cos(d) * r2, np.sin(d) * r2; cv2.line(cv, (int(x - dx), int(y - dy)), (int(x + dx), int(y + dy)), (a * col[0] * 0.6, a * col[1] * 0.6, a * col[2] * 0.6), 1, cv2.LINE_AA)


def cv_blur(a, s): return glow_of(a, s)


# ------------------------------------------------------------------ 3D object: the media as the skin of a simple 3D shape
OB = "3D object"
def _rot(ax, ay, az):
    cx, sx, cy, sy, cz, sz = np.cos(ax), np.sin(ax), np.cos(ay), np.sin(ay), np.cos(az), np.sin(az)
    return np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
def OBP(extra=()): return list(extra) + [F("size", "Size", 70, 10, 200), F("rx", "Tilt X", 15, -180, 180), F("ry", "Turn Y", 25, -180, 180), F("rz", "Roll", 0, -180, 180), F("spin", "Spin (deg / s)", 30, -360, 360), F("light", "Shading", 50, 0, 100)]
def _shade(rgba, n, light):
    k = 1 - light / 100.0 * (1 - np.clip(0.35 + 0.65 * (n @ np.array([-0.4, -0.5, 0.75])), 0, 1)); out = rgba.copy(); out[..., :3] = np.clip(rgba[..., :3].astype(np.float32) * k[..., None], 0, 255).astype(np.uint8); return out


def _quad(img, corners, out_size):
    h, w = img.shape[:2]; src = np.float32([[0, 0], [w, 0], [w, h], [0, h]]); M = cv2.getPerspectiveTransform(src, np.float32(corners)); return cv2.warpPerspective(img, M, (out_size[1], out_size[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _project(pts, Rm, h, w, size, persp):
    p3 = pts @ Rm.T; zc = 3.2 - p3[:, 2] * persp; rh = ref_size(h, w)[0]; sx = w / 2 + p3[:, 0] / zc * rh * size * 2.2; sy = h / 2 + p3[:, 1] / zc * rh * size * 2.2; return np.stack([sx, sy], 1), p3


def _face_roi(ti, corners, size):
    """Warp texture `ti` onto the quad `corners`, but only inside the quad's bounding box (Patch 38: the old code warped,
    shaded and blended the whole frame once per face). Returns (x0, y0, rgba_patch) or None when nothing is visible."""
    h, w = size; c = np.float32(corners)
    x0 = max(0, int(np.floor(c[:, 0].min())) - 1); y0 = max(0, int(np.floor(c[:, 1].min())) - 1)
    x1 = min(w, int(np.ceil(c[:, 0].max())) + 2); y1 = min(h, int(np.ceil(c[:, 1].max())) + 2)
    if x1 <= x0 or y1 <= y0: return None
    th_, tw_ = ti.shape[:2]; src = np.float32([[0, 0], [tw_, 0], [tw_, th_], [0, th_]])
    M = cv2.getPerspectiveTransform(src, c - np.float32([x0, y0]))
    return x0, y0, cv2.warpPerspective(ti, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _shade_k(nrm, light):
    """One brightness factor per flat face (the normal is the same on the whole face)."""
    n = -nrm / (np.linalg.norm(nrm) + 1e-6)
    return float(1 - light / 100.0 * (1 - np.clip(0.35 + 0.65 * float(n @ np.array([-0.4, -0.5, 0.75])), 0, 1)))


def _paste(out, x0, y0, patch, k):
    """Shade the patch by k and put it over `out` (same result as alpha-over; solid pixels are copied, only edges are blended)."""
    ph, pw = patch.shape[:2]; roi = out[y0:y0 + ph, x0:x0 + pw]; a = patch[..., 3]
    if k < 0.999: patch[..., :3] = cv2.convertScaleAbs(patch[..., :3], alpha=k)
    solid = a >= 250; np.copyto(roi, patch, where=solid[..., None])
    edge = (a > 0) & ~solid
    if edge.any():
        af = (a[edge].astype(np.float32) / 255)[:, None]; src = patch[edge].astype(np.float32); dst = roi[edge].astype(np.float32)
        res = src * af + dst * (1 - af); res[:, 3] = np.maximum(dst[:, 3], src[:, 3]); roi[edge] = res.astype(np.uint8)


def _fx_cube_ref(img, p, ctx):          # the original (slow) version, kept so tests can compare against it
    h, w = img.shape[:2]; ti = ref_crop(img); Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); s = 0.5
    V = np.array([[-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s], [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]], np.float32); faces = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
    P2, P3 = _project(V, Rm, h, w, p["size"] / 100.0, p["persp"] / 100.0); out = np.zeros_like(img); order = sorted(range(6), key=lambda i: -np.mean(P3[list(faces[i])][:, 2]) * -1)
    for fi in sorted(range(6), key=lambda i: np.mean(P3[list(faces[i])][:, 2])):
        q = faces[fi]; nrm = np.cross(P3[q[1]] - P3[q[0]], P3[q[2]] - P3[q[1]])
        if nrm[2] > 0: continue
        face = _quad(ti, P2[list(q)], (h, w)); face = _shade(face, np.broadcast_to(-nrm / (np.linalg.norm(nrm) + 1e-6), (h, w, 3)), p["light"]); a = face[..., 3:4].astype(np.float32) / 255; out = (face * a + out * (1 - a)).astype(np.uint8); out[..., 3] = np.maximum(out[..., 3], face[..., 3])
    return out


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

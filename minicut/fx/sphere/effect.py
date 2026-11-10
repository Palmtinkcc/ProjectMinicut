"""sphere: Sphere. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_sphere(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); R = p["size"] / 100.0 * 0.5; X, Y = x / R, y / R; r2 = X * X + Y * Y; ins = r2 < 1; Z = np.sqrt(np.clip(1 - r2, 0, 1)); N = np.stack([X, Y, -Z], -1)
    Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); M = N @ Rm; lon = np.arctan2(M[..., 0], -M[..., 2]); lat = np.arcsin(np.clip(M[..., 1], -1, 1))
    ti = ref_crop(img); th_, tw_ = ti.shape[:2]; tex = remap(ti, (lon / (2 * np.pi) + 0.5) * tw_, (lat / np.pi + 0.5) * th_, cv2.BORDER_WRAP); out = _shade(tex, N, p["light"]); aa = np.clip((1 - np.sqrt(r2)) * R * h / 1.5, 0, 1); out[..., 3] = (out[..., 3] * aa).astype(np.uint8); return out

reg("sphere", OB, "Sphere", OBP(), fx_sphere, "The picture wrapped around a turning ball.", "globe ball planet")

ID = "sphere"

"""cylinder: Cylinder. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_cylinder(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); R = p["size"] / 100.0 * 0.5; X = x / R; ins = np.abs(X) < 1; ang = np.arcsin(np.clip(X, -1, 1)) + np.deg2rad(p["ry"] + ctx.lt * p["spin"])
    u = (ang / (2 * np.pi)) % 1.0; ti = ref_crop(img); th_, tw_ = ti.shape[:2]; yy = (y / (R * 2.6) + 0.5) * th_; tex = remap(ti, u * tw_, yy, cv2.BORDER_REFLECT); N = np.stack([X, np.zeros_like(X), -np.sqrt(np.clip(1 - X * X, 0, 1))], -1); out = _shade(tex, N, p["light"])
    a = ins.astype(np.float32) * (np.abs(y) < R * 1.3); out[..., 3] = (out[..., 3] * cv2.GaussianBlur(a, (0, 0), 0.8)).astype(np.uint8); return out

reg("cylinder", OB, "Cylinder", OBP(), fx_cylinder, "The picture wrapped around a turning can.", "tube roll")

ID = "cylinder"

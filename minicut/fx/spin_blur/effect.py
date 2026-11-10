"""spin_blur: Spin Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, _premul, _unpremul, gpu_spin_blur, register

def fx_spin_blur(img, p, ctx):
    """Rotational motion blur around a center point."""
    angle_deg = p["angle"]
    if abs(angle_deg) < 0.1: return img
    cx    = p.get("cx", 50.0) / 100.0
    cy    = p.get("cy", 50.0) / 100.0
    steps = 5 if ctx.fast else 12
    if _GPU_FX:
        try:
            return gpu_spin_blur(img, math.radians(angle_deg), cx, cy, steps)
        except (GpuFxUnavailable, Exception):
            pass
    h, w  = img.shape[:2]; ocx, ocy = w * cx, h * cy
    pm, a = _premul(img)
    acc   = np.zeros_like(pm); acca = np.zeros_like(a)
    for i in range(steps):
        ang = math.radians(angle_deg * i / max(1, steps - 1))
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        M = np.array([[cos_a, -sin_a, ocx - ocx * cos_a + ocy * sin_a],
                      [sin_a,  cos_a, ocy - ocx * sin_a - ocy * cos_a + ocy]], np.float32)
        acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)

register("spin_blur", "Blur", "Spin Blur",
         [("angle", "Angle",    "float", 15.0, -180.0, 180.0),
          ("cx",    "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",    "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_spin_blur,
         help="Rotational motion blur around a center point.")

ID = "spin_blur"

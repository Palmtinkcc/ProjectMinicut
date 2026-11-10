"""zoom_blur: Zoom Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, _premul, _unpremul, gpu_zoom_blur, register

def fx_zoom_blur(img, p, ctx):
    """Radial zoom blur from a center point — like AM's Zoom Blur."""
    amt   = p["amount"] / 100.0
    if amt <= 0.001: return img
    cx    = p.get("cx", 50.0) / 100.0
    cy    = p.get("cy", 50.0) / 100.0
    steps = 5 if ctx.fast else 12
    if _GPU_FX:
        try:
            return gpu_zoom_blur(img, amt, cx, cy, steps)
        except (GpuFxUnavailable, Exception):
            pass
    h, w  = img.shape[:2]; ocx, ocy = w * cx, h * cy
    pm, a = _premul(img)
    acc   = np.zeros_like(pm); acca = np.zeros_like(a)
    for i in range(steps):
        s = 1.0 + amt * 0.5 * i / max(1, steps - 1)
        M = np.array([[s, 0, ocx * (1 - s)], [0, s, ocy * (1 - s)]], np.float32)
        acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)

register("zoom_blur", "Blur", "Zoom Blur",
         [("amount", "Amount",   "float", 40.0, 0.0, 100.0),
          ("cx",     "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",     "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_zoom_blur,
         help="Radial zoom blur — great for speed lines or warp effects.")

ID = "zoom_blur"

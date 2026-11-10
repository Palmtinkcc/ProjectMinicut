"""radial_blur: Radial Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _premul, _unpremul, register

def fx_radial_blur(img, p, ctx):
    amt = p["amount"] / 100
    if amt <= 0.002: return img
    mode = p.get("mode", "zoom")   # zoom | spin
    h, w = img.shape[:2]; cx, cy = w * p["cx"] / 100, h * p["cy"] / 100
    steps = 6 if ctx.fast else 14
    pm, a = _premul(img); acc = np.zeros_like(pm); acca = np.zeros_like(a)
    if mode == "spin":
        max_angle = amt * 0.3   # max rotation in radians
        for i in range(steps):
            ang = max_angle * i / max(1, steps - 1)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            M = np.array([[cos_a, -sin_a, cx - cx * cos_a + cy * sin_a],
                          [sin_a,  cos_a, cy - cx * sin_a - cy * cos_a + cy]], np.float32)
            acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    else:  # zoom (original)
        zoom_amt = amt * 0.25
        for i in range(steps):
            s = 1 + zoom_amt * i / max(1, steps - 1)
            M = np.array([[s, 0, cx - cx * s], [0, s, cy - cy * s]], np.float32)
            acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)

register("radial_blur", "Blur", "Radial Blur",
         [("amount", "Amount",   "float", 40.0, 0.0, 100.0),
          ("mode",   "Mode",     "choice", "zoom", [("zoom", "Zoom"), ("spin", "Spin")], None),
          ("cx",     "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",     "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_radial_blur,
         help="Zoom or spin radial blur from a movable center point.")

ID = "radial_blur"

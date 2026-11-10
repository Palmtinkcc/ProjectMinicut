"""hueshift: Hue shift. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_hueshift(img, p, ctx):
    hu = p["hue"] + p["cycle"] * ctx.lt
    if abs(hu % 360) < 0.01 and p["saturation"] == 0: return img
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + hu / 2.0) % 180; hsv[..., 1] = np.clip(hsv[..., 1] * (1 + p["saturation"] / 100.0), 0, 255)
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR); return out

reg("hueshift", C1, "Hue shift", [F("hue", "Hue shift", 90, -180, 180), F("cycle", "Cycle (deg / s)", 0, -360, 360), F("saturation", "Saturation", 0, -100, 100)], fx_hueshift, "Turns all the colors around the color wheel; it can also keep turning by itself.", "rainbow rotate cycle")

ID = "hueshift"

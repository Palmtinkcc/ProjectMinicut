"""hue_shift: Hue Shift. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_hue_shift(img, p, ctx):
    shift = p["shift"]
    if shift == 0: return img
    rgb = np.ascontiguousarray(img[..., :3])
    hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + shift / 2.0) % 180
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR); return out

register("hue_shift", "Color", "Hue Shift",
         [("shift", "Hue shift", "float", 0.0, -180.0, 180.0)],
         fx_hue_shift,
         help="Shift all hues by a fixed amount. Keyframe it to cycle through the rainbow.")

ID = "hue_shift"

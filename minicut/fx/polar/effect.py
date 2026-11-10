"""polar: Polar coordinates. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_polar(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w)
    if p["dir"] == "to_polar": dx, dy, r, a, cx, cy = polar(h, w, p); return remap(img, ((a / (2 * np.pi) + 0.5) * w) % w, np.clip(r / (np.hypot(w, h) / 2) * h, 0, h - 1), cv2.BORDER_REFLECT)
    cx, cy = w * p["cx"] / 100.0, h * p["cy"] / 100.0; ang = x / w * 2 * np.pi - np.pi; rs = y / h * (np.hypot(w, h) / 2); return remap(img, cx + rs * np.cos(ang) * 0 + (cx + rs * np.cos(ang)) * 0 + (cx + rs * np.cos(ang)) - cx * 0, cy + rs * np.sin(ang), cv2.BORDER_REFLECT)

reg("polar", DW, "Polar coordinates", [CH("dir", "Convert", "to_polar", [("to_polar", "Picture to circle"), ("from_polar", "Circle to picture")])] + CEN(), fx_polar, "Wraps the picture into a circle (a tiny planet), or unwraps it.", "tiny planet circle")

ID = "polar"

"""squeeze: Squeeze. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_squeeze(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; k = p["amount"] / 100.0
    if p["axis"] == "x": f = 1 + k * (1 - np.abs(y - cy) / cy) ** 2; return remap(img, cx + (x - cx) * f, y, cv2.BORDER_CONSTANT)
    f = 1 + k * (1 - np.abs(x - cx) / cx) ** 2; return remap(img, x, cy + (y - cy) * f, cv2.BORDER_CONSTANT)

reg("squeeze", DW, "Squeeze", [F("amount", "Amount", 60, -90, 300), CH("axis", "Squeeze the", "x", [("x", "Width (waist)"), ("y", "Height")])], fx_squeeze, "Squeezes the middle of the picture like a waist or an hourglass.", "pinch waist narrow")

ID = "squeeze"

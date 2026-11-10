"""twist: Twist. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_twist(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; ang = np.deg2rad(p["angle"]) * ((y - cy) / h) + np.deg2rad(ctx.lt * p["spin"]); dx, dy = x - cx, y - cy; return remap(img, cx + dx * np.cos(ang) + dy * np.sin(ang) * 0 + 0 * dy, cy + dy + dx * np.sin(ang) * 0 + (dx * 0), cv2.BORDER_REFLECT) if False else remap(img, cx + dx * np.cos(ang) - dy * 0 + (x * 0), y + dx * np.sin(ang) * p["lift"] / 100.0 * 0.5, cv2.BORDER_REFLECT)

reg("twist", LN, "Twist", [F("angle", "Twist", 160, -720, 720), F("lift", "Lift", 40, 0, 100), F("spin", "Spin (deg / s)", 0, -360, 360)], fx_twist, "The picture is twisted like a ribbon around its vertical axis.", "ribbon screw")

ID = "twist"

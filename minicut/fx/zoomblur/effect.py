"""zoomblur: Zoom blur. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_zoomblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; return _avg(img, [xform(h, w, 0, 0, 0, 1 + p["amount"] / 100.0 * (i / (n - 1) - 0.5 * (0 if p["onesided"] else 1)), cx, cy) for i in range(n)], w, h)

reg("zoomblur", BL, "Zoom blur", [F("amount", "Amount", 18, 0, 100), I("steps", "Quality", 16, 4, 40), B("onesided", "One direction", False)] + CEN(), fx_zoomblur, "Streaks that rush toward or away from a center point.", "radial speed")

ID = "zoomblur"

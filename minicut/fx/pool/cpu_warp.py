"""Distortion & warp, Lens, Water & glass, and more blurs."""
from .cpu_kit import *
from ...render.effects import _premul, _unpremul, blur_bgra

DW = "Distortion & warp"; LN = "Lens"; WG = "Water & glass"; BL = "Blur"
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def CEN(): return [F("cx", "Center X", 50, -50, 150), F("cy", "Center Y", 50, -50, 150)]
def polar(h, w, p):
    """px, py (picture pixels relative to the center), r, angle, and the center."""
    x, y = coords(h, w); cx, cy = w * p.get("cx", 50) / 100.0, h * p.get("cy", 50) / 100.0; dx, dy = x - cx, y - cy; return dx, dy, np.sqrt(dx * dx + dy * dy), np.arctan2(dy, dx), cx, cy
def sample_polar(img, cx, cy, rs, ang, border=cv2.BORDER_REFLECT): return remap(img, cx + rs * np.cos(ang), cy + rs * np.sin(ang), border)


# ------------------------------------------------------------------ distortion & warp


# ------------------------------------------------------------------ lens


def _barrel(img, p, ctx, k, scale=1.0, cx=0.5, cy=0.5, chan=None):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x - w * cx) / (h / 2); ny = (y - h * cy) / (h / 2); r2 = nx * nx + ny * ny; f = (1 + k * r2 + p.get("k2", 0) / 100.0 * r2 * r2) * scale
    return (nx * f * (h / 2) + w * cx), (ny * f * (h / 2) + h * cy)


# ------------------------------------------------------------------ water & glass


# ------------------------------------------------------------------ blur (more)
def _avg(img, mats, w, h):
    acc = np.zeros(img.shape, np.float32); pm = pm4(img)
    for M in mats: acc += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return unpm4(acc / len(mats))


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

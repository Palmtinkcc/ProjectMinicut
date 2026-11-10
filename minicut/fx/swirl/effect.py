"""swirl: Swirl. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_swirl(img, p, ctx):
    amount = p["amount"]
    if abs(amount) < 0.1: return img
    radius = p.get("radius", 50.0) / 100.0
    h, w   = img.shape[:2]; cx, cy = w / 2, h / 2
    max_r  = min(w, h) * radius / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx; dy = yy - cy; r = np.sqrt(dx**2 + dy**2)
    angle = amount * np.maximum(0, 1 - r / max(1, max_r))
    cos_a = np.cos(angle); sin_a = np.sin(angle)
    src_x = cx + cos_a * dx - sin_a * dy
    src_y = cy + sin_a * dx + cos_a * dy
    return cv2.remap(img, src_x, src_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

register("swirl", "Distort", "Swirl",
         [("amount", "Angle",  "float", 1.5, -10.0, 10.0),
          ("radius", "Radius", "float", 50.0, 1.0, 100.0)],
         fx_swirl,
         help="Swirl/twirl distortion around the layer center.")


# ------------------------------------------------------------------ GPU version
from ..pool.cpu_warp import *

def fx_swirl(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["radius"] / 100.0; t = np.clip(1 - r / R, 0, 1); ang = np.deg2rad(p["angle"] + ctx.lt * p["spin"]) * t * t * (3 - 2 * t); return sample_polar(img, cx, cy, r, a - ang)

reg("swirl", LN, "Swirl", [F("angle", "Twist", 160, -720, 720), F("radius", "Size", 60, 5, 200), F("spin", "Spin (deg / s)", 0, -360, 360)] + CEN(), fx_swirl, "Twists a round area of the picture like a whirlpool.", "whirl vortex")

ID = "swirl"

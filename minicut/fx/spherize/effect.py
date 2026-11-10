"""spherize: Spherize. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_spherize(img, p, ctx):
    amount = p["amount"] / 100.0
    if abs(amount) < 0.01: return img
    h, w   = img.shape[:2]; cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - cx) / cx; ny = (yy - cy) / cy
    r2 = nx**2 + ny**2
    inside = r2 < 1.0
    r = np.sqrt(np.where(inside, r2, 1.0))
    factor = np.where(inside, 1.0 - (1.0 - r) * amount, 1.0)
    src_x  = np.clip(cx + nx * factor * cx, 0, w - 1)
    src_y  = np.clip(cy + ny * factor * cy, 0, h - 1)
    return cv2.remap(img, src_x.astype(np.float32), src_y.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

register("spherize", "Distort", "Spherize",
         [("amount", "Amount", "float", 50.0, -100.0, 100.0)],
         fx_spherize,
         help="Wrap the layer around a sphere (positive=bulge, negative=pinch).")

ID = "spherize"

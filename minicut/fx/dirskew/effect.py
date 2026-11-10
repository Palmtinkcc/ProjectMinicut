"""dirskew: Directional skew. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_dirskew(img, p, ctx):
    h, w = img.shape[:2]; a = np.deg2rad(p["angle"]); k = np.tan(np.deg2rad(p["amount"])); x, y = coords(h, w); ux, uy = np.cos(a), np.sin(a); d = (x - w / 2) * (-uy) + (y - h / 2) * ux; return remap(img, x - ux * k * d, y - uy * k * d, cv2.BORDER_CONSTANT)

reg("dirskew", LN, "Directional skew", [F("amount", "Skew", 15, -60, 60), F("angle", "Direction", 0, -180, 180)], fx_dirskew, "Slants the picture in any direction.", "shear slant")

ID = "dirskew"

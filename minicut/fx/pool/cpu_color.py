"""Color and Opacity effects."""
from .cpu_kit import *

C1 = "Color"; C2 = "Opacity"


_BANDS = [("red", "Red", 0.0), ("yellow", "Yellow", 1 / 6), ("green", "Green", 2 / 6), ("cyan", "Cyan", 3 / 6), ("blue", "Blue", 4 / 6), ("magenta", "Magenta", 5 / 6)]


# ------------------------------------------------------------------ opacity
def _alpha_mul(img, m):
    out = img.copy(); out[..., 3] = np.clip(img[..., 3].astype(np.float32) * m, 0, 255).astype(np.uint8); return out


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

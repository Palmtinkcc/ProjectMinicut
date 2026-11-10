"""VHS and old-screen effects."""
from .cpu_kit import *

V = "VHS"
def _under(img, layer, op):
    """Put `layer` (BGRA) behind the picture."""
    return blend(img, f3(layer), layer[..., 3].astype(np.float32) / 255.0, "behind", op)


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

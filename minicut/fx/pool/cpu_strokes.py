"""Strokes & shadows, and Ink & paint & halftone."""
from .cpu_kit import *

SS = "Strokes & shadows"
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def _shadow_under(img, a, col, op):
    return blend(img, np.broadcast_to(bgr(col), a.shape + (3,)), np.clip(a, 0, 1), "behind", op)
def _alpha(img): return img[..., 3].astype(np.float32) * (1 / 255)


# ------------------------------------------------------------------ ink & paint & halftone
IK = "Ink & paint"


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

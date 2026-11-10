"""Repeat, Shake & transform and Move effects."""
from .cpu_kit import *
from ...render.fxpack.kit import _BAND

RP = "Repeat"
def _over(base, lay):
    """Alpha-over of two premultiplied-safe BGRA pictures: lay on top of base."""
    return blend(base, f3(lay), lay[..., 3].astype(np.float32) / 255.0, "over", 1.0) if base[..., 3].max() > 0 else lay
def _comp(copies, h, w):
    """Stack BGRA copies (first = bottom) with alpha-over, premultiplied. Done band by band (the same per-pixel sums, so the same picture, but the
    band stays in the CPU cache) and a copy that is see-through all over a band is skipped there (alpha 0 changes nothing)."""
    out = np.empty((h, w, 4), np.uint8)
    for y0 in range(0, h, _BAND):
        y1 = min(h, y0 + _BAND); acc = np.zeros((y1 - y0, w, 3), np.float32); acc_a = np.zeros((y1 - y0, w), np.float32)
        for c in copies:
            cb = c[y0:y1]
            if not cb[..., 3].any(): continue
            a = cb[..., 3].astype(np.float32) * (1 / 255); acc = f3(cb) * a[..., None] + acc * (1 - a[..., None]); acc_a = a + acc_a * (1 - a)
        out[y0:y1] = pack(acc / np.maximum(acc_a[..., None], 1e-4), acc_a)
    return out
def _small(img, sc): h, w = img.shape[:2]; return cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
def _place(img, M): return affine(img, M)


# ------------------------------------------------------------------ shake & transform
SH = "Shake & transform"
def _tf(img, ctx, tx, ty, rot=0.0, sc_=1.0, cx=0.5, cy=0.5):
    h, w = img.shape[:2]; return affine(img, xform(h, w, tx * ctx.k, ty * ctx.k, rot, sc_, cx, cy))


# ------------------------------------------------------------------ move
MV = "Move"


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

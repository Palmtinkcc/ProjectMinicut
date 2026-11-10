"""Glitch effects (they change by themselves with time; Seed and Changes per second control the randomness)."""
from .cpu_kit import *

G = "Glitch"
def GP(extra=()): return [F("amount", "Amount", 50, 0, 100), F("speed", "Changes / s", 12, 0, 60), SEED()] + list(extra)
def _r(p, ctx): return rng(ctx, p["seed"], p["speed"])
def _rows(r, h, amt, maxh=0.12):
    """Random horizontal bands covering the picture: list of (y0, y1)."""
    out = []; y = 0
    while y < h:
        hh = int(r.integers(max(1, h // 90), max(2, int(h * maxh)) + 1)); out.append((y, min(h, y + hh))); y += hh
    return out


def _sort(img, lo, hi, key, rev, vertical):
    src = np.ascontiguousarray(np.swapaxes(img, 0, 1)) if vertical else img; h, w = src.shape[:2]; f = f3(src); L = lum(f)
    if key == "hue": kv = cv2.cvtColor(np.ascontiguousarray(src[..., :3]), cv2.COLOR_BGR2HSV)[..., 0].astype(np.float32) / 180.0
    elif key == "red": kv = f[..., 2]
    else: kv = L
    sel = (L >= lo) & (L <= hi); start = np.ones((h, w), bool); start[:, 1:] = sel[:, 1:] != sel[:, :-1]; seg = np.cumsum(start.ravel()).astype(np.float64).reshape(h, w)
    k2 = np.where(sel, (1 - kv if rev else kv), np.arange(w, dtype=np.float32)[None, :] / w) * 0.999; order = np.argsort((seg + k2).ravel(), kind="stable")
    out = src.reshape(-1, 4)[order].reshape(h, w, 4); return np.ascontiguousarray(np.swapaxes(out, 0, 1)) if vertical else out


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

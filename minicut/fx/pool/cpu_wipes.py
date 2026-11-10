"""Wipes, breaks and shatter. Progress 0 = the picture is whole, 100 = it is completely gone. Set it by hand, or let it run by itself
(Run by itself = seconds it takes; Start after = a delay; Reverse = the picture appears instead)."""
from .cpu_kit import *

WP = "Wipes & shatter"
def _am(img, m):
    out = img.copy(); out[..., 3] = np.clip(img[..., 3].astype(np.float32) * m, 0, 255).astype(np.uint8); return out
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def _over(base, top):
    a = top[..., 3:4].astype(np.float32) / 255.0; ba = base[..., 3:4].astype(np.float32) / 255.0; oa = a + ba * (1 - a)
    rgb = (top[..., :3] * a + base[..., :3].astype(np.float32) * ba * (1 - a)) / np.maximum(oa, 1e-4); return np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), (oa[..., 0] * 255).astype(np.uint8)])


def _paste(canvas, crop, x0, y0, M):
    """Warp `crop` (which sits at x0, y0 of the picture) with the 2x3 matrix M (picture coordinates) and put it over the canvas.
    Only the small window that the piece lands in is worked on."""
    h, w = canvas.shape[:2]; ch, cw = crop.shape[:2]; A = M[:, :2]; t = M[:, 2]
    pts = np.array([[x0, y0], [x0 + cw, y0], [x0 + cw, y0 + ch], [x0, y0 + ch]], np.float32) @ A.T + t
    wx0, wy0 = int(max(0, np.floor(pts[:, 0].min()) - 1)), int(max(0, np.floor(pts[:, 1].min()) - 1)); wx1, wy1 = int(min(w, np.ceil(pts[:, 0].max()) + 2)), int(min(h, np.ceil(pts[:, 1].max()) + 2))
    if wx1 <= wx0 or wy1 <= wy0: return canvas
    Mw = np.hstack([A, (t + A @ np.array([x0, y0]) - np.array([wx0, wy0]))[:, None]]).astype(np.float32)
    win = cv2.warpAffine(np.ascontiguousarray(crop), Mw, (wx1 - wx0, wy1 - wy0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)); canvas[wy0:wy1, wx0:wx1] = _over(canvas[wy0:wy1, wx0:wx1], win); return canvas


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

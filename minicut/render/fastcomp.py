"""Fast layer compositing (CPU, uint8) used by Renderer.render().

The old path converted every layer to float32 at full canvas size. This one keeps the canvas as uint8 BGR, draws a
layer with ONE resize of only the visible part when that is possible (no rotation), and only falls back to a warp for
rotated layers. Hidden layers (covered by an opaque layer above) are not decoded at all."""
import math
import cv2
import numpy as np


def blend_into(base_roi, top_bgr, alpha, op):
    """Normal blend of top over base_roi in place. alpha: uint8 (h,w) or None (fully opaque). op: 0..1 opacity."""
    if alpha is None:
        if op >= 0.999: base_roi[...] = top_bgr
        else: base_roi[...] = cv2.addWeighted(base_roi, 1.0 - op, top_bgr, op, 0)
        return
    if op < 0.999: alpha = cv2.convertScaleAbs(alpha, alpha=op)
    # Avoid np.full_like (heap allocation) — use bitwise_not on the merged channel instead.
    a3 = cv2.merge((alpha, alpha, alpha))
    inv = cv2.bitwise_not(a3)
    base_roi[...] = cv2.add(cv2.multiply(top_bgr, a3, scale=1.0 / 255), cv2.multiply(base_roi, inv, scale=1.0 / 255))


def _alpha_comp(roi, res, alpha, op):
    """Composite a blended result over roi using alpha*op, in place."""
    if alpha is None:
        if op >= 0.999: roi[...] = res
        else: roi[...] = cv2.addWeighted(roi, 1.0 - op, res, op, 0)
        return
    a = cv2.convertScaleAbs(alpha, alpha=op) if op < 0.999 else alpha
    a3 = cv2.merge((a, a, a)); inv = cv2.bitwise_not(a3)
    roi[...] = cv2.add(cv2.multiply(res, a3, scale=1.0 / 255), cv2.multiply(roi, inv, scale=1.0 / 255))


def blend_mode(roi, top_bgr, alpha, op, mode):
    """Non-normal blend of top over roi in place.  Stays in uint8/uint16 wherever possible —
    2–3x faster than the old float32 path for multiply, screen, add, subtract, darken,
    lighten, difference; ~2.5x faster for overlay.  Max rounding error: 2 LSB (imperceptible)."""
    b16 = roi.astype(np.uint16); t16 = top_bgr.astype(np.uint16)
    if mode == "multiply":
        res = ((b16 * t16) >> 8).astype(np.uint8)
    elif mode == "screen":
        res = (255 - (((255 - b16) * (255 - t16)) >> 8)).astype(np.uint8)
    elif mode == "add":
        res = np.clip(b16 + t16, 0, 255).astype(np.uint8)
    elif mode == "subtract":
        res = np.clip(b16.astype(np.int32) - t16, 0, 255).astype(np.uint8)
    elif mode == "darken":
        res = np.minimum(roi, top_bgr)
    elif mode == "lighten":
        res = np.maximum(roi, top_bgr)
    elif mode == "difference":
        res = np.abs(b16.astype(np.int16) - t16.astype(np.int16)).astype(np.uint8)
    elif mode == "overlay":
        # Per-channel threshold avoids broadcasting issues and is still fast.
        hi  = np.clip(255 - ((2 * (255 - b16) * (255 - t16)) >> 8), 0, 255).astype(np.uint8)
        lo  = ((2 * b16 * t16) >> 8).astype(np.uint8)
        mk  = cv2.threshold(roi, 127, 255, cv2.THRESH_BINARY)[1]   # 255 where roi>=128
        res = cv2.add(cv2.bitwise_and(hi, mk), cv2.bitwise_and(lo, cv2.bitwise_not(mk)))
    elif mode == "soft light":
        # soft light has no cheap integer form; use float32 but only for the blend step
        bF = roi.astype(np.float32) * (1.0 / 255); tF = top_bgr.astype(np.float32) * (1.0 / 255)
        res = np.clip(((1 - 2 * tF) * bF * bF + 2 * tF * bF) * 255 + 0.5, 0, 255).astype(np.uint8)
    else:
        res = top_bgr
    _alpha_comp(roi, res, alpha, op)


def visible_rect(cx, cy, dw, dh, W, H):
    """Layer centre (cx, cy) and size (dw, dh) on a W x H canvas -> integer visible rectangle and the matching part of
    the layer as fractions (u0, v0, u1, v1) of the layer's width / height. None when nothing is visible."""
    dx0, dy0 = cx - dw / 2.0, cy - dh / 2.0
    vx0, vy0 = max(0, int(math.floor(dx0 + 0.5))), max(0, int(math.floor(dy0 + 0.5)))
    vx1, vy1 = min(W, int(math.floor(dx0 + dw + 0.5))), min(H, int(math.floor(dy0 + dh + 0.5)))
    if vx1 <= vx0 or vy1 <= vy0: return None
    u0, u1 = (vx0 - dx0) / dw, (vx1 - dx0) / dw
    v0, v1 = (vy0 - dy0) / dh, (vy1 - dy0) / dh
    return vx0, vy0, vx1, vy1, u0, v0, u1, v1


def resize_part(raw, u0, v0, u1, v1, out_w, out_h, fast=False):
    """The part (u0..u1, v0..v1 as fractions) of raw, resized to out_w x out_h in one pass."""
    ih, iw = raw.shape[:2]
    x0, x1 = int(round(u0 * iw)), int(round(u1 * iw)); y0, y1 = int(round(v0 * ih)), int(round(v1 * ih))
    x0, y0 = max(0, min(iw - 1, x0)), max(0, min(ih - 1, y0)); x1, y1 = max(x0 + 1, min(iw, x1)), max(y0 + 1, min(ih, y1))
    crop = raw[y0:y1, x0:x1]
    if crop.shape[1] == out_w and crop.shape[0] == out_h: return crop
    if fast: return cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    cw, ch = crop.shape[1], crop.shape[0]
    r = min(cw / float(out_w), ch / float(out_h))
    if r >= 1.5:
        # Shrinking: first an exact integer shrink with the fast area filter (anti-aliased), then a small linear step to the
        # exact size. The generic area filter for odd ratios is 5-6 times slower for almost the same picture.
        k = max(2, int(round(r)))
        crop = crop[:ch // k * k, :cw // k * k]
        crop = cv2.resize(crop, (cw // k, ch // k), interpolation=cv2.INTER_AREA)
        if crop.shape[1] == out_w and crop.shape[0] == out_h: return crop
    return cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_LINEAR)


def covers_canvas(cx, cy, dw, dh, W, H, rot):
    """True when an unrotated layer of this size and place hides the whole canvas."""
    if abs(rot) > 0.01: return False
    return cx - dw / 2.0 <= 0.5 and cy - dh / 2.0 <= 0.5 and cx + dw / 2.0 >= W - 0.5 and cy + dh / 2.0 >= H - 0.5


def to_cv_matrix(M):
    """A placing matrix in corner coordinates (image corners at whole numbers: how Qt and the GPU draw) -> the matrix for
    cv2.warpAffine, which counts from pixel centres. Without it a mirrored layer would be one pixel off."""
    M = np.array(M, np.float32)
    M[0, 2] += 0.5 * (M[0, 0] + M[0, 1]) - 0.5
    M[1, 2] += 0.5 * (M[1, 0] + M[1, 1]) - 0.5
    return M

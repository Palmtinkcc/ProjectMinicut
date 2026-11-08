"""Fast CPU versions of the most used effects (Patch 34: render optimisation).

Why this file exists
--------------------
The original effect functions work in float32 on the whole picture (several temporary copies of the frame for every effect) and the
GPU variants upload / read back the picture for every single effect. On an old CPU or an old GPU both are slow, so adding one effect to a
clip made the preview drop to 10-20 FPS.

What these versions do instead
------------------------------
  * 8-bit only: no float32 copy of the frame. Point operations (tint, B&W, adjust, posterize, ...) are one 256-entry lookup table (cv2.LUT).
  * Blurs and glows of a big radius run on a shrunken copy of the picture (the result is smooth anyway) and are scaled back up.
  * Vignette masks, film grain and noise are built once, kept in a cache and only *applied* every frame.
  * Maps for warps (radial RGB split) are cached.
  * Only 3 channels are processed when the picture is fully opaque (every video frame); the alpha channel is put back at the end.
  * Everything stays on the CPU: no OpenGL context, no upload / read-back, so it behaves the same on every PC.

Every function has the same signature and the same look as the original. Where a rare case is not covered (transparent pictures for some
blurs, sharpen with a threshold, ...) the original function is called, so nothing is lost.  Any error is caught by apply_effects()."""
import math
import numpy as np
import cv2
from ..shared.deps import QColor

_ORIG = {}                      # effect type -> the original image function (used for the rare cases that are not covered here)


# ───────────────────────── helpers ─────────────────────────
def _opaque(img):
    """True when every pixel is fully opaque (the normal case for video frames). A 3-channel picture has no alpha: it is opaque."""
    return img.shape[2] == 3 or cv2.minMaxLoc(cv2.extractChannel(img, 3))[0] >= 255


def _bgr(img):
    return img if img.shape[2] == 3 else cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def _put(img, bgr, opq):
    """New colour (BGR) + the alpha of `img` -> same layout as `img` (BGR stays BGR: the 3-channel lane never makes the alpha plane)."""
    if img.shape[2] == 3: return bgr
    if opq: return cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    out = np.empty_like(img)
    cv2.mixChannels([np.ascontiguousarray(bgr), img], [out], [0, 0, 1, 1, 2, 2, 6, 3])
    return out


def _gray3(bgr):
    return cv2.cvtColor(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def _u8(x):
    return np.clip(np.asarray(x, np.float32) + .5, 0, 255).astype(np.uint8)


def _lut3(b, g, r):
    return np.ascontiguousarray(np.stack([b, g, r], -1).reshape(256, 1, 3))


def _call_orig(name, img, p, ctx):
    """The original (slower, complete) function. It expects BGRA, so a 3-channel picture is widened and narrowed again."""
    if img.shape[2] == 3:
        out = _ORIG[name](cv2.cvtColor(img, cv2.COLOR_BGR2BGRA), p, ctx)
        return out if out is None or out.ndim != 3 or out.shape[2] == 3 else cv2.cvtColor(out, cv2.COLOR_BGRA2BGR)
    return _ORIG[name](img, p, ctx)


def _ksize(sigma):
    return int(sigma * 3) * 2 + 1


def _shrink_factor(sigma):
    """How much a blur of this sigma may be shrunk before it is run (1 = not at all)."""
    return 1 if sigma < 3.0 else int(min(8, max(2, sigma / 1.5)))


def gauss_u8(a, sx, sy=None):
    """Gaussian blur of an 8-bit picture. Big sigmas run on a shrunken copy, so the cost stays small for any radius."""
    if sy is None: sy = sx
    sx = float(sx); sy = float(sy)
    if sx < 0.3 and sy < 0.3: return a
    h, w = a.shape[:2]
    fx, fy = _shrink_factor(sx), _shrink_factor(sy)
    if fx == 1 and fy == 1:
        return cv2.GaussianBlur(a, (_ksize(sx) if sx >= 0.3 else 1, _ksize(sy) if sy >= 0.3 else 1), sx if sx >= 0.3 else 0.01, sigmaY=sy if sy >= 0.3 else 0.01)
    sw, sh = max(1, w // fx), max(1, h // fy)
    small = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    rx, ry = w / float(sw), h / float(sh)                       # the real shrink ratios
    tx = math.sqrt(max(sx * sx - rx * rx * 0.25, 0.04)) / rx if sx >= 0.3 else 0.0
    ty = math.sqrt(max(sy * sy - ry * ry * 0.25, 0.04)) / ry if sy >= 0.3 else 0.0
    small = cv2.GaussianBlur(small, (_ksize(tx) if tx >= 0.3 else 1, _ksize(ty) if ty >= 0.3 else 1), tx if tx >= 0.3 else 0.01, sigmaY=ty if ty >= 0.3 else 0.01)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


# ───────────────────────── colour ─────────────────────────
def fx_tint(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    col = QColor(p["color"]); tc = np.array([col.blueF(), col.greenF(), col.redF()], np.float32)
    g = (np.arange(256, dtype=np.float32) / 255.0)[:, None]
    T = np.where(g < 0.5, 2 * g * tc, 1 - 2 * (1 - g) * (1 - tc))
    lut = np.ascontiguousarray(_u8(T * 255.0).reshape(256, 1, 3))
    opq = _opaque(img); bgr = _bgr(img)
    t = cv2.LUT(_gray3(bgr), lut)
    return _put(img, t if a >= 0.999 else cv2.addWeighted(bgr, 1 - a, t, a, 0), opq)


def fx_bw(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    opq = _opaque(img); bgr = _bgr(img); g3 = _gray3(bgr)
    return _put(img, g3 if a >= 0.999 else cv2.addWeighted(bgr, 1 - a, g3, a, 0), opq)


def fx_invert(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    opq = _opaque(img); bgr = _bgr(img)
    if a >= 0.999: return _put(img, cv2.bitwise_not(bgr), opq)
    x = np.arange(256, dtype=np.float32)
    return _put(img, cv2.LUT(bgr, _u8(x + (255 - 2 * x) * a)), opq)


def _lum_offset(bgr, hi, sh):
    """Lift / pull highlights and shadows: an offset per luminance value, added to the three channels."""
    l = np.arange(256, dtype=np.float32) / 255.0
    off = np.clip((l - 0.5) * 2, 0, 1) * hi + np.clip((0.5 - l) * 2, 0, 1) * sh        # -0.5 .. 0.5
    pos = _u8(np.clip(off, 0, 1) * 255.0); neg = _u8(np.clip(-off, 0, 1) * 255.0)
    g3 = _gray3(bgr)
    return cv2.subtract(cv2.add(bgr, cv2.LUT(g3, pos)), cv2.LUT(g3, neg))


def fx_adjust(img, p, ctx):
    br, co, sa, hu = p["brightness"], p["contrast"], p["saturation"], p["hue"]
    temp, vib, hi, sh = p.get("temperature", 0.0), p.get("vibrance", 0.0), p.get("highlights", 0.0), p.get("shadows", 0.0)
    if br == 0 and co == 0 and sa == 0 and hu == 0 and temp == 0 and vib == 0 and hi == 0 and sh == 0: return img
    opq = _opaque(img); bgr = _bgr(img)
    if br != 0 or co != 0 or temp != 0:
        x = np.arange(256, dtype=np.float32) / 255.0
        base = (x - .5) * (1 + co / 100.0) + .5 + br / 200.0
        lb = lg = lr = base
        if temp != 0:
            t = temp / 100.0; lr = np.clip(base + t * 0.15, 0, 1); lb = np.clip(base - t * 0.15, 0, 1)
        bgr = cv2.LUT(bgr, _lut3(_u8(np.clip(lb, 0, 1) * 255.0), _u8(np.clip(lg, 0, 1) * 255.0), _u8(np.clip(lr, 0, 1) * 255.0)))
    if hi != 0 or sh != 0:
        bgr = _lum_offset(bgr, hi / 200.0, sh / 200.0)
    if sa != 0 or hu != 0 or vib != 0:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        i = np.arange(256, dtype=np.float32)
        h_l = np.floor((i + hu / 2.0) % 180).astype(np.uint8) if hu != 0 else i.astype(np.uint8)
        s = np.clip(i * (1 + sa / 100.0), 0, 255)
        if vib != 0: s = np.clip(s + (1.0 - s / 255.0) * (vib / 100.0) * 255.0, 0, 255)
        s_l = np.floor(s).astype(np.uint8)
        hsv = cv2.LUT(hsv, _lut3(h_l, s_l, i.astype(np.uint8)))
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return _put(img, bgr, opq)


def fx_hue_shift(img, p, ctx):
    shift = p["shift"]
    if shift == 0: return img
    opq = _opaque(img); hsv = cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2HSV)
    i = np.arange(256, dtype=np.float32)
    hl = np.floor((i + shift / 2.0) % 180).astype(np.uint8); ident = i.astype(np.uint8)
    return _put(img, cv2.cvtColor(cv2.LUT(hsv, _lut3(hl, ident, ident)), cv2.COLOR_HSV2BGR), opq)


def fx_color_temperature(img, p, ctx):
    temp = p["temperature"] / 100.0; tint = p.get("tint", 0.0) / 100.0
    if temp == 0 and tint == 0: return img
    x = np.arange(256, dtype=np.float32)
    r = np.clip(x + temp * 30, 0, 255)
    g = np.clip(x + tint * 20, 0, 255)
    b = np.clip(np.clip(x - temp * 30, 0, 255) - tint * 20, 0, 255)
    opq = _opaque(img)
    return _put(img, cv2.LUT(_bgr(img), _lut3(_u8(b), _u8(g), _u8(r))), opq)


def fx_highlights_shadows(img, p, ctx):
    hi = p["highlights"] / 100.0; sh = p["shadows"] / 100.0
    if hi == 0 and sh == 0: return img
    opq = _opaque(img)
    return _put(img, _lum_offset(_bgr(img), hi * 0.5, sh * 0.5), opq)


def fx_posterize(img, p, ctx):
    levels = max(2, int(p["levels"])); step = 255.0 / (levels - 1)
    x = np.arange(256, dtype=np.float32)
    opq = _opaque(img)
    return _put(img, cv2.LUT(_bgr(img), _u8(np.round(x / step) * step)), opq)


def fx_threshold(img, p, ctx):
    opq = _opaque(img)
    gray = cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2GRAY)
    m = cv2.threshold(gray, int(p["level"]) - 1, 255, cv2.THRESH_BINARY)[1]          # gray >= level
    if p.get("invert", False): m = cv2.bitwise_not(m)
    return _put(img, cv2.cvtColor(m, cv2.COLOR_GRAY2BGR), opq)


def fx_gradient_map(img, p, ctx):
    clo, chi = QColor(p.get("color_lo", "#000000")), QColor(p.get("color_hi", "#ffffff")); a = p.get("amount", 100.0) / 100.0
    lo = np.array([clo.blueF(), clo.greenF(), clo.redF()], np.float32) * 255; hi = np.array([chi.blueF(), chi.greenF(), chi.redF()], np.float32) * 255
    l = (np.arange(256, dtype=np.float32) / 255.0)[:, None]
    lut = np.ascontiguousarray(_u8(lo + l * (hi - lo)).reshape(256, 1, 3))
    opq = _opaque(img); bgr = _bgr(img); mapped = cv2.LUT(_gray3(bgr), lut)
    return _put(img, mapped if a >= 0.999 else cv2.addWeighted(bgr, 1 - a, mapped, a, 0), opq)


def fx_luma_key(img, p, ctx):
    thr = p["threshold"] / 100.0; soft = max(0.001, p.get("softness", 10.0) / 100.0)
    l = np.arange(256, dtype=np.float32) / 255.0
    k = np.clip((thr - l) / soft, 0, 1) if p.get("mode", "dark") == "bright" else np.clip((l - thr) / soft, 0, 1)
    ka = _u8(k * 255.0)
    gray = cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2GRAY)
    b, g, r, a = cv2.split(img)
    return cv2.merge([b, g, r, cv2.multiply(a, cv2.LUT(gray, ka), scale=1.0 / 255)])


def fx_chroma(img, p, ctx):
    key = QColor(p["color"]); tol = int(p["tolerance"])
    hsv = cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2HSV)
    kh = cv2.cvtColor(np.uint8([[[key.blue(), key.green(), key.red()]]]), cv2.COLOR_BGR2HSV)[0, 0]
    h, s, _ = cv2.split(hsv)
    d = np.arange(256, dtype=np.int32); wrap = np.clip(np.minimum(d, 180 - d) * 2, 0, 255).astype(np.uint8)
    dh = cv2.LUT(cv2.absdiff(h, np.full_like(h, int(kh[0]))), wrap)
    ds = cv2.absdiff(s, np.full_like(s, int(kh[1])))
    m = cv2.max(dh, ds)
    ka = _u8(np.clip((np.arange(256, dtype=np.float32) - tol) / max(1, tol), 0, 1) * 255.0)
    b, g, r, a = cv2.split(img)
    return cv2.merge([b, g, r, cv2.multiply(a, cv2.LUT(m, ka), scale=1.0 / 255)])


# ───────────────────────── blur ─────────────────────────
def fx_blur(img, p, ctx):
    amt = p["amount"] * ctx.k
    if amt < 0.3: return img
    sx = amt * p["x_blur"] / 100.0; sy = amt * p["y_blur"] / 100.0
    if sx < 0.3 and sy < 0.3: return img
    if p.get("alpha_blur", False) and not _opaque(img): return _call_orig("blur", img, p, ctx)      # blurring a transparent edge needs premultiplied pixels
    opq = _opaque(img)
    if abs(sx - sy) < 0.5: sy = sx
    return _put(img, gauss_u8(_bgr(img), sx, sy), opq)


def _box_axis(src, k, ang, bidir, border):
    """Motion blur along an axis (0 / 90 / 180 / 270 degrees) as a box filter: cost does not depend on the length."""
    if bidir:
        kk = k | 1; return cv2.boxFilter(src, -1, (kk, 1) if ang in (0, 180) else (1, kk), borderType=border)
    if ang == 0:   return cv2.boxFilter(src, -1, (k, 1), anchor=(0, 0), borderType=border)
    if ang == 180: return cv2.boxFilter(src, -1, (k, 1), anchor=(k - 1, 0), borderType=border)
    if ang == 90:  return cv2.boxFilter(src, -1, (1, k), anchor=(0, 0), borderType=border)
    return cv2.boxFilter(src, -1, (1, k), anchor=(0, k - 1), borderType=border)


def fx_motion_blur(img, p, ctx):
    n = int(p["length"] * ctx.k)
    if n < 2: return img
    if not _opaque(img): return _call_orig("motion_blur", img, p, ctx)
    h, w = img.shape[:2]; n = min(n, max(h, w) // 2); bidir = bool(p.get("bidirectional", False))
    ang = float(p["angle"]) % 360.0; bgr = _bgr(img)
    # The original blurs the transparency too, so the picture's edge fades out. Same here, but only the alpha plane is computed (one channel).
    for axis in (0, 90, 180, 270):
        if abs(ang - axis) < 1e-6:
            k = n if bidir else n // 2 + 1
            res = _box_axis(bgr, k, axis, bidir, cv2.BORDER_REPLICATE)
            al = _box_axis(np.full((h, w), 255, np.uint8), k, axis, bidir, cv2.BORDER_CONSTANT)
            return cv2.merge([*cv2.split(res), al])
    sc = max(1.0, n / 9.0)
    small = cv2.resize(bgr, (max(1, int(w / sc)), max(1, int(h / sc))), interpolation=cv2.INTER_AREA) if sc > 1 else bgr
    m = max(3, int(round(n / sc))) | 1; ker = np.zeros((m, m), np.float32)
    if bidir: ker[m // 2, :] = 1
    else: ker[m // 2, m // 2:] = 1
    ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((m / 2 - .5, m / 2 - .5), -p["angle"], 1), (m, m))
    ker /= max(float(ker.sum()), 1e-6)
    res = cv2.filter2D(small, -1, ker, borderType=cv2.BORDER_REPLICATE)
    al = cv2.filter2D(np.full(small.shape[:2], 255, np.uint8), -1, ker, borderType=cv2.BORDER_CONSTANT)
    if sc > 1: res = cv2.resize(res, (w, h), interpolation=cv2.INTER_LINEAR); al = cv2.resize(al, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.merge([*cv2.split(res), al])


def _steps_for(disp_px, fast):
    """How many samples a radial blur needs: about one per two pixels of travel at the edge, never fewer than 4."""
    return int(max(4, min(10 if fast else 14, disp_px * 0.5 + 2)))


def _warp_avg(src, mats):
    h, w = src.shape[:2]; acc = np.zeros((h, w, 3), np.float32)
    for M in mats: cv2.accumulate(cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE), acc)
    return cv2.convertScaleAbs(acc, alpha=1.0 / len(mats))


def _rot_mat(cx, cy, ang):
    """Rotation by `ang` radians around (cx, cy). (The original CPU spin blurs had an extra +cy in the translation, which pushed the
    whole picture down by half its height; the GPU version never had it. This is the correct matrix.)"""
    c, s = math.cos(ang), math.sin(ang)
    return np.array([[c, -s, cx - cx * c + cy * s], [s, c, cy - cx * s - cy * c]], np.float32)


def _radial(img, ctx, make_mats, disp_fn, fade_edges=False):
    """Shared body of the zoom / spin blurs: the work runs on a half-size picture and the result is scaled back up.
    fade_edges: a rotating blur leaves the corners empty; like the original, those corners fade to transparent (alpha plane only)."""
    h, w = img.shape[:2]; bgr = _bgr(img)
    sc = 2 if min(w, h) >= 240 else 1
    small = cv2.resize(bgr, (max(1, w // sc), max(1, h // sc)), interpolation=cv2.INTER_AREA) if sc > 1 else bgr
    sh_, sw_ = small.shape[:2]
    mats = make_mats(sw_, sh_, _steps_for(disp_fn(sw_, sh_), ctx.fast))
    res = _warp_avg(small, mats); al = None
    if fade_edges:
        acc = np.zeros((sh_, sw_), np.float32); one = np.full((sh_, sw_), 255, np.uint8)
        for M in mats: cv2.accumulate(cv2.warpAffine(one, M, (sw_, sh_), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT), acc)
        al = cv2.convertScaleAbs(acc, alpha=1.0 / len(mats))
    if sc > 1:
        res = cv2.resize(res, (w, h), interpolation=cv2.INTER_LINEAR)
        if al is not None: al = cv2.resize(al, (w, h), interpolation=cv2.INTER_LINEAR)
    return _put(img, res, True) if al is None else cv2.merge([*cv2.split(res), al])


def fx_radial_blur(img, p, ctx):
    amt = p["amount"] / 100.0
    if amt <= 0.002: return img
    if not _opaque(img): return _call_orig("radial_blur", img, p, ctx)
    spin = p.get("mode", "zoom") == "spin"; px, py = p["cx"] / 100.0, p["cy"] / 100.0
    def mats(w, h, steps):
        cx, cy = w * px, h * py; out = []
        for i in range(steps):
            if spin: out.append(_rot_mat(cx, cy, amt * 0.3 * (i / max(1, steps - 1) - 0.5)))      # centred on 0: the sharp picture stays in place
            else:
                z = 1 + amt * 0.25 * (i / max(1, steps - 1) - 0.5); out.append(np.array([[z, 0, cx - cx * z], [0, z, cy - cy * z]], np.float32))
        return out
    disp = (lambda w, h: amt * 0.3 * math.hypot(w, h) / 2) if spin else (lambda w, h: amt * 0.25 * max(w, h) / 2)
    return _radial(img, ctx, mats, disp, fade_edges=spin)


def fx_zoom_blur(img, p, ctx):
    amt = p["amount"] / 100.0
    if amt <= 0.001: return img
    if not _opaque(img): return _call_orig("zoom_blur", img, p, ctx)
    px, py = p.get("cx", 50.0) / 100.0, p.get("cy", 50.0) / 100.0
    def mats(w, h, steps):
        cx, cy = w * px, h * py; out = []
        for i in range(steps):
            z = 1.0 + amt * 0.5 * (i / max(1, steps - 1) - 0.5); out.append(np.array([[z, 0, cx * (1 - z)], [0, z, cy * (1 - z)]], np.float32))
        return out
    return _radial(img, ctx, mats, lambda w, h: amt * 0.5 * max(w, h) / 2)


def fx_spin_blur(img, p, ctx):
    ang = p["angle"]
    if abs(ang) < 0.1: return img
    if not _opaque(img): return _call_orig("spin_blur", img, p, ctx)
    px, py = p.get("cx", 50.0) / 100.0, p.get("cy", 50.0) / 100.0
    def mats(w, h, steps):
        return [_rot_mat(w * px, h * py, math.radians(ang * (i / max(1, steps - 1) - 0.5))) for i in range(steps)]
    return _radial(img, ctx, mats, lambda w, h: abs(math.radians(ang)) * math.hypot(w, h) / 2, fade_edges=True)


# ───────────────────────── distort ─────────────────────────
_MAPS = {}


def _radial_maps(h, w, d, cx, cy):
    key = (h, w, round(d, 2), round(cx, 1), round(cy, 1)); m = _MAPS.get(key)
    if m is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - cx) / (w / 2); ny = (yy - cy) / (h / 2); ln = np.maximum(np.sqrt(nx * nx + ny * ny), 1e-5)
        ux, uy = nx / ln * d, ny / ln * d
        m = ((xx + ux, yy + uy), (xx - ux, yy - uy))
        if len(_MAPS) > 4: _MAPS.pop(next(iter(_MAPS)))
        _MAPS[key] = m
    return m


def fx_rgb_split(img, p, ctx):
    d = p["amount"] * ctx.k
    if d < 0.3: return img
    mode = p.get("mode", "directional"); h, w = img.shape[:2]
    planes = cv2.split(img); b, g, r = planes[:3]; a = planes[3] if len(planes) == 4 else None
    flags = dict(flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if mode == "zoom":
        cx, cy = w * p.get("cx", 50.0) / 100, h * p.get("cy", 50.0) / 100
        for ch, scale in ((2, 1 + d / w), (0, 1 - d / w)):
            if scale <= 0: continue
            M = np.array([[scale, 0, cx * (1 - scale)], [0, scale, cy * (1 - scale)]], np.float32)
            if ch == 2: r = cv2.warpAffine(r, M, (w, h), **flags)
            else: b = cv2.warpAffine(b, M, (w, h), **flags)
    elif mode == "radial":
        (rx, ry), (bx, by) = _radial_maps(h, w, d, w * p.get("cx", 50.0) / 100, h * p.get("cy", 50.0) / 100)
        r = cv2.remap(r, rx, ry, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        b = cv2.remap(b, bx, by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    else:
        th = math.radians(p["angle"]); dx, dy = math.cos(th) * d, math.sin(th) * d
        r = cv2.warpAffine(r, np.array([[1, 0, dx], [0, 1, dy]], np.float32), (w, h), **flags)
        b = cv2.warpAffine(b, np.array([[1, 0, -dx], [0, 1, -dy]], np.float32), (w, h), **flags)
    return cv2.merge([b, g, r] if a is None else [b, g, r, a])


def fx_glitch(img, p, ctx):
    amt = p["amount"] / 100
    if amt <= 0: return img
    h, w = img.shape[:2]; rng = np.random.default_rng(int(ctx.lt * 12) * 7919 + int(p["seed"])); out = img.copy()
    for _ in range(int(2 + amt * 14)):
        y0 = int(rng.integers(0, h)); hh = int(rng.integers(max(1, h // 80), max(2, h // 8))); sh = int(rng.normal(0, w * 0.08 * amt))
        if hh > 0 and sh: out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], sh, axis=1)
    return fx_rgb_split(out, {"amount": 6 * amt, "angle": 0}, ctx)


def fx_pixelate(img, p, ctx):
    s = max(1, int(round(p["size"] * ctx.k))); h, w = img.shape[:2]
    if s <= 1: return img
    small = cv2.resize(img, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


# ───────────────────────── stylize ─────────────────────────
def fx_sharpen(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    if p.get("threshold", 0.0) > 0: return _call_orig("sharpen", img, p, ctx)
    radius = max(0.4, p.get("radius", 1.0) * ctx.k)
    opq = _opaque(img); bgr = _bgr(img)
    blurred = gauss_u8(bgr, radius)
    return _put(img, cv2.addWeighted(bgr, 1 + a, blurred, -a, 0), opq)


_VIG = {}


def _vignette_weight(h, w, softness, rnd):
    """Vignette strength 0..1 per pixel, made on a small grid and scaled up (it is a smooth shape)."""
    sw = max(2, min(w, 384)); sh = max(2, int(round(sw * h / float(w))))
    xs = (np.arange(sw, dtype=np.float32) + .5) / sw * 2 - 1; ys = (np.arange(sh, dtype=np.float32) + .5) / sh * 2 - 1
    nx, ny = np.meshgrid(xs, ys)
    r_box = np.maximum(np.abs(nx), np.abs(ny)); r_cir = np.sqrt(nx * nx + ny * ny) / 1.4142
    r = r_box + (r_cir - r_box) * rnd; start = 1.0 - softness / 100 * 0.95
    m = np.clip((r - start) / max(1e-3, 1 - start), 0, 1) ** 2
    return m if (sw == w and sh == h) else cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)


def fx_vignette(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    h, w = img.shape[:2]; rnd = p.get("roundness", 50.0) / 100.0; mode = p.get("mode", "darken"); col = p.get("color", "#000000")
    key = (h, w, round(a, 3), round(p["softness"], 1), round(rnd, 2), mode, col if mode == "color" else "")
    ent = _VIG.get(key)
    if ent is None:
        v = _vignette_weight(h, w, p["softness"], rnd) * a
        inv = np.clip((1 - v) * 255.0 + .5, 0, 255).astype(np.uint8)
        if mode == "alpha": ent = (inv, None)
        else:
            c = QColor(col); tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32) * 255
            add = None if mode != "color" or not tc.any() else np.ascontiguousarray(np.clip(v[..., None] * tc + .5, 0, 255).astype(np.uint8))
            ent = (cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR), add)
        if len(_VIG) >= 4: _VIG.pop(next(iter(_VIG)))
        _VIG[key] = ent
    inv, add = ent
    if mode == "alpha":
        b, g, r, al = cv2.split(img); return cv2.merge([b, g, r, cv2.multiply(al, inv, scale=1.0 / 255)])
    opq = _opaque(img); out = cv2.multiply(_bgr(img), inv, scale=1.0 / 255)
    if add is not None: out = cv2.add(out, add)
    return _put(img, out, opq)


def _glow_scale(radius):
    return int(min(8, max(1, radius / 3.0)))


def _glow_layer(bgr, radius, weight_fn=None):
    """(blurred light layer at full size). weight_fn(small_bgr) -> small_bgr lets the caller pick which pixels glow."""
    h, w = bgr.shape[:2]; f = _glow_scale(radius)
    small = cv2.resize(bgr, (max(1, w // f), max(1, h // f)), interpolation=cv2.INTER_AREA) if f > 1 else bgr
    if weight_fn is not None: small = weight_fn(small)
    rs = w / float(small.shape[1])
    small = gauss_u8(small, max(0.5, radius / rs))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR) if f > 1 else small


def _screen(base, top):
    return cv2.bitwise_not(cv2.multiply(cv2.bitwise_not(base), cv2.bitwise_not(top), scale=1.0 / 255))


def fx_glow(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    if p.get("color"): return _call_orig("glow", img, p, ctx)                        # the tinted glow keeps its original formula
    radius = max(0.5, p["radius"] * ctx.k); thr = p["threshold"] / 100.0
    opq = _opaque(img); bgr = _bgr(img)
    l = np.arange(256, dtype=np.float32) / 255.0; mask = np.clip((l - thr) / max(1e-3, 1 - thr), 0, 1)
    def bright(small):                      # only the bright pixels glow: colour * (how far the luminance is above the threshold)
        m = cv2.LUT(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), _u8(mask * 255.0))
        return cv2.multiply(small, cv2.cvtColor(m, cv2.COLOR_GRAY2BGR), scale=1.0 / 255)
    glow = _glow_layer(bgr, radius, bright)
    ga = cv2.convertScaleAbs(glow, alpha=a)
    out = cv2.add(bgr, ga) if p.get("blend_mode", "screen") == "add" else _screen(bgr, ga)
    return _put(img, out, opq)


def fx_soft_glow(img, p, ctx):
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k); softness = p.get("softness", 50.0) / 100.0
    opq = _opaque(img); bgr = _bgr(img)
    soft = cv2.convertScaleAbs(_glow_layer(bgr, radius), alpha=softness)
    return _put(img, cv2.addWeighted(bgr, 1 - amount, _screen(bgr, soft), amount, 0), opq)


def fx_dark_glow(img, p, ctx):
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k); thr = p.get("threshold", 40.0) / 100.0
    opq = _opaque(img); bgr = _bgr(img)
    l = np.arange(256, dtype=np.float32) / 255.0; mask = np.clip((thr - l) / max(1e-3, thr), 0, 1)
    def dark(small):
        m = cv2.LUT(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), _u8(mask * 255.0))
        return cv2.multiply(cv2.bitwise_not(small), cv2.cvtColor(m, cv2.COLOR_GRAY2BGR), scale=1.0 / 255)
    spread = cv2.convertScaleAbs(_glow_layer(bgr, radius, dark), alpha=amount)
    return _put(img, cv2.subtract(bgr, spread), opq)


_POOL = 10
_GRAIN = {}
_NOISE = {}


def _pool_get(store, key, i, make):
    ent = store.get(key)
    if ent is None:
        if len(store) >= 3: store.pop(next(iter(store)))
        ent = store[key] = [None] * _POOL
    if ent[i] is None: ent[i] = make(i)
    return ent[i]


def _flipped(n, k):
    return n if k == 0 else cv2.flip(n, (1, 0, -1)[k - 1])


def fx_grain(img, p, ctx):
    a = p["amount"] / 100.0
    if a <= 0: return img
    h, w = img.shape[:2]; s = max(1, int(round(p["size"] * ctx.k))); color = bool(p.get("color_grain", False))
    frame = int(ctx.lt * 24); i, fl = frame % _POOL, (frame // _POOL) % 4
    def make(j):
        rng = np.random.default_rng(104729 + j); gh, gw = max(1, h // s), max(1, w // s)
        n = np.clip(rng.standard_normal((gh, gw, 3) if color else (gh, gw)).astype(np.float32) * 40 + 128, 0, 255).astype(np.uint8)
        return np.ascontiguousarray(cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR) if s > 1 else n)
    n = _flipped(_pool_get(_GRAIN, (h, w, s, color), i, make), fl)
    d = np.arange(256, dtype=np.float32) - 128
    pos = cv2.LUT(n, _u8(np.clip(d, 0, None) * a)); neg = cv2.LUT(n, _u8(np.clip(-d, 0, None) * a))
    if not color: pos = cv2.cvtColor(pos, cv2.COLOR_GRAY2BGR); neg = cv2.cvtColor(neg, cv2.COLOR_GRAY2BGR)
    opq = _opaque(img)
    return _put(img, cv2.subtract(cv2.add(_bgr(img), pos), neg), opq)


def fx_noise(img, p, ctx):
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    h, w = img.shape[:2]; frame = int(ctx.lt * 30); i, fl = frame % _POOL, (frame // _POOL) % 4
    def make(j): return np.random.default_rng(48611 + j).integers(0, 256, (h, w, 3), dtype=np.uint8)
    n = _flipped(_pool_get(_NOISE, (h, w), i, make), fl)
    opq = _opaque(img)
    return _put(img, cv2.addWeighted(_bgr(img), 1 - amount, n, amount, 0), opq)


def fx_find_edges(img, p, ctx):
    amount = p["amount"] / 100.0; sigma = max(0.4, p.get("softness", 1.0) * ctx.k)
    opq = _opaque(img); rgb = _bgr(img)
    if p.get("mode", "luminance") == "color":
        edges = cv2.convertScaleAbs(cv2.absdiff(rgb, cv2.GaussianBlur(rgb, (0, 0), sigma)), alpha=amount * 4)
    else:
        g = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY), (0, 0), sigma)
        edges = cv2.cvtColor(cv2.convertScaleAbs(cv2.Laplacian(g, cv2.CV_16S), alpha=amount * 4), cv2.COLOR_GRAY2BGR)
    if p.get("invert", False): edges = cv2.bitwise_not(edges)
    return _put(img, edges, opq)


# ───────────────────────── install ─────────────────────────
_FAST = {"tint": fx_tint, "bw": fx_bw, "invert": fx_invert, "adjust": fx_adjust, "hue_shift": fx_hue_shift,
         "color_temperature": fx_color_temperature, "highlights_shadows": fx_highlights_shadows, "posterize": fx_posterize,
         "threshold": fx_threshold, "gradient_map": fx_gradient_map, "luma_key": fx_luma_key, "chroma": fx_chroma,
         "blur": fx_blur, "motion_blur": fx_motion_blur, "radial_blur": fx_radial_blur, "zoom_blur": fx_zoom_blur, "spin_blur": fx_spin_blur,
         "rgb_split": fx_rgb_split, "glitch": fx_glitch, "pixelate": fx_pixelate,
         "sharpen": fx_sharpen, "vignette": fx_vignette, "glow": fx_glow, "soft_glow": fx_soft_glow, "dark_glow": fx_dark_glow,
         "grain": fx_grain, "noise": fx_noise, "find_edges": fx_find_edges}


# Effects that take and give a 3-channel picture, so an opaque video frame never needs the alpha plane (saves 3-4 colour conversions per frame).
LANE_BGR = frozenset(_FAST) - {"luma_key", "chroma", "motion_blur", "radial_blur", "zoom_blur", "spin_blur"}


def lane_ok(e):
    """May this effect layer (dict) run on a 3-channel picture?"""
    t = e.get("type")
    if t not in LANE_BGR: return False
    if t == "vignette" and (e.get("p") or {}).get("mode") == "alpha": return False
    return True


def install(FX):
    """Swap the image function of every effect listed above for its fast version (the original is kept for the rare cases)."""
    n = 0
    for name, fn in _FAST.items():
        spec = FX.get(name)
        if spec is None: continue
        _ORIG[name] = spec["fn"]; spec["fn"] = fn; n += 1
    return n

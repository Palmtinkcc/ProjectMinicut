"""Better Chroma Key.

Two ways to take a subject out of its background, one effect ("Better Chroma Key", category Key):

  * Background color  - live, like the old Chroma Key but better: a soft matte from the chroma distance (so shadows on the screen
    do not matter), colour spill removed from the subject, and an *edge colour* step that repaints the rim of the subject
    (the semi-transparent pixels and a few pixels inside) with the colour of the subject itself, or with a colour of your choice,
    so a green fringe cannot show.
  * Select object     - you paint the object (and, if you like, the background); the program finds the object's edge with GrabCut,
    follows it through the video with optical flow, sharpens the edge with a colour-guided filter and removes the background colour
    from the edge pixels. This cannot run for every frame while you play, so it is *rendered* once, like CapCut does: the clip is
    rendered into a new media file (colour and matte packed side by side in an all-intra H.264 file, or a PNG for a picture) and
    that file is used instead of the original media. Turn the effect off, delete it, change the paint, or Undo: the original media is
    used again (nothing is ever overwritten; the rendered files live in ~/.minicut/smartkey).

This module has no widgets in it, so it can be tested without a window.
"""
import os, json, time, math, hashlib, subprocess, threading, tempfile, shutil
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import cv2
from ..shared.core import APP_DIR, FFMPEG, NOWIN, safe_path, src_time

SK_VER = 3                                   # change it when the result of a render changes: old renders are then ignored
CACHE_DIR = os.path.join(APP_DIR, "smartkey")
FULL_LIMIT_S = 120.0                         # up to this length the whole file is rendered; longer: the part the clip uses, +- MARGIN_S
MARGIN_S = 5.0
QUALITY = {"fast": 384, "normal": 512, "high": 768}      # long side of the picture the object is searched in
CACHE_MAX_BYTES = 8 * 1024 ** 3

MODE_CHOICES = [("color", "Background color"), ("object", "Select object")]
EDGE_CHOICES = [("off", "Off"), ("auto", "Match the subject"), ("custom", "Custom color")]
QUALITY_CHOICES = [("fast", "Fast"), ("normal", "Normal"), ("high", "High")]
VIEW_CHOICES = [("result", "Result"), ("matte", "Matte (white = kept)"), ("edge", "Edge zone")]

_COLOR_ONLY = {"color", "tolerance", "softness", "spill"}
_OBJECT_ONLY = {"quality"}


def visible_params(e, params):
    """The parameter rows the card shows for the mode / edge setting this effect layer has now."""
    p = (e or {}).get("p") or {}; mode = p.get("mode", "color"); out = []
    for prm in params:
        k = prm[0]
        if mode == "object" and k in _COLOR_ONLY: continue
        if mode != "object" and k in _OBJECT_ONLY: continue
        if k == "edge_color" and p.get("edge_mode", "auto") != "custom": continue
        if k in ("edge_width", "edge_amount") and p.get("edge_mode", "auto") == "off": continue
        out.append(prm)
    return out


# ============================================================================================ small helpers
def _hex_bgr(s):
    s = str(s or "#00ff00").lstrip("#")
    if len(s) == 8: s = s[2:]                                  # Qt's #AARRGGBB
    try: return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))
    except Exception: return (0, 255, 0)


def _smooth(x):
    x = np.clip(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x)


def _ell(n):
    n = max(1, int(n)); return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * n + 1, 2 * n + 1))


def _blur(a, sigma):
    """Gaussian blur; a big sigma runs on a shrunken copy (the result is smooth anyway)."""
    if sigma < 0.3: return a
    if sigma < 4.0: return cv2.GaussianBlur(a, (0, 0), sigma)
    h, w = a.shape[:2]; f = int(min(8, max(2, sigma / 2.0))); sw, sh = max(1, w // f), max(1, h // f)
    sm = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), max(0.3, sigma / f))
    return cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR)


def _box(x, r):
    r = max(1, int(r)); return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REPLICATE)


# ============================================================================================ 1) live: background colour
def key_matte(bgr, p):
    """Soft matte (float 0..1, 1 = keep) from the distance of the chroma (Cb, Cr) to the chroma of the key colour.
    Using the chroma only means a shadow or a bright spot on the screen is still the screen."""
    key = _hex_bgr(p["color"])
    ycc = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2YCrCb).astype(np.float32)
    kyc = cv2.cvtColor(np.uint8([[key]]), cv2.COLOR_BGR2YCrCb)[0, 0].astype(np.float32)
    d = cv2.magnitude(ycc[..., 1] - kyc[1], ycc[..., 2] - kyc[2])
    t0 = float(p["tolerance"]) * 1.1 + 1.5; wd = 1.5 + float(p["softness"]) * 1.1
    return _smooth((d - t0) / wd)


def despill(bgr, key_bgr, amount):
    """Take the key colour out of the subject (green light bounced onto skin and hair). The strongest channel(s) of the key colour
    may not be stronger than the average of the others; `amount` 0..1 says how much of that is applied."""
    if amount <= 0: return bgr
    kd = np.asarray(key_bgr, np.float32) / 255.0; mx = float(kd.max())
    if mx < 0.12: return bgr
    dom = [i for i in range(3) if kd[i] >= 0.7 * mx]; oth = [i for i in range(3) if i not in dom]
    if not oth: return bgr                                      # a white key: nothing to say about it
    lim = bgr[..., oth[0]] if len(oth) == 1 else (bgr[..., oth[0]] + bgr[..., oth[1]]) * 0.5
    out = bgr.copy()
    for i in dom: out[..., i] = bgr[..., i] + (np.minimum(bgr[..., i], lim) - bgr[..., i]) * amount
    return out


def post_matte(A, choke, feather, k):
    """Shrink (+) or grow (-) the edge, then feather it. Sizes are in layer pixels; k scales them to the picture on screen."""
    r = float(choke) * k
    if abs(r) >= 0.5:
        ker = _ell(int(round(abs(r)))); A = cv2.erode(A, ker) if r > 0 else cv2.dilate(A, ker)
    f = float(feather) * k
    if f > 0.3: A = _blur(A, f * 0.5)
    return A


def edge_zone(A, width_px):
    """0..1: how much a pixel belongs to the rim of the subject: every partly see-through pixel and `width_px` pixels inside."""
    n = max(1, int(round(width_px))); solid = (A > 0.97).astype(np.uint8)
    inner = cv2.erode(solid, _ell(n)); ring = (solid - inner).astype(np.float32)
    partial = ((A > 0.004) & (A <= 0.97)).astype(np.float32)
    z = np.maximum(ring, partial); z = _blur(z, max(0.7, width_px * 0.35))
    return np.clip(z * 1.6, 0.0, 1.0), inner


def edge_color(col, A, p, k):
    """Repaint the rim of the subject. Returns (colour, zone weight)."""
    mode = p.get("edge_mode", "auto"); amt = float(p.get("edge_amount", 70.0)) / 100.0; wpx = float(p.get("edge_width", 3.0)) * k
    if mode == "off" or amt <= 0 or wpx <= 0.0: return col, None
    z, inner = edge_zone(A, wpx); w = (z * amt)[..., None]
    if mode == "custom":
        ec = np.empty_like(col); ec[...] = np.asarray(_hex_bgr(p.get("edge_color", "#303030")), np.float32)
    else:
        core = inner.astype(np.float32)
        if core.max() <= 0: core = (A > 0.97).astype(np.float32)
        if core.max() <= 0: return col, z
        sig = max(3.0, wpx * 2.0 + 3.0); num = _blur(col * core[..., None], sig); den = _blur(core, sig)[..., None]
        ec = np.where(den > 1e-3, num / np.maximum(den, 1e-3), col)
    return col + (ec - col) * w, z


def fx_smart_key(img, p, ctx):
    """The effect function (BGRA in, BGRA out). In 'object' mode the matte comes with the rendered media (see bake()); what this function
    does then is only the live finishing: shrink / grow, feather and the edge colour."""
    k = float(getattr(ctx, "k", 1.0) or 1.0); mode = p.get("mode", "color"); view = p.get("view", "result")
    a_in = img[..., 3]; bgr = img[..., :3].astype(np.float32)
    if mode == "object":
        if cv2.minMaxLoc(a_in)[0] >= 255: return img                  # nothing rendered (yet): the picture is left alone
        A = a_in.astype(np.float32) * (1.0 / 255.0); col = bgr
    else:
        A = key_matte(img[..., :3], p) * (a_in.astype(np.float32) * (1.0 / 255.0))
        col = despill(bgr, _hex_bgr(p["color"]), float(p.get("spill", 60.0)) / 100.0)
    A = post_matte(A, p.get("choke", 0.0), p.get("feather", 0.0), k)
    col, zone = edge_color(col, A, p, k)
    out = np.empty_like(img)
    if view == "matte" or view == "edge":
        g = A if view == "matte" else (zone if zone is not None else edge_zone(A, max(1.0, float(p.get("edge_width", 3.0)) * k))[0])
        g8 = np.clip(g * 255.0 + 0.5, 0, 255).astype(np.uint8); out[..., 0] = out[..., 1] = out[..., 2] = g8; out[..., 3] = 255; return out
    out[..., :3] = np.clip(col + 0.5, 0, 255).astype(np.uint8); out[..., 3] = np.clip(A * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


# ============================================================================================ 2) object: segmentation
def raster_strokes(strokes, w, h, kind):
    """Strokes ({"k": "fg" | "bg", "r": radius as a part of the width, "pts": [[x, y], ...] as parts of the size}) -> 0 / 255 picture."""
    m = np.zeros((h, w), np.uint8)
    for s in strokes or ():
        if s.get("k") != kind: continue
        pts = np.asarray(s.get("pts") or [], np.float64)
        if pts.size == 0: continue
        pts = pts.reshape(-1, 2) * np.array([w, h], np.float64); ip = np.round(pts).astype(np.int32)
        rad = max(1, int(round(float(s.get("r", 0.01)) * w)))
        if len(ip) > 1: cv2.polylines(m, [ip.reshape(-1, 1, 2)], False, 255, 2 * rad + 1, cv2.LINE_8)
        for q in ip: cv2.circle(m, (int(q[0]), int(q[1])), rad, 255, -1)
    return m


def _kmeans(samples, k):
    n = len(samples)
    if n > 4000: samples = samples[np.random.default_rng(1).choice(n, 4000, replace=False)]
    k = max(1, min(k, len(samples)))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, lab, cen = cv2.kmeans(samples.astype(np.float32), k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    lab = lab.ravel(); rad = np.zeros(k, np.float32)
    for i in range(k):
        s = samples[lab == i]
        rad[i] = (np.percentile(np.linalg.norm(s - cen[i], axis=1), 90) if len(s) else 0.0)
    return cen, np.maximum(rad, 7.0) + 4.0


def _model_dist(lab, cen, rad):
    """min over the colour clusters of (distance / cluster radius): below 1 = looks like the painted colours."""
    best = None
    for c, r in zip(cen, rad):
        d = np.sqrt(((lab - c) ** 2).sum(-1)) / r; best = d if best is None else np.minimum(best, d)
    return best


def _clean(mask, ref, strict):
    """Drop little islands that have nothing to do with the object, fill little holes."""
    m = mask.astype(np.uint8); n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n > 2:
        area = st[1:, cv2.CC_STAT_AREA].astype(np.float64); big = area.max() if len(area) else 0
        ov = np.bincount(lab[ref], minlength=n)[1:].astype(np.float64) if ref.any() else np.zeros(n - 1)
        keep = np.zeros(n, bool)
        for i in range(n - 1):
            a = area[i]
            keep[i + 1] = (ov[i] > (0.2 * a if strict else 0)) or (a >= 0.25 * big)
        m = keep[lab].astype(np.uint8)
    H, W = m.shape; inv = (1 - m).astype(np.uint8); n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    lim = 0.002 * H * W
    for i in range(1, n2):
        x, y, w, h, a = st2[i]
        if a < lim and x > 0 and y > 0 and x + w < W and y + h < H: m[lab2 == i] = 1
    return m.astype(bool)


def _grabcut(sm, labels, iters):
    mask = labels.copy()
    if not (mask == 0).any(): mask[0, :] = 0; mask[-1, :] = 0; mask[:, 0] = 0; mask[:, -1] = 0
    if not ((mask == 1) | (mask == 3)).any(): return mask
    bg = np.zeros((1, 65), np.float64); fg = np.zeros((1, 65), np.float64)
    try: cv2.grabCut(sm, mask, None, bg, fg, int(iters), cv2.GC_INIT_WITH_MASK)
    except cv2.error: return labels
    return mask


def init_labels(sm, fg, bg):
    """GrabCut labels (0 sure background, 1 sure object, 2 probably background, 3 probably object) from the painted strokes.
    The colours of the object strokes decide which pixels may belong to the object."""
    H, W = fg.shape; lab = cv2.cvtColor(sm, cv2.COLOR_BGR2LAB).astype(np.float32)
    fgb = fg > 0; bgb = bg > 0
    cen, rad = _kmeans(lab[fgb], 5) if fgb.sum() >= 3 else _kmeans(np.zeros((3, 3), np.float32), 1)
    dist = _model_dist(lab, cen, rad)
    ys, xs = np.nonzero(fgb)
    x0, x1, y0, y1 = (xs.min(), xs.max(), ys.min(), ys.max()) if len(xs) else (0, W - 1, 0, H - 1)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1; mx = int(max(0.5 * bw, 0.06 * W)); my = int(max(0.5 * bh, 0.06 * H))
    far = np.ones((H, W), bool); far[max(0, y0 - my):y1 + my + 1, max(0, x0 - mx):x1 + mx + 1] = False      # outside the painted area, widened
    like = (dist < 1.25).astype(np.uint8); n, cl = cv2.connectedComponents(like, connectivity=8)
    touch = np.unique(cl[fgb]); touch = touch[touch > 0]; conn = np.isin(cl, touch)
    labels = np.full((H, W), 2, np.uint8)
    labels[conn] = 3
    labels[far & (dist > 2.0)] = 0
    labels[fgb] = 1; labels[bgb] = 0
    return labels


class Tracker:
    """Finds the object on a seed picture and follows it frame after frame (all at a reduced size)."""
    def __init__(self, W, H, quality="normal"):
        long = QUALITY.get(quality, 512); self.W, self.H = W, H; self.s = min(1.0, long / float(max(W, H)))
        self.sw = max(16, int(round(W * self.s))); self.sh = max(16, int(round(H * self.s)))
        self.prev_gray = None; self.prev_alpha = None
    def small(self, bgr):
        if bgr.shape[1] == self.sw and bgr.shape[0] == self.sh: return bgr
        return cv2.resize(bgr, (self.sw, self.sh), interpolation=cv2.INTER_AREA)
    def set_state(self, sm, alpha): self.prev_gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY); self.prev_alpha = alpha.astype(np.float32)
    def seed(self, sm, strokes):
        fg = raster_strokes(strokes, self.sw, self.sh, "fg"); bg = raster_strokes(strokes, self.sw, self.sh, "bg")
        m = _grabcut(sm, init_labels(sm, fg, bg), 6)
        fgm = _clean((m == 1) | (m == 3), fg > 0, False)
        fgm[fg > 0] = True; fgm[(bg > 0) & ~(fg > 0)] = False
        a = cv2.GaussianBlur(fgm.astype(np.float32), (0, 0), 1.0); self.set_state(sm, a); return a
    def _motion(self, g):
        """How the object moved from the previous picture to this one: a similarity transform (2x3) from tracked corners inside the object
        (outliers thrown out), and how far the tracked points stay from that model (the part of the motion it cannot explain)."""
        H, W = g.shape; I = np.float32([[1, 0, 0], [0, 1, 0]])
        inside = cv2.erode((self.prev_alpha > 0.5).astype(np.uint8), _ell(2)) * 255
        pts = cv2.goodFeaturesToTrack(self.prev_gray, 250, 0.008, 3, mask=inside)
        if pts is not None and len(pts) >= 6:
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.prev_gray, g, pts, None, winSize=(21, 21), maxLevel=4)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(g, self.prev_gray, nxt, None, winSize=(21, 21), maxLevel=4)
            ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((back - pts).reshape(-1, 2), axis=1) < 1.0)
            if ok.sum() >= 6:
                p0 = pts.reshape(-1, 2)[ok]; p1 = nxt.reshape(-1, 2)[ok]
                M, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                if M is not None:
                    pr = p0 @ M[:, :2].T + M[:, 2]; res = np.linalg.norm(pr - p1, axis=1)
                    return M.astype(np.float32), float(np.percentile(res, 90)) if len(res) else 0.0
        flow = cv2.calcOpticalFlowFarneback(self.prev_gray, g, None, 0.5, 4, 21, 3, 5, 1.1, 0)     # too few corners: the dense flow, as a plain shift
        m = self.prev_alpha > 0.5; mag = np.hypot(flow[..., 0], flow[..., 1])[m]
        if len(mag) == 0: return I, 2.0
        hi = mag >= np.percentile(mag, 60)
        I[0, 2] = float(np.median(flow[..., 0][m][hi])); I[1, 2] = float(np.median(flow[..., 1][m][hi])); return I, 2.0
    def step(self, sm):
        g = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY); H, W = g.shape
        M, spread = self._motion(g)
        warped = cv2.warpAffine(self.prev_alpha, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        fgw = warped > 0.5; area = int(fgw.sum())
        if area < 12:
            self.prev_gray = g; self.prev_alpha = warped; return warped
        r_out = int(np.clip(round(2.0 + 1.5 * spread + 0.002 * max(W, H)), 2, 12)); r_in = r_out + 1       # the band covers what the motion model cannot explain
        u8 = fgw.astype(np.uint8); sure_fg = cv2.erode(u8, _ell(r_in)); dil = cv2.dilate(u8, _ell(r_out))
        labels = np.where(fgw, 3, 2).astype(np.uint8); labels[sure_fg > 0] = 1; labels[dil == 0] = 0
        ys, xs = np.nonzero(dil); pad = 8
        x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + pad + 1); y0, y1 = max(0, ys.min() - pad), min(H, ys.max() + pad + 1)
        sub = _grabcut(np.ascontiguousarray(sm[y0:y1, x0:x1]), np.ascontiguousarray(labels[y0:y1, x0:x1]), 3)
        new = np.zeros((H, W), bool); new[y0:y1, x0:x1] = (sub == 1) | (sub == 3)
        new = _clean(new, fgw, True); na = int(new.sum())
        if na < 0.7 * area or na > 1.3 * area: new = fgw                         # the cut went wrong: keep what the motion says
        a = cv2.GaussianBlur(new.astype(np.float32), (0, 0), 1.0)
        a = a * 0.8 + warped * 0.2
        self.prev_gray = g; self.prev_alpha = a; return a


# ---------------------------------------------------------------------------------------------- refinement at full size
def guided_filter(I, p, r, eps):
    """Colour guided filter (He et al.): p follows the edges of the picture I (float32 HxWx3, 0..1)."""
    mi = [_box(I[..., c], r) for c in range(3)]; mp = _box(p, r)
    cov = [_box(I[..., c] * p, r) - mi[c] * mp for c in range(3)]
    def v(i, j): return _box(I[..., i] * I[..., j], r) - mi[i] * mi[j]
    s00, s01, s02, s11, s12, s22 = v(0, 0) + eps, v(0, 1), v(0, 2), v(1, 1) + eps, v(1, 2), v(2, 2) + eps
    c00 = s11 * s22 - s12 * s12; c01 = s02 * s12 - s01 * s22; c02 = s01 * s12 - s02 * s11
    c11 = s00 * s22 - s02 * s02; c12 = s01 * s02 - s00 * s12; c22 = s00 * s11 - s01 * s01
    inv_det = 1.0 / np.maximum(s00 * c00 + s01 * c01 + s02 * c02, 1e-12)
    a0 = (c00 * cov[0] + c01 * cov[1] + c02 * cov[2]) * inv_det
    a1 = (c01 * cov[0] + c11 * cov[1] + c12 * cov[2]) * inv_det
    a2 = (c02 * cov[0] + c12 * cov[1] + c22 * cov[2]) * inv_det
    b = mp - a0 * mi[0] - a1 * mi[1] - a2 * mi[2]
    return _box(a0, r) * I[..., 0] + _box(a1, r) * I[..., 1] + _box(a2, r) * I[..., 2] + _box(b, r)


def _blur_fusion(img, F, B, a, r):
    a3 = a[..., None]
    den_f = _box(a, r)[..., None]; den_b = _box(1.0 - a, r)[..., None]
    fh = np.where(den_f > 1e-3, _box(F * a3, r) / np.maximum(den_f, 1e-3), img)
    bh = np.where(den_b > 1e-3, _box(B * (1.0 - a3), r) / np.maximum(den_b, 1e-3), img)
    Fn = fh + a3 * (img - a3 * fh - (1.0 - a3) * bh)
    return np.clip(Fn, 0.0, 255.0), bh


def refine(full_bgr, coarse, small_scale):
    """The coarse mask (float 0..1 at the reduced size) -> (colour BGR uint8, alpha uint8) at the full size: the edge is moved onto the
    real edge of the picture, and the background colour is taken out of the edge pixels (the colour is made from the subject's own)."""
    H, W = full_bgr.shape[:2]; rs = min(1.0, 1280.0 / max(H, W))
    g = full_bgr if rs >= 0.999 else cv2.resize(full_bgr, (max(2, int(round(W * rs))), max(2, int(round(H * rs)))), interpolation=cv2.INTER_AREA)
    gh, gw = g.shape[:2]
    a0 = np.clip(cv2.resize(coarse, (gw, gh), interpolation=cv2.INTER_CUBIC), 0.0, 1.0)
    br = max(3, int(round(3.0 * rs / small_scale))); r = max(3, int(round(br * 0.7)))
    q = guided_filter(g.astype(np.float32) * (1.0 / 255.0), a0.astype(np.float32), r, 1e-3)
    b = (a0 > 0.5).astype(np.uint8); inner = cv2.erode(b, _ell(br)); outer = cv2.dilate(b, _ell(br))
    q = np.where(inner > 0, 1.0, q); q = np.where(outer > 0, q, 0.0)
    q = _smooth((q - 0.08) / 0.84).astype(np.float32)
    gf = g.astype(np.float32); m = max(gh, gw)
    F, Bh = _blur_fusion(gf, gf, gf, q, max(8, int(round(0.05 * m))))
    F, _ = _blur_fusion(gf, F, Bh, q, max(3, int(round(0.006 * m))))
    if gw != W or gh != H:
        qf = np.clip(cv2.resize(q, (W, H), interpolation=cv2.INTER_CUBIC), 0.0, 1.0)
        Ff = cv2.resize(F, (W, H), interpolation=cv2.INTER_LINEAR); t = np.clip((qf - 0.9) / 0.1, 0.0, 1.0)[..., None]
        col = Ff + (full_bgr.astype(np.float32) - Ff) * t
    else:
        qf = q; t = np.clip((q - 0.9) / 0.1, 0.0, 1.0)[..., None]; col = F + (gf - F) * t
    return np.clip(col + 0.5, 0, 255).astype(np.uint8), np.clip(qf * 255.0 + 0.5, 0, 255).astype(np.uint8)


def segment_still(bgr, strokes, quality="normal"):
    """One picture -> (colour, alpha uint8) at the full size. Used for pictures and for the preview in the paint window."""
    H, W = bgr.shape[:2]; tr = Tracker(W, H, quality); a = tr.seed(tr.small(bgr), strokes)
    return refine(bgr, a, tr.s)


# ============================================================================================ rendering to a file
def _pack(col, alpha, ph):
    H, W = alpha.shape; out = np.empty((ph, W * 2, 3), np.uint8)
    out[:H, :W] = col; out[:H, W:, 0] = out[:H, W:, 1] = out[:H, W:, 2] = alpha
    if ph > H: out[H:] = out[H - 1:H]
    return out


class _Encoder:
    def __init__(self, out, W, H, fps, audio_src):
        self.ph = H + (H & 1); self.err = tempfile.TemporaryFile()
        cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (W * 2, self.ph), "-r", "%.6f" % fps, "-i", "-"]
        if audio_src: cmd += ["-i", audio_src]
        cmd += ["-map", "0:v:0"] + (["-map", "1:a:0?"] if audio_src else [])
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-g", "1", "-pix_fmt", "yuv420p"]
        if audio_src: cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-movflags", "+faststart", "-f", "mp4", out]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self.err, creationflags=NOWIN)
    def write(self, packed):
        try: self.p.stdin.write(np.ascontiguousarray(packed).data)
        except (BrokenPipeError, OSError): raise RuntimeError("the video encoder stopped: " + self.error_text())
    def error_text(self):
        try: self.err.seek(0); return self.err.read().decode("utf-8", "ignore")[-600:]
        except Exception: return ""
    def close(self):
        try: self.p.stdin.close()
        except Exception: pass
        rc = self.p.wait()
        if rc != 0: raise RuntimeError("the video encoder failed: " + self.error_text())
    def kill(self):
        try: self.p.kill()
        except Exception: pass
        try: self.p.stdin.close()
        except Exception: pass
        try: self.p.wait(5)
        except Exception: pass


class Cancelled(Exception): pass


def read_source_frame(path, kind, ts):
    """(BGR picture, frame index, fps) of the original media at source time ts."""
    if kind == "image":
        from ..shared.core import imread_any
        im = imread_any(path)
        if im is None: raise IOError("cannot open " + path)
        if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        elif im.shape[2] == 4:                                       # over grey, so the painter sees what it can see
            a = im[..., 3:4].astype(np.float32) / 255.0; im = (im[..., :3] * a + 128 * (1 - a)).astype(np.uint8)
        return im, 0, 1.0
    cap = cv2.VideoCapture(safe_path(path))
    if not cap.isOpened(): raise IOError("cannot open " + path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        idx = max(0, int(round(max(0.0, ts) * fps)))
        if n > 0: idx = min(idx, n - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx); ok, fr = cap.read()
        if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, fr = cap.read(); idx = 0
        if not ok: raise IOError("cannot read " + path)
        return fr, idx, float(fps)
    finally: cap.release()


def _group_seeds(strokes, i0, i1, n):
    seeds = {}
    for s in strokes or ():
        f = max(0, min(n - 1, int(s.get("f", 0)))); seeds.setdefault(f, []).append(s)
    return {f: v for f, v in seeds.items() if any(x.get("k") == "fg" for x in v)}


def bake(path, kind, strokes, quality, out_file, span=None, progress=None, cancel=None):
    """Render the media into out_file (see the top of this file). span = (first, last) source seconds the clip uses, or None for all.
    progress(fraction, text) is called often; cancel() returns True to stop. Returns a dict with what the clip needs to remember."""
    prog = progress or (lambda f, t="": None); stop = cancel or (lambda: False)
    os.makedirs(CACHE_DIR, exist_ok=True); prune_cache(keep=out_file)
    if kind == "image": return _bake_image(path, strokes, quality, out_file, prog)
    cap = cv2.VideoCapture(safe_path(path))
    if not cap.isOpened(): raise IOError("cannot open " + path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if n <= 0:
        from ..shared.core import ffprobe_dur
        n = max(1, int((ffprobe_dur(path) or 0) * fps))
    seeds = _group_seeds(strokes, 0, n - 1, n)
    if not seeds: cap.release(); raise ValueError("paint the object first")
    if span is None or n / fps <= FULL_LIMIT_S: i0, i1 = 0, n - 1; full = True
    else:
        i0 = max(0, int((span[0] - MARGIN_S) * fps)); i1 = min(n - 1, int(math.ceil((span[1] + MARGIN_S) * fps))); full = False
        i0 = min(i0, min(seeds)); i1 = max(i1, max(seeds))
    cnt = i1 - i0 + 1; tr = Tracker(W, H, quality); work = tempfile.mkdtemp(prefix="work_", dir=CACHE_DIR); enc = None; tmp_out = out_file + ".part"
    try:
        # pass 0: the whole range at the reduced size, so the object can be followed in both directions
        smalls = np.memmap(os.path.join(work, "s.bin"), np.uint8, "w+", shape=(cnt, tr.sh, tr.sw, 3))
        alphas = np.memmap(os.path.join(work, "a.bin"), np.uint8, "w+", shape=(cnt, tr.sh, tr.sw))
        cap.set(cv2.CAP_PROP_POS_FRAMES, i0); got = 0
        for j in range(cnt):
            if stop(): raise Cancelled()
            ok, fr = cap.read()
            if not ok: break
            smalls[j] = tr.small(fr); got += 1
            if j % 8 == 0: prog(0.08 * j / cnt, "Reading frames")
        cap.release()
        if got < 1: raise IOError("no frames could be read")
        cnt = got; i1 = i0 + cnt - 1
        # pass 1: follow the object from every seed, to the middle between two seeds
        sj = sorted(f - i0 for f in seeds if 0 <= f - i0 < cnt); seed_a = {}
        for j in sj:
            seed_a[j] = tr.seed(np.asarray(smalls[j]), seeds[j + i0]); alphas[j] = np.clip(seed_a[j] * 255 + 0.5, 0, 255).astype(np.uint8)
        done = 0
        def sweep(j0, rng):
            nonlocal done
            tr.set_state(np.asarray(smalls[j0]), seed_a[j0])
            for j in rng:
                if stop(): raise Cancelled()
                a = tr.step(np.asarray(smalls[j])); alphas[j] = np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8); done += 1
                if done % 3 == 0: prog(0.08 + 0.57 * min(1.0, done / float(max(1, cnt - len(sj)))), "Following the object")
        for k, j0 in enumerate(sj):
            end = (j0 + sj[k + 1]) // 2 if k + 1 < len(sj) else cnt - 1
            start = (sj[k - 1] + j0 + 1) // 2 if k > 0 else 0
            if end > j0: sweep(j0, range(j0 + 1, end + 1))
            if start < j0: sweep(j0, range(j0 - 1, start - 1, -1))
        # pass 2: full size, edge refinement, encode
        audio = path if _has_audio(path) else None
        enc = _Encoder(tmp_out, W, H, fps, audio); ph = enc.ph
        cap = cv2.VideoCapture(safe_path(path)); pend = deque(); total = n; written = 0
        def one(fr, a8):
            col, al = refine(fr, a8.astype(np.float32) * (1.0 / 255.0), tr.s); return _pack(col, al, ph)
        def outside(fr): return _pack(fr, np.zeros((H, W), np.uint8), ph)
        with ThreadPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2)))) as ex:
            for idx in range(n):
                if stop(): raise Cancelled()
                ok, fr = cap.read()
                if not ok: break
                if i0 <= idx <= i1: pend.append(ex.submit(one, fr, np.array(alphas[idx - i0])))
                else: pend.append(ex.submit(outside, fr))
                while len(pend) >= 8:
                    enc.write(pend.popleft().result()); written += 1
                if idx % 4 == 0: prog(0.65 + 0.35 * idx / float(total), "Rendering the edge")
            while pend: enc.write(pend.popleft().result()); written += 1
        cap.release(); enc.close(); enc = None
        if written < 1: raise IOError("nothing was written")
        with open(out_file + ".json", "w", encoding="utf-8") as f: json.dump({"w": W, "h": H, "fps": fps, "n": written, "ver": SK_VER, "span": None if full else [i0 / fps, i1 / fps]}, f)
        os.replace(tmp_out, out_file); prog(1.0, "Done")
        return {"file": out_file, "span": None if full else [i0 / fps, i1 / fps], "frames": written, "t": time.time(), "w": W, "h": H}
    except BaseException:
        if enc is not None: enc.kill()
        try: os.remove(tmp_out)
        except OSError: pass
        raise
    finally:
        try: cap.release()
        except Exception: pass
        try: del smalls, alphas
        except Exception: pass
        shutil.rmtree(work, ignore_errors=True)


def _has_audio(path):
    try:
        p = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True, errors="ignore", creationflags=NOWIN)
        return "Audio:" in p.stderr
    except Exception: return False


def _bake_image(path, strokes, quality, out_file, prog):
    from ..shared.core import imread_any
    im = imread_any(path)
    if im is None: raise IOError("cannot open " + path)
    alpha0 = None
    if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    elif im.shape[2] == 4: alpha0 = im[..., 3]; im = im[..., :3]
    if not _group_seeds(strokes, 0, 0, 1): raise ValueError("paint the object first")
    prog(0.1, "Finding the object"); col, al = segment_still(np.ascontiguousarray(im), [dict(s, f=0) for s in strokes], quality)
    if alpha0 is not None: al = (al.astype(np.uint16) * alpha0 // 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", cv2.merge([col[..., 0], col[..., 1], col[..., 2], al]))
    if not ok: raise IOError("could not write the picture")
    tmp = out_file + ".part"; buf.tofile(tmp); os.replace(tmp, out_file); prog(1.0, "Done")
    return {"file": out_file, "span": None, "frames": 1, "t": time.time(), "w": im.shape[1], "h": im.shape[0]}


def prune_cache(keep=None):
    """Keep the render folder under CACHE_MAX_BYTES (oldest first). A render that is gone is simply not used: the original media plays."""
    try:
        files = []
        for nm in os.listdir(CACHE_DIR):
            fp = os.path.join(CACHE_DIR, nm)
            if os.path.isfile(fp) and nm.endswith((".mckey.mp4", ".mckey.png")): files.append((os.path.getmtime(fp), fp, os.path.getsize(fp)))
        tot = sum(s for _, _, s in files)
        for _, fp, s in sorted(files):
            if tot <= CACHE_MAX_BYTES: break
            if fp == keep: continue
            for x in (fp, fp + ".json"):
                try: os.remove(x)
                except OSError: pass
            tot -= s
    except Exception: pass


# ============================================================================================ which media a clip uses
class PackedAlphaSource:
    """A rendered clip: colour on the left half of every frame, the matte on the right half (an all-intra H.264 file, so any frame can be read at once)."""
    has_alpha = True
    def __init__(self, path):
        with open(path + ".json", "r", encoding="utf-8") as f: m = json.load(f)
        self.path = path; self.w = int(m["w"]); self.h = int(m["h"]); self.fps = float(m["fps"]) or 30.0; self.n = int(m["n"])
        self.cap = cv2.VideoCapture(safe_path(path))
        if not self.cap.isOpened(): raise IOError("cannot open " + path)
        self._pos = -2; self._lock = threading.RLock(); self.cache = OrderedDict()
    def _read(self, idx):
        with self._lock:
            if idx != self._pos + 1: self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = self.cap.read()
            self._pos = idx if ok else -2
            return fr if ok else None
    def frame(self, t, ds=1.0):
        idx = max(0, int(max(0.0, t) * self.fps + 1e-6))
        if self.n > 0: idx = min(idx, self.n - 1)
        key = (idx, round(ds, 3)); hit = self.cache.get(key)
        if hit is not None: self.cache.move_to_end(key); return hit
        fr = self._read(idx)
        if fr is None: img = np.zeros((self.h, self.w, 4), np.uint8)
        else: img = cv2.merge([fr[:self.h, :self.w, 0], fr[:self.h, :self.w, 1], fr[:self.h, :self.w, 2], fr[:self.h, self.w:2 * self.w, 0]])
        if ds < 0.999: img = cv2.resize(img, (max(1, int(self.w * ds)), max(1, int(self.h * ds))), interpolation=cv2.INTER_AREA)
        self.cache[key] = img
        while len(self.cache) > 24: self.cache.popitem(last=False)
        return img
    def raw_frame(self, t): return np.ascontiguousarray(self.frame(t)[..., :3])
    def frame_bgr(self, t, ds=1.0): return np.ascontiguousarray(self.frame(t, ds)[..., :3])
    def close(self):
        with self._lock:
            try: self.cap.release()
            except Exception: pass
        self.cache.clear()


def sk_effect(c):
    """The Better Chroma Key layer of the clip that works in 'object' mode and is on, or None."""
    for e in (c.get("effects") or ()):
        if e.get("type") == "smart_key" and e.get("on", True) and (e.get("p") or {}).get("mode") == "object": return e
    return None


def sig_of(c, e):
    """What a render depends on: the file, the painted strokes and the quality (not the clip's trim, the live finishing or the other effects)."""
    p = c.get("path") or ""
    try: st = os.stat(safe_path(p)); fs = [st.st_size, int(st.st_mtime)]
    except OSError: fs = None
    d = json.dumps([SK_VER, p, fs, c.get("kind"), e.get("strokes") or [], (e.get("p") or {}).get("quality", "normal")], sort_keys=True, default=str)
    return hashlib.sha1(d.encode("utf-8", "replace")).hexdigest()[:20]


def out_path_for(c, e):
    return os.path.join(CACHE_DIR, sig_of(c, e) + (".mckey.png" if c.get("kind") == "image" else ".mckey.mp4"))


def cached_info(c, e):
    """The info of a render that already exists for the current paint (e.g. the effect was switched off and on again), or None."""
    out = out_path_for(c, e)
    if not os.path.exists(out): return None
    if c.get("kind") == "image": return {"file": out, "span": None, "frames": 1, "t": time.time()}
    try:
        with open(out + ".json", "r", encoding="utf-8") as f: m = json.load(f)
        return {"file": out, "span": m.get("span"), "frames": int(m.get("n", 1)), "t": time.time(), "w": m.get("w"), "h": m.get("h")}
    except Exception: return None


def used_span(c):
    dur = max(0.01, float(c.get("dur", 1.0))); ts = [src_time(c, dur * i / 32.0) for i in range(33)]
    return min(ts), max(ts)


def state_of(c, e):
    """('none' | 'ready' | 'stale' | 'short', text) for the card: no render yet / the render is used / the paint changed since / the clip now uses frames
    outside the part that was rendered."""
    b = e.get("bake")
    if not any(s.get("k") == "fg" for s in (e.get("strokes") or [])): return "none", "Paint the object first"
    if not isinstance(b, dict) or not b.get("file"): return "none", "Not rendered yet"
    if not os.path.exists(b["file"]): return "stale", "The render file is gone. Render again"
    if b.get("sig") != sig_of(c, e): return "stale", "The paint or quality changed. Render again"
    sp = b.get("span")
    if sp and c.get("kind") == "video":
        lo, hi = used_span(c)
        if lo < sp[0] - 1e-3 or hi > sp[1] + 1e-3: return "short", "The clip now shows frames that were not rendered. Render again"
    return "ready", "Rendered (%d frame%s). This render is used instead of the original media" % (b.get("frames", 1), "" if b.get("frames", 1) == 1 else "s")


def sk_path(c):
    """The rendered file the clip should use instead of its media, or None (use the original). Cheap enough to call for every frame."""
    try:
        if c.get("kind") not in ("video", "image"): return None
        e = sk_effect(c)
        if e is None or not isinstance(e.get("bake"), dict): return None
        return e["bake"]["file"] if state_of(c, e)[0] == "ready" else None
    except Exception: return None

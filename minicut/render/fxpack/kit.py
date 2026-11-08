"""Tool box for the effect pack: noise, remapping, colour helpers, blending of generated pictures, time helpers.
Every effect works on an 8-bit BGRA picture (h, w, 4). Sizes in the parameters are in layer pixels: S(ctx, v) turns them into
picture pixels, so the small preview looks like the export."""
from ...shared.deps import *
from ..effects import register as _register, _premul, _unpremul, _gauss, blur_bgra, ref_size, ref_crop, ref_origin

_GRID = {}
_NZ = OrderedDict()


# ------------------------------------------------------------------ parameter shortcuts
def F(key, label, d, lo, hi): return (key, label, "float", float(d), float(lo), float(hi))
def I(key, label, d, lo, hi): return (key, label, "int", int(d), int(lo), int(hi))
def C(key, label, d): return (key, label, "color", d, None, None)
def B(key, label, d): return (key, label, "bool", bool(d), None, None)
def CH(key, label, d, opts): return (key, label, "choice", d, list(opts), None)


def reg(type_, cat, title, params, fn, help="", kw="", area=False):
    _register(type_, cat, title, params, fn, area=area, help=help, kw=kw)


MODES = [("over", "Over the picture"), ("behind", "Behind the picture"), ("replace", "Replace the picture"), ("add", "Add (light)"), ("screen", "Screen"), ("multiply", "Multiply"), ("overlay", "Overlay")]


def MODE(d="over"): return CH("mode", "Blend", d, MODES)
def OPAC(d=100): return F("opacity", "Opacity", d, 0, 100)
def SEED(d=1): return I("seed", "Seed", d, 0, 999)
def SPEED(d=1.0, hi=10): return F("speed", "Speed", d, 0, hi)


# ------------------------------------------------------------------ geometry and time
def S(ctx, v): return max(1.0, float(v) * ctx.k)
def coords(h, w):
    """x, y in picture pixels (float32, h x w)."""
    key = (h, w); g = _GRID.get(key)
    if g is None:
        g = np.mgrid[0:h, 0:w].astype(np.float32)[::-1]; _GRID.clear() if len(_GRID) > 6 else None; _GRID[key] = g
    return g[0], g[1]
def norm_coords(h, w, cx=0.5, cy=0.5):
    """x, y centred at (cx, cy) (fractions) and scaled so that the picture height is 1 (aspect kept)."""
    x, y = coords(h, w); rh = ref_size(h, w)[0]; return (x - w * cx) / rh, (y - h * cy) / rh
def rng(ctx, seed=0, rate=12.0):
    """A random generator that changes `rate` times a second (the same time gives the same numbers)."""
    return np.random.default_rng((int(seed) * 7919 + int(ctx.lt * rate) * 104729) & 0xFFFFFFFF)
def prog(p, ctx, key="progress"):
    """0..1 wipe progress. An explicit Progress keyframe track wins over auto-run.
    Otherwise `anim` runs the effect over its duration after `delay` seconds."""
    a = p.get("anim", 0.0)
    keyed = bool(getattr(ctx, "progress_keyframed", False)) and key == "progress"
    v = (np.clip((ctx.lt - p.get("delay", 0.0)) / a, 0, 1)
         if a > 0 and not keyed else p.get(key, 50.0) / 100.0)
    return float(1 - v if p.get("reverse") else v)
def WIPE(d=50.0): return [F("progress", "Progress", d, 0, 100), F("anim", "Run by itself (s)", 0.0, 0, 20), F("delay", "Start after (s)", 0.0, 0, 20), B("reverse", "Reverse", False)]


# ------------------------------------------------------------------ noise
def _grid(gh, gw, seed):
    key = (gh, gw, seed); g = _NZ.get(key)
    if g is None:
        g = np.random.default_rng(seed * 2654435761 % 2 ** 32).random((gh, gw)).astype(np.float32); _NZ[key] = g
        while len(_NZ) > 120: _NZ.popitem(last=False)
    return g
def noise2(h, w, sx, sy, seed=1, t=0.0):
    """Smooth value noise 0..1 with different feature sizes across (sx) and down (sy); t moves it in time."""
    sx = max(2.0, float(sx)); sy = max(2.0, float(sy)); gh, gw = int(h / sy) + 3, int(w / sx) + 3; i = int(np.floor(t)); f = t - i; f = f * f * (3 - 2 * f)
    g = _grid(gh, gw, seed * 977 + i)
    if f > 1e-4: g = g * (1 - f) + _grid(gh, gw, seed * 977 + i + 1) * f
    big = cv2.resize(g, (int(gw * sx) + 1, int(gh * sy) + 1), interpolation=cv2.INTER_CUBIC)
    return np.clip(big[:h, :w], 0, 1)
def noise(h, w, scale, seed=1, t=0.0): return noise2(h, w, scale, scale, seed, t)
def fbm(h, w, scale, seed=1, t=0.0, octaves=4):
    tot = np.zeros((h, w), np.float32); amp = 1.0; norm = 0.0
    for o in range(octaves):
        tot += amp * noise(h, w, scale / (2 ** o), seed + o * 31, t * (1 + o * 0.5)); norm += amp; amp *= 0.5
    return tot / norm


# ------------------------------------------------------------------ colour
def bgr(col): c = QColor(col); return np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
def f3(img): return np.multiply(img[..., :3], np.float32(1 / 255), dtype=np.float32)       # one pass (was astype + multiply); same numbers
def lum(f): return f @ np.array([0.114, 0.587, 0.299], np.float32)
def pack(rgb, alpha=None, like=None):
    """float BGR 0..1 (+ alpha 0..1 or uint8) -> BGRA uint8. The alpha of `like` is kept when no alpha is given."""
    h, w = rgb.shape[:2]; out = np.empty((h, w, 4), np.uint8)
    if rgb.dtype == np.float32 and rgb.ndim == 3 and h * w > 100000:         # the same sum, done in bands that stay in the CPU cache (no big temporaries)
        for y0 in range(0, h, _BAND):
            t = rgb[y0:y0 + _BAND] * np.float32(255); t += np.float32(.5); np.clip(t, 0, 255, out=t); out[y0:y0 + _BAND, :, :3] = t
    else: out[..., :3] = np.clip(rgb * 255 + .5, 0, 255).astype(np.uint8)
    if alpha is None: out[..., 3] = like[..., 3] if like is not None else 255
    elif alpha.dtype == np.uint8: out[..., 3] = alpha
    else: out[..., 3] = np.clip(alpha * 255 + .5, 0, 255).astype(np.uint8)
    return out
def hsv_bgr(h, s, v):
    """h 0..1 (any shape), s, v 0..1 -> float BGR."""
    h = (np.asarray(h, np.float32) % 1.0) * 6; i = np.floor(h); f = h - i; s = np.asarray(s, np.float32) * np.ones_like(h); v = np.asarray(v, np.float32) * np.ones_like(h)
    p_, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f)); i = i.astype(int) % 6
    r = np.choose(i, [v, q, p_, p_, t, v]); g = np.choose(i, [t, v, v, q, p_, p_]); b = np.choose(i, [p_, p_, t, v, v, q])
    return np.stack([b, g, r], -1)
def ramp(vals, stops):
    """Colour the values 0..1 with a gradient: stops = [(pos, '#rrggbb'), ...] -> float BGR."""
    xs = [s[0] for s in stops]; cs = np.array([bgr(s[1]) for s in stops], np.float32); v = np.clip(vals, 0, 1)
    return np.stack([np.interp(v, xs, cs[:, i]) for i in range(3)], -1).astype(np.float32)


# ------------------------------------------------------------------ blending
_BAND = 48            # rows per band for the cache-friendly versions below (a band of float32 stays inside the CPU cache)
def blend(img, pat, pa=None, mode="over", opacity=1.0):
    """Put a generated picture (float BGR, optional alpha 0..1) onto the picture with a blend mode. Big pictures are done band by band
    (every step is per pixel, so the numbers are exactly the same, only much less memory is pushed around)."""
    h, w = img.shape[:2]
    if h * w > 100000 and getattr(pat, "ndim", 0) == 3 and pat.shape[:2] == (h, w) and (pa is None or getattr(pa, "shape", None) == (h, w)):
        out = np.empty((h, w, 4), np.uint8)
        for y0 in range(0, h, _BAND): out[y0:y0 + _BAND] = _blend(img[y0:y0 + _BAND], pat[y0:y0 + _BAND], None if pa is None else pa[y0:y0 + _BAND], mode, opacity)
        return out
    return _blend(img, pat, pa, mode, opacity)
def _blend(img, pat, pa=None, mode="over", opacity=1.0):
    base = f3(img); ia = img[..., 3].astype(np.float32) * (1 / 255); pa = np.ones(ia.shape, np.float32) if pa is None else pa; op = float(opacity)
    if mode == "replace": rgb = base * (1 - op * pa[..., None]) + pat * (op * pa[..., None]); al = np.maximum(ia, op * pa)
    elif mode == "behind":
        w_ = (pa * (1 - ia))[..., None] * op; rgb = (base * ia[..., None] + pat * w_) / np.maximum(ia[..., None] + w_, 1e-4); al = np.clip(ia + w_[..., 0], 0, 1)
    elif mode in ("add", "screen"):
        # Light is new picture: where the media is see-through it must show too (Porter-Duff on premultiplied colours), so its alpha grows
        # with the brightness of the light. On opaque pixels the result is exactly the old add / screen.
        light = pat * (pa[..., None] * op); m = np.clip(np.maximum(np.maximum(light[..., 0], light[..., 1]), light[..., 2]), 0, 1); al = ia + m - ia * m; bp = base * ia[..., None]
        pm = bp + light if mode == "add" else bp + light - bp * np.clip(light, 0, 1); rgb = pm / np.maximum(al[..., None], 1e-4)
    elif mode == "multiply": rgb = base * (1 - pa[..., None] * op) + base * pat * (pa[..., None] * op); al = ia
    elif mode == "overlay":
        o = np.where(base < 0.5, 2 * base * pat, 1 - 2 * (1 - base) * (1 - pat)); rgb = base + (o - base) * (pa[..., None] * op); al = ia
    else: rgb = base * (1 - pa[..., None] * op) + pat * (pa[..., None] * op); al = ia
    return pack(np.clip(rgb, 0, 1), al)


# ------------------------------------------------------------------ remapping
def remap(img, mx, my, border=cv2.BORDER_REFLECT):
    """Sample the picture at (mx, my) (picture pixels)."""
    return cv2.remap(np.ascontiguousarray(img), mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=border)
def remap_clear(img, mx, my): return cv2.remap(np.ascontiguousarray(img), mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
def displace(img, dx, dy, border=cv2.BORDER_REFLECT):
    h, w = img.shape[:2]; x, y = coords(h, w); return remap(img, x + dx, y + dy, border)
def affine(img, M, clear=True):
    h, w = img.shape[:2]
    return cv2.warpAffine(np.ascontiguousarray(img), M.astype(np.float32), (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT if clear else cv2.BORDER_REFLECT, borderValue=(0, 0, 0, 0))
def xform(h, w, tx=0.0, ty=0.0, rot=0.0, sc=1.0, cx=0.5, cy=0.5):
    """2x3 matrix: rotate (degrees) and scale about (cx, cy) (fractions), then move by (tx, ty) pixels."""
    M = cv2.getRotationMatrix2D((w * cx, h * cy), -rot, sc); M[0, 2] += tx; M[1, 2] += ty; return M
def shift_rows(img, shifts):
    """Move every row sideways by shifts[row] pixels (wraps around)."""
    h, w = img.shape[:2]; x, y = coords(h, w); return remap(img, (x - shifts[:, None]) % w, y, cv2.BORDER_REFLECT)
def lum8(img): return ((img[..., :3].astype(np.float32) @ np.array([0.114, 0.587, 0.299], np.float32)) * np.float32(1 / 255)).astype(np.float32)
def edges(img, ctx, width=1.0):
    """Edge strength 0..1 of the picture (Sobel on the luminance and the alpha)."""
    g = (lum8(img) * (img[..., 3] * np.float32(1 / 255))).astype(np.float32); s = max(0.5, width * ctx.k * 0.7)
    if s > 0.6: g = cv2.GaussianBlur(g, (0, 0), s)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3); return np.clip(np.sqrt(gx * gx + gy * gy) * 2.0, 0, 1)
def pm4(img):
    """Premultiplied float32 (h, w, 4): colors times alpha, and alpha. Averaging / blurring these never bleeds black from see-through parts."""
    a = img[..., 3:4].astype(np.float32) * (1 / 255); return np.concatenate([img[..., :3].astype(np.float32) * a, a], -1)
def unpm4(x): return _unpremul(x[..., :3], x[..., 3])
def glow_of(a, sigma):
    """Soft glow of a float picture (any channels)."""
    return _gauss(a.astype(np.float32), max(0.4, sigma))
def disc(h, w, cx, cy, r, soft=1.0):
    x, y = coords(h, w); d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2); return np.clip((r - d) / max(soft, 1e-3) + 0.5, 0, 1)

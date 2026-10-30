"""Effect layers: registry of effects (parameters + image function) and the stack applied to a clip's image.

A clip keeps an ordered list  c["effects"] = [{"id", "type", "on", "p": {...}}, ...]  (top of the list is applied first).
Add a new effect = write one function and call register(...); the Effects panel builds its controls from the parameter list.
Image functions receive / return an 8-bit BGRA image.  Sizes are in *layer pixels* (the clip at 100 % scale); ctx.k converts
them to image pixels, so the preview (lower resolution) looks the same as the export.
"""
from ..shared.deps import *
from types import SimpleNamespace
from ..shared.core import DEFAULT_CURVE, IDENT, curve_eval, new_id

FX = OrderedDict()          # type -> {"cat", "title", "params", "fn", "area"}
FX_CATS = ["Color", "Blur", "Distort", "Stylize", "Key"]
_LUT_CACHE = {}


def register(type_, cat, title, params, fn, area=False):
    """params: [(key, label, kind, default, lo, hi)]   kind = float | int | color | choice | bool | curve
    (for kind 'choice' the `lo` slot holds the [(value, label)] options)."""
    FX[type_] = {"cat": cat, "title": title, "params": params, "fn": fn, "area": area}


def fx_defaults(type_):
    spec = FX[type_]; p = {}
    for key, label, kind, dflt, lo, hi in spec["params"]: p[key] = copy.deepcopy(dflt)
    if spec["area"]:
        from .renderer import MASK_DEFAULT
        p["mask"] = "Rect"; p["mask_shape"] = copy.deepcopy(MASK_DEFAULT); p["mask_feather"] = 12
    return p


def new_effect(type_):
    return {"id": new_id(), "type": type_, "on": True, "p": fx_defaults(type_)}


def fx_param_spec(type_, key):
    for sp in FX.get(type_, {}).get("params", ()):
        if sp[0] == key: return sp
    return None


def clean_params(spec, p):
    """Merge defaults with the stored values and clamp every number (NaN / inf / out of range can never reach an image function)."""
    out = {}
    for key, label, kind, dflt, lo, hi in spec["params"]:
        v = p.get(key, dflt)
        try:
            if kind in ("float", "int"):
                v = float(v)
                if v != v or v in (float("inf"), float("-inf")): v = float(dflt)
                v = max(lo, min(hi, v)); v = int(round(v)) if kind == "int" else v
            elif kind == "bool": v = bool(v)
            elif kind == "choice":
                if v not in [o[0] for o in lo]: v = dflt
            elif kind == "color":
                if not QColor(v).isValid(): v = dflt
        except Exception: v = dflt
        out[key] = v
    return out


def apply_effects(c, img, k=1.0, lt=0.0, fast=False):
    """Run the clip's effect stack on a BGRA image.  A failing effect is skipped, never fatal."""
    fx = c.get("effects")
    if not fx or img is None or img.ndim != 3: return img
    if img.dtype != np.uint8: img = np.clip(img, 0, 255).astype(np.uint8)
    if img.shape[2] == 3: img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    for e in fx:
        if not e.get("on", True): continue
        spec = FX.get(e.get("type"))
        if spec is None: continue
        ctx = SimpleNamespace(k=max(1e-3, float(k)), lt=lt, fast=fast, clip=c, holder=e.get("p", {}))
        try:
            out = spec["fn"](img, clean_params(spec, e.get("p", {})), ctx)
            if out is not None and out.shape == img.shape and out.dtype == np.uint8: img = out
        except Exception as ex: print("[effects]", e.get("type"), ex)
    return img


# ───────────────────────── helpers ─────────────────────────
def _premul(img):
    a = img[..., 3:4].astype(np.float32) * (1 / 255); return img[..., :3].astype(np.float32) * a, a[..., 0]


def _unpremul(pm, a):
    rgb = pm / np.maximum(a[..., None], 1e-4)
    out = np.empty(a.shape + (4,), np.uint8); out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8); out[..., 3] = np.clip(a * 255 + .5, 0, 255).astype(np.uint8)
    return out


def _gauss(arr, sigma):
    """Gaussian blur; large radii run on a shrunken copy (same look, a fraction of the time)."""
    if sigma < 0.35: return arr
    h, w = arr.shape[:2]
    if sigma > 6:
        f = 4.0 / sigma; sw, sh = max(1, int(w * f)), max(1, int(h * f))
        small = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA); s = 4.0
        kk = int(s * 3) * 2 + 1; small = cv2.GaussianBlur(small, (kk, kk), s)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    kk = int(sigma * 3) * 2 + 1; return cv2.GaussianBlur(arr, (kk, kk), sigma)


def blur_bgra(img, sigma):
    """Blur colour and alpha together on premultiplied pixels (transparent areas never bleed black into the picture)."""
    if sigma < 0.35: return img
    pm, a = _premul(img); return _unpremul(_gauss(pm, sigma), _gauss(a, sigma))


def _mix(a, b, m):
    """a*(1-m)+b*m for BGRA uint8 images, m = float32 HxW in 0..1."""
    m3 = m[..., None]; return np.clip(a.astype(np.float32) * (1 - m3) + b.astype(np.float32) * m3 + .5, 0, 255).astype(np.uint8)


def _area_mask(p, holder, iw, ih):
    """0..1 float mask of the effect's own area (reuses the clip-mask shapes, including the hand-drawn Custom shape)."""
    from .renderer import mask_alpha, MASK_DEFAULT
    sh = holder.get("mask", "Rect")
    if sh in (None, "None"): return None
    ms = dict(MASK_DEFAULT, **(holder.get("mask_shape") or {}))
    m = mask_alpha(sh, ms, iw, ih, holder.get("mask_feather", 0))
    return None if m is None else m.astype(np.float32) * (1 / 255)


# ───────────────────────── color ─────────────────────────
def fx_tint(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    col = QColor(p["color"]); tc = np.array([col.blueF(), col.greenF(), col.redF()], np.float32)
    f = img[..., :3].astype(np.float32) * (1 / 255); g = (f @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
    tinted = np.where(g < 0.5, 2 * g * tc, 1 - 2 * (1 - g) * (1 - tc)); out = img.copy()
    out[..., :3] = np.clip((f + (tinted - f) * a) * 255, 0, 255).astype(np.uint8); return out


def fx_curves(img, p, ctx):
    curve = p.get("curve") or DEFAULT_CURVE
    if all(curve.get(k, IDENT) == IDENT for k in "mrgb"): return img
    key = json.dumps(curve, sort_keys=True); lut = _LUT_CACHE.get(key)
    if lut is None:
        xs = np.linspace(0, 1, 256)
        lut = np.stack([(curve_eval(curve["m"], curve_eval(curve[ch], xs)) * 255 + .5).astype(np.uint8) for ch in ("b", "g", "r")], -1).reshape(256, 1, 3)
        if len(_LUT_CACHE) > 64: _LUT_CACHE.clear()
        _LUT_CACHE[key] = lut
    out = img.copy(); out[..., :3] = cv2.LUT(np.ascontiguousarray(img[..., :3]), lut); return out


def fx_adjust(img, p, ctx):
    br, co, sa, hu = p["brightness"], p["contrast"], p["saturation"], p["hue"]
    if br == 0 and co == 0 and sa == 0 and hu == 0: return img
    f = img[..., :3].astype(np.float32) * (1 / 255)
    f = (f - .5) * (1 + co / 100) + .5 + br / 200
    if sa != 0 or hu != 0:
        f8 = np.clip(f * 255, 0, 255).astype(np.uint8); hsv = cv2.cvtColor(f8, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 0] = (hsv[..., 0] + hu / 2.0) % 180; hsv[..., 1] = np.clip(hsv[..., 1] * (1 + sa / 100), 0, 255)
        f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) * (1 / 255)
    out = img.copy(); out[..., :3] = np.clip(f * 255 + .5, 0, 255).astype(np.uint8); return out


def fx_bw(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    f = img[..., :3].astype(np.float32); g = (f @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
    out = img.copy(); out[..., :3] = np.clip(f + (g - f) * a + .5, 0, 255).astype(np.uint8); return out


def fx_invert(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    f = img[..., :3].astype(np.float32); out = img.copy(); out[..., :3] = np.clip(f + (255 - 2 * f) * a + .5, 0, 255).astype(np.uint8); return out


# ───────────────────────── blur ─────────────────────────
def fx_blur(img, p, ctx): return blur_bgra(img, p["amount"] * ctx.k)


def fx_motion_blur(img, p, ctx):
    n = int(p["length"] * ctx.k)
    if n < 2: return img
    h, w = img.shape[:2]; n = min(n, max(h, w) // 2)
    sc = max(1.0, n / 14.0)                                   # long blurs run on a shrunken copy (same look, much faster)
    pm, a = _premul(img)
    if sc > 1:
        sw, sh = max(1, int(w / sc)), max(1, int(h / sc))
        pm = cv2.resize(pm, (sw, sh), interpolation=cv2.INTER_AREA); a = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    m = max(3, int(round(n / sc))) | 1; ker = np.zeros((m, m), np.float32); ker[m // 2, :] = 1
    ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((m / 2 - .5, m / 2 - .5), -p["angle"], 1), (m, m)); ker /= max(float(ker.sum()), 1e-6)
    pad = m // 2
    def run(x): return cv2.filter2D(cv2.copyMakeBorder(x, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0), -1, ker)[pad:-pad, pad:-pad]
    pm, a = run(pm), run(a)
    if sc > 1:
        pm = cv2.resize(pm, (w, h), interpolation=cv2.INTER_LINEAR); a = cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)
    return _unpremul(pm, a)


def fx_radial_blur(img, p, ctx):
    amt = p["amount"] / 100 * 0.25
    if amt <= 0.002: return img
    h, w = img.shape[:2]; cx, cy = w * p["cx"] / 100, h * p["cy"] / 100; steps = 6 if ctx.fast else 14
    pm, a = _premul(img); acc = np.zeros_like(pm); acca = np.zeros_like(a)
    for i in range(steps):
        s = 1 + amt * i / (steps - 1); M = np.array([[s, 0, cx - cx * s], [0, s, cy - cy * s]], np.float32)
        acc += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        acca += cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)


def fx_area_blur(img, p, ctx):
    ih, iw = img.shape[:2]; m = _area_mask(p, ctx.holder, iw, ih); blurred = blur_bgra(img, p["amount"] * ctx.k)
    return blurred if m is None else _mix(img, blurred, m)


# ───────────────────────── distort / stylize ─────────────────────────
def fx_rgb_split(img, p, ctx):
    d = p["amount"] * ctx.k
    if d < 0.3: return img
    th = math.radians(p["angle"]); dx, dy = math.cos(th) * d, math.sin(th) * d; h, w = img.shape[:2]; out = img.copy()
    for ch, sgn in ((2, 1.0), (0, -1.0)):           # red goes one way, blue the other, green stays
        M = np.array([[1, 0, dx * sgn], [0, 1, dy * sgn]], np.float32)
        out[..., ch] = cv2.warpAffine(np.ascontiguousarray(img[..., ch]), M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out


def fx_pixelate(img, p, ctx):
    s = max(1, int(round(p["size"] * ctx.k))); h, w = img.shape[:2]
    if s <= 1: return img
    small = cv2.resize(img, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def fx_glitch(img, p, ctx):
    amt = p["amount"] / 100
    if amt <= 0: return img
    h, w = img.shape[:2]; rng = np.random.default_rng(int(ctx.lt * 12) * 7919 + int(p["seed"])); out = img.copy()
    for _ in range(int(2 + amt * 14)):
        y0 = int(rng.integers(0, h)); hh = int(rng.integers(max(1, h // 80), max(2, h // 8))); sh = int(rng.normal(0, w * 0.08 * amt))
        if hh > 0 and sh: out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], sh, axis=1)
    return fx_rgb_split(out, {"amount": 6 * amt, "angle": 0}, ctx)


def fx_sharpen(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    blur = cv2.GaussianBlur(img[..., :3], (0, 0), max(0.6, 1.2 * ctx.k)); out = img.copy()
    out[..., :3] = cv2.addWeighted(img[..., :3], 1 + a, blur, -a, 0); return out


def fx_vignette(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]; yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 1.4142
    start = 1.0 - p["softness"] / 100 * 0.95; v = np.clip((r - start) / max(1e-3, 1 - start), 0, 1) ** 2
    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) * (1 - v[..., None] * a) + .5, 0, 255).astype(np.uint8); return out


def fx_glow(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    f = img[..., :3].astype(np.float32); lum = (f @ np.array([0.114, 0.587, 0.299], np.float32)) * (1 / 255); thr = p["threshold"] / 100
    bright = np.clip((lum - thr) / max(1e-3, 1 - thr), 0, 1)[..., None] * f
    glow = _gauss(bright, max(0.5, p["radius"] * ctx.k)); out = img.copy()
    out[..., :3] = np.clip(255 - (255 - f) * (255 - glow * a) / 255 + .5, 0, 255).astype(np.uint8); return out      # screen blend


def fx_grain(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]; s = max(1, int(round(p["size"] * ctx.k)))
    rng = np.random.default_rng(int(ctx.lt * 24) * 104729 + 17); n = rng.standard_normal((max(1, h // s), max(1, w // s))).astype(np.float32)
    if s > 1: n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)
    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) + n[..., None] * 40 * a + .5, 0, 255).astype(np.uint8); return out


# ───────────────────────── key ─────────────────────────
def fx_chroma(img, p, ctx):
    try:
        key = QColor(p["color"]); hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
        khsv = cv2.cvtColor(np.uint8([[[key.blue(), key.green(), key.red()]]]), cv2.COLOR_BGR2HSV)[0, 0]; tol = int(p["tolerance"])
        h16 = hsv[..., 0].astype(np.int16); dh = np.minimum(np.abs(h16 - int(khsv[0])), 180 - np.abs(h16 - int(khsv[0])))
        dsat = np.abs(hsv[..., 1].astype(np.int16) - int(khsv[1])); ka = np.clip((np.maximum(dh * 2, dsat) - tol) / max(1, tol), 0, 1)
        out = img.copy(); out[..., 3] = (img[..., 3].astype(np.float32) * ka).astype(np.uint8); return out
    except Exception as ex:
        print("chroma key error:", ex); return img


# ───────────────────────── registry ─────────────────────────
register("tint", "Color", "Tint", [("color", "Color", "color", "#2f7bff", None, None), ("amount", "Amount", "float", 50.0, 0.0, 100.0)], fx_tint)
register("curves", "Color", "Curves", [("curve", "Curves", "curve", copy.deepcopy(DEFAULT_CURVE), None, None)], fx_curves)
register("adjust", "Color", "Adjust",
         [("brightness", "Brightness", "float", 0.0, -100.0, 100.0), ("contrast", "Contrast", "float", 0.0, -100.0, 100.0),
          ("saturation", "Saturation", "float", 0.0, -100.0, 100.0), ("hue", "Hue shift", "float", 0.0, -180.0, 180.0)], fx_adjust)
register("bw", "Color", "Black & white", [("amount", "Amount", "float", 100.0, 0.0, 100.0)], fx_bw)
register("invert", "Color", "Invert", [("amount", "Amount", "float", 100.0, 0.0, 100.0)], fx_invert)
register("blur", "Blur", "Blur", [("amount", "Amount", "float", 12.0, 0.0, 100.0)], fx_blur)
register("motion_blur", "Blur", "Motion blur", [("length", "Length", "float", 40.0, 0.0, 300.0), ("angle", "Angle", "float", 0.0, -180.0, 180.0)], fx_motion_blur)
register("radial_blur", "Blur", "Radial blur",
         [("amount", "Amount", "float", 40.0, 0.0, 100.0), ("cx", "Center X", "float", 50.0, 0.0, 100.0), ("cy", "Center Y", "float", 50.0, 0.0, 100.0)], fx_radial_blur)
register("area_blur", "Blur", "Area blur", [("amount", "Amount", "float", 25.0, 0.0, 100.0)], fx_area_blur, area=True)
register("rgb_split", "Distort", "Color split", [("amount", "Distance", "float", 8.0, 0.0, 80.0), ("angle", "Angle", "float", 0.0, -180.0, 180.0)], fx_rgb_split)
register("pixelate", "Distort", "Pixelate", [("size", "Block size", "float", 14.0, 1.0, 120.0)], fx_pixelate)
register("glitch", "Distort", "Glitch", [("amount", "Amount", "float", 40.0, 0.0, 100.0), ("seed", "Seed", "int", 1, 0, 999)], fx_glitch)
register("sharpen", "Stylize", "Sharpen", [("amount", "Amount", "float", 60.0, 0.0, 300.0)], fx_sharpen)
register("vignette", "Stylize", "Vignette", [("amount", "Amount", "float", 50.0, 0.0, 100.0), ("softness", "Softness", "float", 60.0, 0.0, 100.0)], fx_vignette)
register("glow", "Stylize", "Glow",
         [("amount", "Amount", "float", 60.0, 0.0, 100.0), ("radius", "Radius", "float", 20.0, 0.0, 100.0), ("threshold", "Threshold", "float", 60.0, 0.0, 100.0)], fx_glow)
register("grain", "Stylize", "Film grain", [("amount", "Amount", "float", 25.0, 0.0, 100.0), ("size", "Grain size", "float", 1.0, 1.0, 10.0)], fx_grain)
register("chroma", "Key", "Chroma key", [("color", "Key color", "color", "#00ff00", None, None), ("tolerance", "Tolerance", "int", 55, 1, 180)], fx_chroma)

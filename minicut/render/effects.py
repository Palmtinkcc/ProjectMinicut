"""Effect layers: registry of effects (parameters + image function) and the stack applied to a clip's image.

A clip keeps an ordered list  c["effects"] = [{"id", "type", "on", "p": {...}}, ...]  (top of the list is applied first).
Add a new effect = write one function and call register(...); the Effects panel builds its controls from the parameter list.
Image functions receive / return an 8-bit BGRA image.  Sizes are in *layer pixels* (the clip at 100 % scale); ctx.k converts
them to image pixels, so the preview (lower resolution) looks the same as the export.
"""
from ..shared.deps import *
from types import SimpleNamespace
import threading

# Patch 33: GPU-accelerated effect helpers (optional — CPU fallback on any error)
try:
    from .gpu_fx import (GpuFxUnavailable,
                         gpu_gaussian_blur, gpu_zoom_blur, gpu_spin_blur,
                         gpu_glow, gpu_sharpen, gpu_adjust, gpu_tint,
                         gpu_bw, gpu_vignette)
    _GPU_FX = True
except Exception:
    _GPU_FX = False

try:                              # Patch 35: OpenGL effect chains (needs moderngl; any problem -> the CPU effects run as before)
    from . import glfx as _GLX
except Exception:
    _GLX = None

_REF = threading.local()      # the media inside a picture that has an empty border around it (spill): 3D objects and effects that size themselves from the picture read it
_TIME = threading.local()     # set while an effect stack runs and something in it depends on the clip time (ctx.lt read, or keyframes)


class _Ctx:
    """What an effect function gets next to its parameters. Reading .lt is noted: an effect that never reads the time gives the same
    picture at every moment, so the renderer can keep that picture instead of drawing it again for every frame."""
    def __init__(self, k, lt, fast, clip=None, holder=None, progress_keyframed=False, bg=None):
        self.k = k; self._lt = lt; self.fast = fast; self.clip = clip; self.holder = holder if holder is not None else {}
        self.progress_keyframed = progress_keyframed; self.bg = bg
    @property
    def lt(self): _TIME.used = True; return self._lt


def time_used():
    """True when the effect stack that ran last on this thread depends on the clip time."""
    return bool(getattr(_TIME, "used", False))


def ref_crop(img):
    """The media inside a spilled layer (the picture a 3D object wraps around itself), or the picture itself."""
    r = getattr(_REF, "rect", None)
    if not r: return img
    x0, y0, x1, y1 = r; return np.ascontiguousarray(img[y0:y1, x0:x1])


def ref_origin():
    """(x, y) of the top left corner of the media inside a picture with an empty border around it; (0, 0) when the picture is the media."""
    r = getattr(_REF, "rect", None)
    return (r[0], r[1]) if r else (0, 0)


def ref_size(h, w):
    """(h, w) an effect should size itself from: the media inside a spilled layer, otherwise the whole picture."""
    r = getattr(_REF, "hw", None)
    return r if r else (h, w)
from ..shared.core import DEFAULT_CURVE, IDENT, curve_eval, new_id, bezier_ease

FX = OrderedDict()          # type -> {"cat", "title", "params", "fn", "area"}
FX_CATS = ['Color', 'Opacity', 'Glitch', 'VHS', 'Background', 'Repeat', 'Particle', '3D object', 'Wipes & shatter', 'Shake & transform', 'Strokes & shadows', 'Distortion & warp', 'Procedural', 'Move', 'Blur', 'Lens', 'Water & glass', 'Ink & paint', 'Distort', 'Stylize', 'Key']
_LUT_CACHE = {}


def register(type_, cat, title, params, fn, area=False, help="", kw=""):
    """params: [(key, label, kind, default, lo, hi)]   kind = float | int | color | choice | bool | curve
    (for kind 'choice' the `lo` slot holds the [(value, label)] options)."""
    FX[type_] = {"cat": cat, "title": title, "params": params, "fn": fn, "area": area, "help": help, "kw": kw}


def fx_defaults(type_):
    spec = FX[type_]; p = {}
    for key, label, kind, dflt, lo, hi in spec["params"]: p[key] = copy.deepcopy(dflt)
    if spec["area"]:
        from .renderer import MASK_DEFAULT
        p["mask"] = "Rect"; p["mask_shape"] = copy.deepcopy(MASK_DEFAULT); p["mask_feather"] = 12
    return p


def new_effect(type_):
    return {"id": new_id(), "type": type_, "on": True, "spill": False, "p": fx_defaults(type_)}


def clip_spills(c):
    """True when an effect layer of the clip may draw outside the media (the renderer then gives the picture an empty border to draw in)."""
    if c.get("kind") == "compound": return False
    return any(e.get("on", True) and e.get("spill") and e.get("type") in FX for e in (c.get("effects") or []))


def _rainbow(): return [(i / 6.0, QColor.fromHsvF(min(i / 6.0, 0.999), 1.0, 1.0)) for i in range(7)]


_VIZ = {          # (effect, parameter) -> what the slider shows (for names that say nothing by themselves)
    ("adjust", "brightness"): {"stops": [(0.0, QColor("#000000")), (1.0, QColor("#ffffff"))]},
    ("adjust", "saturation"): {"stops": [(0.0, QColor("#8f8f8f")), (0.5, QColor("#b07fa0")), (1.0, QColor("#ff2f7a"))]},
    ("bw", "amount"): {"stops": [(0.0, QColor("#ff8a3d")), (1.0, QColor("#8a8a8a"))]},
    ("vignette", "amount"): {"stops": [(0.0, QColor(0, 0, 0, 0)), (1.0, QColor(0, 0, 0, 255))], "alpha": True},
    ("glow", "amount"): {"stops": [(0.0, QColor(255, 255, 255, 0)), (1.0, QColor(255, 255, 255, 255))], "alpha": True},
    ("grain", "amount"): {"stops": [(0.0, QColor(255, 255, 255, 0)), (1.0, QColor(255, 255, 255, 255))], "alpha": True},
}


def param_viz(type_, key, label, lo, hi):
    """What the track of the slider of a parameter should show instead of a plain bar: the colours of a hue, a fade for an
    opacity, or a fade towards the colour of the effect. None = a plain bar. Works from the names, so a new effect gets it too."""
    v = _VIZ.get((type_, key))
    if v: return v
    k = key.lower(); lab = (label or "").lower()
    if "hue" in k or "hue" in lab: return {"stops": _rainbow()}
    if any(w in k or w in lab for w in ("opacity", "alpha", "transparen", "dissolve")):
        return {"stops": [(0.0, QColor(255, 255, 255, 0)), (1.0, QColor(255, 255, 255, 255))], "alpha": True}
    cols = [sp[0] for sp in FX.get(type_, {}).get("params", ()) if sp[2] == "color"]
    if cols and any(w in k for w in ("amount", "strength", "intensity", "mix")): return {"color_key": cols[0]}
    return None


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


def _effect_param_value(e, key, lt, fallback):
    """Evaluate an effect parameter track using the same Bezier easing as native clip properties."""
    ks = sorted(((e.get("keys") or {}).get(key) or []), key=lambda x: float(x.get("t", 0)))
    if not ks: return (e.get("p") or {}).get(key, fallback)
    if lt <= ks[0]["t"]: return ks[0]["v"]
    if lt >= ks[-1]["t"]: return ks[-1]["v"]
    for a, b in zip(ks, ks[1:]):
        if a["t"] <= lt <= b["t"]:
            u = (lt - a["t"]) / max(1e-9, b["t"] - a["t"])
            u = bezier_ease(a.get("e", [0, 0, 1, 1]), u)
            av, bv = a["v"], b["v"]
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                value = av + (bv - av) * u
                return int(round(value)) if isinstance(av, int) and isinstance(bv, int) else value
            if isinstance(av, str) and isinstance(bv, str) and QColor(av).isValid() and QColor(bv).isValid():
                ca, cb = QColor(av), QColor(bv)
                return QColor(round(ca.red() + (cb.red()-ca.red())*u), round(ca.green()+(cb.green()-ca.green())*u), round(ca.blue()+(cb.blue()-ca.blue())*u), round(ca.alpha()+(cb.alpha()-ca.alpha())*u)).name(QColor.HexArgb)
            return av if u < 1 else bv
    return ks[-1]["v"]


_lane_ok = lambda e: False        # replaced by fastfx.lane_ok when the fast effects are installed


def _effect_params(e, spec, lt):
    """The cleaned parameters of an effect layer at clip time lt (animated parameters evaluated)."""
    params = clean_params(spec, e.get("p", {}))
    # Evaluate each animated parameter at the clip-local playhead time before
    # calling the effect. A keyframed Progress track must take precedence over
    # the effect's autonomous timer; otherwise prog() replaces the interpolated
    # value and the effect appears to stop/change incorrectly between keyframes.
    for key, _, kind, dflt, lo, hi in spec["params"]:
        track = (e.get("keys") or {}).get(key) or []
        if track:
            _TIME.used = True
            params[key] = _effect_param_value(e, key, lt, params.get(key, dflt))
    return clean_params(spec, params)


_LIGHT_FX = frozenset({"glow", "soft_glow"})      # glows: the light is new picture, so it has to show where the media is see-through too


def _see_through(img):
    return img.shape[2] == 4 and cv2.minMaxLoc(cv2.extractChannel(img, 3))[0] < 255


def _run_fx(c, img, e, spec, k, lt, fast, inner, bg):
    """One effect function on a BGRA picture. A failing effect is skipped, never fatal.
    inner: (x0, y0, x1, y1) of the media inside this picture when it has an empty border around the media, else None."""
    ctx = _Ctx(max(1e-3, float(k)), lt, fast, clip=c, holder=e.get("p", {}), progress_keyframed=bool((e.get("keys") or {}).get("progress")), bg=bg)      # bg: BGR canvas behind this layer (may be None)
    try:
        params = _effect_params(e, spec, lt); ctx.holder = params
        _REF.hw = (inner[3] - inner[1], inner[2] - inner[0]) if inner is not None else None; _REF.rect = inner
        work = img; light = e.get("type") in _LIGHT_FX and _see_through(img)
        if light:       # work on the colours over black (an opaque picture): what the glow adds is then new picture, and gets an alpha below
            a = np.ascontiguousarray(img[..., 3]); work = np.empty_like(img)
            work[..., :3] = cv2.multiply(np.ascontiguousarray(img[..., :3]), cv2.merge((a, a, a)), scale=1 / 255.0); work[..., 3] = 255
        out = spec["fn"](work, params, ctx)
        if out is None or out.shape != work.shape or out.dtype != np.uint8: return img
        if light:
            al = np.maximum(a, out[..., :3].max(-1)); res = np.empty_like(out)
            res[..., :3] = cv2.divide(np.ascontiguousarray(out[..., :3]), cv2.merge((al, al, al)), scale=255.0); res[..., 3] = al; out = res
        return out
    except Exception as ex: print("[effects]", e.get("type"), ex); return img
    finally: _REF.hw = None; _REF.rect = None


def _apply_one(c, img, e, spec, k, lt, fast, inner, bg, lane):
    """One effect layer on the CPU.
    With `inner` (the picture has an empty border, see Renderer._pad_for_spill) an effect with Spill on works on the whole picture, so it can draw
    in the border. An effect with Spill off works on the media alone, exactly as on a picture without a border, and what is outside the media
    stays as the effects before it left it."""
    if img.shape[2] == 3 and not (lane is not None and lane(e)): img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if inner is None or e.get("spill"): return _run_fx(c, img, e, spec, k, lt, fast, inner, bg)
    x0, y0, x1, y1 = inner
    img[y0:y1, x0:x1] = _run_fx(c, np.ascontiguousarray(img[y0:y1, x0:x1]), e, spec, k, lt, fast, None, bg)       # img is this layer's own array, never a cached one
    return img


def _gl_run(c, fx, i, img, k, lt, fast, bg, lane, inner=None):
    """Patch 35: the run of effects that starts at fx[i] and that the GPU library knows is done as ONE GPU job (one upload, one read-back),
    or on the CPU, whichever the Chooser measured to be faster for this combination and picture size.
    Returns (picture, index of the next effect) or None when the CPU should do effect i by itself (not supported / GL off / GL error)."""
    items = []; idx = []; see = _see_through(img)
    for j in range(i, len(fx)):
        e = fx[j]
        if not e.get("on", True): continue
        t = e.get("type"); spec = FX.get(t)
        if spec is None: continue
        if spec.get("area") or not _GLX.supported(t): break
        if inner is not None and not e.get("spill"): break          # this one stays inside the media: the CPU path crops it
        if see and t in _LIGHT_FX: break                            # see-through media: see _run_fx
        try: items.append((t, _effect_params(e, spec, lt))); idx.append(j)
        except Exception: break
    if not items: return None
    plan = _GLX.build_chain(img, items, _Ctx(max(1e-3, float(k)), lt, fast))
    if plan is None: return None
    n = plan.n; end = idx[n - 1] + 1; h, w = img.shape[:2]
    key = (tuple(t for t, _ in items[:n]), (w * h) >> 15)
    pick = "gl" if (_GLX.is_export() or _GLX.forced()) else _GLX.CHOOSER.pick(key); t0 = _GLX.now_ms()
    if pick == "gl":
        try: out = _GLX.execute(img, plan)
        except Exception as ex: _GLX.fail("drawing failed: %s" % (ex,)); return None
        _GLX.CHOOSER.report(key, "gl", _GLX.now_ms() - t0); return out, end
    out = img
    for j in range(i, end):
        e = fx[j]; spec = FX.get(e.get("type"))
        if e.get("on", True) and spec is not None: out = _apply_one(c, out, e, spec, k, lt, fast, inner, bg, lane)
    _GLX.CHOOSER.report(key, "cpu", _GLX.now_ms() - t0); return out, end


def apply_effects(c, img, k=1.0, lt=0.0, fast=False, inner=None, bg=None):
    """Run the clip's effect stack on a BGRA image.  A failing effect is skipped, never fatal.
    inner: (x0, y0, x1, y1) of the media when `img` is the media with an empty border around it (see Renderer._pad_for_spill).
    bg: optional BGR uint8 canvas snapshot (the composited frame up to but not including this layer),
        used by copy_background and other composite-aware effects."""
    _TIME.used = False
    fx = c.get("effects")
    if not fx or img is None or img.ndim != 3: return img
    if img.dtype != np.uint8: img = np.clip(img, 0, 255).astype(np.uint8)
    # Patch 34: a 3-channel (BGR) picture stays 3-channel while the effects in the stack can work on it (see fastfx.lane_ok); it is widened
    # to BGRA once, at the first effect that needs the alpha plane.
    lane = _lane_ok if img.shape[2] == 3 and inner is None else None
    i = 0; n = len(fx)
    while i < n:
        e = fx[i]; spec = FX.get(e.get("type"))
        if not e.get("on", True) or spec is None: i += 1; continue
        # Patch 35: runs of GPU-capable effects go through OpenGL (preview thread only)
        if _GLX is not None and (inner is None or e.get("spill")) and _GLX.active():
            try: done = _gl_run(c, fx, i, img, k, lt, fast, bg, lane, inner)
            except Exception as ex: _GLX.fail("effect chain: %s" % (ex,)); done = None
            if done is not None: img, i = done; continue
        img = _apply_one(c, img, e, spec, k, lt, fast, inner, bg, lane); i += 1
    return img


# ───────────────────────── helpers ─────────────────────────
def _premul(img):
    a = img[..., 3:4].astype(np.float32) * (1 / 255); return img[..., :3].astype(np.float32) * a, a[..., 0]


def _unpremul(pm, a):
    rgb = pm / np.maximum(a[..., None], 1e-4)
    out = np.empty(a.shape + (4,), np.uint8); out[..., :3] = cv2.convertScaleAbs(rgb); out[..., 3] = cv2.convertScaleAbs(a, alpha=255.0)
    return out


def _gauss(arr, sigma):
    """Gaussian blur (float32 or uint8, any channel count). Patch 34: a blur of sigma >= 3 runs on a shrunken copy (the result is smooth
    anyway), so the cost stays small for any radius; the GPU round trip of the old version is gone (it was slower than this on most PCs)."""
    if sigma < 0.35: return arr
    h, w = arr.shape[:2]
    f = 1 if sigma < 3.0 else int(min(8, max(2, sigma / 1.5)))
    if f == 1:
        kk = int(sigma * 3) * 2 + 1; return cv2.GaussianBlur(arr, (kk, kk), sigma)
    sw, sh = max(1, w // f), max(1, h // f); rs = w / float(sw)
    small = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
    s = math.sqrt(max(sigma * sigma - rs * rs * 0.25, 0.04)) / rs; kk = int(s * 3) * 2 + 1
    small = cv2.GaussianBlur(small, (kk, kk), s)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def blur_bgra(img, sigma):
    """Blur colour and alpha together on premultiplied pixels (transparent areas never bleed black into the picture)."""
    if sigma < 0.35: return img
    pm, a = _premul(img); return _unpremul(_gauss(pm, sigma), _gauss(a, sigma))


def _mix(a, b, m):
    """a*(1-m)+b*m for BGRA uint8 images, m = float32 HxW in 0..1."""
    m3 = m[..., None]; return cv2.convertScaleAbs(a.astype(np.float32) * (1 - m3) + b.astype(np.float32) * m3)


def _area_mask(p, holder, iw, ih):
    """0..1 float mask of the effect's own area (reuses the clip-mask shapes, including the hand-drawn Custom shape)."""
    from .renderer import mask_alpha, MASK_DEFAULT
    sh = holder.get("mask", "Rect")
    if sh in (None, "None"): return None
    ms = dict(MASK_DEFAULT, **(holder.get("mask_shape") or {}))
    m = mask_alpha(sh, ms, iw, ih, holder.get("mask_feather", 0))
    return None if m is None else m.astype(np.float32) * (1 / 255)


# ───────────────────────── color ─────────────────────────


# ───────────────────────── blur ─────────────────────────

def _blur_rgb_only(img, sigma):
    """Blur only the colour channels; keep the original alpha edge sharp."""
    if sigma < 0.3: return img
    out = img.copy()
    out[..., :3] = cv2.GaussianBlur(np.ascontiguousarray(img[..., :3]),
                                    (int(sigma*3)*2+1, int(sigma*3)*2+1), sigma)
    return out


# ───────────────────────── distort / stylize ─────────────────────────
def fx_rgb_split(img, p, ctx):
    d = p["amount"] * ctx.k
    if d < 0.3: return img
    mode = p.get("mode", "directional")
    h, w = img.shape[:2]; out = img.copy()
    if mode == "zoom":
        # Zoom split: R zoomed in, B zoomed out from center
        cx, cy = w * p.get("cx", 50.0) / 100, h * p.get("cy", 50.0) / 100
        for ch, scale in ((2, 1 + d / w), (0, 1 - d / w)):
            if scale <= 0: continue
            M = np.array([[scale, 0, cx * (1 - scale)], [0, scale, cy * (1 - scale)]], np.float32)
            out[..., ch] = cv2.warpAffine(np.ascontiguousarray(img[..., ch]), M, (w, h),
                                           flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    elif mode == "radial":
        # Radial: channels displaced outward/inward from center
        cx, cy = w * p.get("cx", 50.0) / 100, h * p.get("cy", 50.0) / 100
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - cx) / (w / 2); ny = (yy - cy) / (h / 2)
        length = np.maximum(np.sqrt(nx**2 + ny**2), 1e-5)
        for ch, sgn in ((2, 1.0), (0, -1.0)):
            ox = xx + nx / length * d * sgn
            oy = yy + ny / length * d * sgn
            out[..., ch] = cv2.remap(np.ascontiguousarray(img[..., ch]),
                                      ox, oy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    else:  # directional (default)
        th = math.radians(p["angle"]); dx, dy = math.cos(th) * d, math.sin(th) * d
        for ch, sgn in ((2, 1.0), (0, -1.0)):
            M = np.array([[1, 0, dx * sgn], [0, 1, dy * sgn]], np.float32)
            out[..., ch] = cv2.warpAffine(np.ascontiguousarray(img[..., ch]), M, (w, h),
                                           flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out


_VIG = {}


# ───────────────────────── key ─────────────────────────


# ───────────────────────── hue shift ─────────────────────────


# ───────────────────────── color temperature ─────────────────────────


# ───────────────────────── highlights & shadows ─────────────────────────


# ───────────────────────── posterize ─────────────────────────


# ───────────────────────── threshold ─────────────────────────


# ───────────────────────── find edges ─────────────────────────


# ───────────────────────── luma key ─────────────────────────


# ───────────────────────── mirror ─────────────────────────


# ───────────────────────── zoom blur ─────────────────────────


# ───────────────────────── spin blur ─────────────────────────


# ───────────────────────── inner glow ─────────────────────────


# ───────────────────────── soft glow ─────────────────────────


# ───────────────────────── dark glow ─────────────────────────


# ───────────────────────── offset ─────────────────────────


# ───────────────────────── flip layer ─────────────────────────


# ───────────────────────── swirl ─────────────────────────


# ───────────────────────── spherize ─────────────────────────


# ───────────────────────── noise ─────────────────────────


# ───────────────────────── dissolve ─────────────────────────


# ───────────────────────── gradient map ─────────────────────────


# ───────────────────────── replace color ─────────────────────────


# ───────────────────────── copy background ─────────────────────────


# ───────────────────────── registry ─────────────────────────
# ── Color ──────────────────────────────────────────────────────────────────────

# ── Blur ───────────────────────────────────────────────────────────────────────

# ── Distort ────────────────────────────────────────────────────────────────────

# ── Stylize ────────────────────────────────────────────────────────────────────

# ── Transform ──────────────────────────────────────────────────────────────────

# ── Key ────────────────────────────────────────────────────────────────────────

from . import smartkey as _sk


try:
    from . import fxpack      # the effect pack (about 150 more effects); a problem in it must never stop the program
except Exception as _ex:
    print("[effects] the effect pack was not loaded:", _ex)

try:
    from .fxpack.custom import load_all as _load_custom_fx
    _load_custom_fx()          # load user-built effects from ~/.minicut/custom_effects/
except Exception as _ex:
    print("[effects] custom effects not loaded:", _ex)


# Patch 34: fast 8-bit versions of the most used effects replace the float32 / GPU round-trip ones (see fastfx.py). Any problem -> the old ones stay.
try:
    from . import fastfx as _fastfx
    _fastfx.install(FX); _lane_ok = _fastfx.lane_ok
except Exception as _ex:
    print("[effects] fast effects not installed:", _ex)

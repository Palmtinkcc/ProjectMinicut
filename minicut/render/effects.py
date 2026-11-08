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
    pick = "gl" if _GLX.is_export() else _GLX.CHOOSER.pick(key); t0 = _GLX.now_ms()
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
def fx_tint(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    col = QColor(p["color"])
    if _GPU_FX:
        try:
            return gpu_tint(img, (col.blueF(), col.greenF(), col.redF()), a)
        except (GpuFxUnavailable, Exception):
            pass
    tc = np.array([col.blueF(), col.greenF(), col.redF()], np.float32)
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
    br = p["brightness"]; co = p["contrast"]; sa = p["saturation"]; hu = p["hue"]
    temp = p.get("temperature", 0.0)
    vib  = p.get("vibrance", 0.0)
    hi   = p.get("highlights", 0.0)
    sh   = p.get("shadows", 0.0)
    if br == 0 and co == 0 and sa == 0 and hu == 0 and temp == 0 and vib == 0 and hi == 0 and sh == 0:
        return img
    # GPU fast path: handles brightness/contrast/saturation/hue in one pass
    # Falls back to CPU for temperature/vibrance/highlights/shadows (rare controls)
    if _GPU_FX and temp == 0 and vib == 0 and hi == 0 and sh == 0:
        try:
            return gpu_adjust(img, br=br, co=co, sa=sa, hu=hu)
        except (GpuFxUnavailable, Exception):
            pass
    f = img[..., :3].astype(np.float32) * (1 / 255)
    # brightness + contrast (lifted shadows approach like AM)
    f = (f - .5) * (1 + co / 100) + .5 + br / 200
    # temperature: shift R and B in opposite directions (warm = more R, less B)
    if temp != 0:
        t = temp / 100.0
        f[..., 2] = np.clip(f[..., 2] + t * 0.15, 0, 1)   # R up when warm
        f[..., 0] = np.clip(f[..., 0] - t * 0.15, 0, 1)   # B down when warm
    # highlights / shadows lift
    if hi != 0 or sh != 0:
        lum = (f[..., 0] * 0.114 + f[..., 1] * 0.587 + f[..., 2] * 0.299)  # luminance
        hi_mask = np.clip((lum - 0.5) * 2, 0, 1)[..., None]   # 0 at mid, 1 at white
        sh_mask = np.clip((0.5 - lum) * 2, 0, 1)[..., None]   # 0 at mid, 1 at black
        f = np.clip(f + hi_mask * (hi / 200.0) + sh_mask * (sh / 200.0), 0, 1)
    if sa != 0 or hu != 0 or vib != 0:
        f8 = np.clip(f * 255, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(f8, cv2.COLOR_BGR2HSV).astype(np.float32)
        if hu != 0: hsv[..., 0] = (hsv[..., 0] + hu / 2.0) % 180
        if sa != 0: hsv[..., 1] = np.clip(hsv[..., 1] * (1 + sa / 100), 0, 255)
        if vib != 0:
            # vibrance: boost low-saturation pixels more (Lightroom-style)
            sat_norm = hsv[..., 1] / 255.0
            vib_boost = (1.0 - sat_norm) * (vib / 100.0)
            hsv[..., 1] = np.clip(hsv[..., 1] + vib_boost * 255, 0, 255)
        f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) * (1 / 255)
    out = img.copy(); out[..., :3] = np.clip(f * 255 + .5, 0, 255).astype(np.uint8); return out


def fx_bw(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    if _GPU_FX:
        try: return gpu_bw(img, a)
        except (GpuFxUnavailable, Exception): pass
    f = img[..., :3].astype(np.float32); g = (f @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
    out = img.copy(); out[..., :3] = np.clip(f + (g - f) * a + .5, 0, 255).astype(np.uint8); return out


def fx_invert(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    f = img[..., :3].astype(np.float32); out = img.copy(); out[..., :3] = np.clip(f + (255 - 2 * f) * a + .5, 0, 255).astype(np.uint8); return out


# ───────────────────────── blur ─────────────────────────
def fx_blur(img, p, ctx):
    amt = p["amount"] * ctx.k
    if amt < 0.3: return img
    sx = amt * p["x_blur"] / 100.0
    sy = amt * p["y_blur"] / 100.0
    if sx < 0.3 and sy < 0.3: return img
    if abs(sx - sy) < 0.5:
        # isotropic fast path
        return blur_bgra(img, sx) if p.get("alpha_blur", False) else _blur_rgb_only(img, sx)
    # anisotropic: blur each axis separately
    pm, a = _premul(img)
    def _gauss1d(arr, sigma, axis):
        if sigma < 0.3: return arr
        kk = int(sigma * 3) * 2 + 1
        if axis == 0: return cv2.GaussianBlur(arr, (1, kk), sigma)
        return cv2.GaussianBlur(arr, (kk, 1), sigma)
    rgb = _gauss1d(_gauss1d(pm, sx, 1), sy, 0)
    al  = _gauss1d(_gauss1d(a,  sx, 1), sy, 0) if p.get("alpha_blur", False) else a
    return _unpremul(rgb, al)

def _blur_rgb_only(img, sigma):
    """Blur only the colour channels; keep the original alpha edge sharp."""
    if sigma < 0.3: return img
    out = img.copy()
    out[..., :3] = cv2.GaussianBlur(np.ascontiguousarray(img[..., :3]),
                                    (int(sigma*3)*2+1, int(sigma*3)*2+1), sigma)
    return out


def fx_motion_blur(img, p, ctx):
    n = int(p["length"] * ctx.k)
    if n < 2: return img
    h, w = img.shape[:2]; n = min(n, max(h, w) // 2)
    bidirectional = p.get("bidirectional", False)
    sc = max(1.0, n / 14.0)
    pm, a = _premul(img)
    if sc > 1:
        sw, sh = max(1, int(w / sc)), max(1, int(h / sc))
        pm = cv2.resize(pm, (sw, sh), interpolation=cv2.INTER_AREA)
        a  = cv2.resize(a,  (sw, sh), interpolation=cv2.INTER_AREA)
    m = max(3, int(round(n / sc))) | 1; ker = np.zeros((m, m), np.float32)
    if bidirectional:
        ker[m // 2, :] = 1   # already symmetric
    else:
        ker[m // 2, m // 2:] = 1    # trailing blur only (direction of motion)
    ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((m / 2 - .5, m / 2 - .5), -p["angle"], 1), (m, m))
    ker /= max(float(ker.sum()), 1e-6)
    pad = m // 2
    def run(x): return cv2.filter2D(cv2.copyMakeBorder(x, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0), -1, ker)[pad:-pad, pad:-pad]
    pm, a = run(pm), run(a)
    if sc > 1:
        pm = cv2.resize(pm, (w, h), interpolation=cv2.INTER_LINEAR)
        a  = cv2.resize(a,  (w, h), interpolation=cv2.INTER_LINEAR)
    return _unpremul(pm, a)


def fx_radial_blur(img, p, ctx):
    amt = p["amount"] / 100
    if amt <= 0.002: return img
    mode = p.get("mode", "zoom")   # zoom | spin
    h, w = img.shape[:2]; cx, cy = w * p["cx"] / 100, h * p["cy"] / 100
    steps = 6 if ctx.fast else 14
    pm, a = _premul(img); acc = np.zeros_like(pm); acca = np.zeros_like(a)
    if mode == "spin":
        max_angle = amt * 0.3   # max rotation in radians
        for i in range(steps):
            ang = max_angle * i / max(1, steps - 1)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            M = np.array([[cos_a, -sin_a, cx - cx * cos_a + cy * sin_a],
                          [sin_a,  cos_a, cy - cx * sin_a - cy * cos_a + cy]], np.float32)
            acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    else:  # zoom (original)
        zoom_amt = amt * 0.25
        for i in range(steps):
            s = 1 + zoom_amt * i / max(1, steps - 1)
            M = np.array([[s, 0, cx - cx * s], [0, s, cy - cy * s]], np.float32)
            acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)


def fx_area_blur(img, p, ctx):
    ih, iw = img.shape[:2]; m = _area_mask(p, ctx.holder, iw, ih); blurred = blur_bgra(img, p["amount"] * ctx.k)
    return blurred if m is None else _mix(img, blurred, m)


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
    radius    = max(0.4, p.get("radius", 1.0) * ctx.k)
    threshold = p.get("threshold", 0.0) / 255.0
    if _GPU_FX:
        try:
            blurred_bgra = gpu_gaussian_blur(img, radius)
            return gpu_sharpen(img, blurred_bgra, a, threshold)
        except (GpuFxUnavailable, Exception):
            pass
    rgb = img[..., :3].astype(np.float32)
    blurred = cv2.GaussianBlur(np.ascontiguousarray(img[..., :3]), (0, 0), radius).astype(np.float32)
    diff = rgb - blurred
    if threshold > 0:
        edge = np.abs(diff).max(axis=2) / 255.0
        thr_mask = np.clip((edge - threshold) / max(1e-4, threshold), 0, 1)[..., None]
        sharpened = rgb + diff * a * thr_mask
    else:
        sharpened = rgb + diff * a
    out = img.copy(); out[..., :3] = np.clip(sharpened + .5, 0, 255).astype(np.uint8); return out


_VIG = {}


def fx_vignette(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]
    rnd  = p.get("roundness", 50.0) / 100.0
    col  = p.get("color", "#000000")
    mode = p.get("mode", "darken")
    if _GPU_FX:
        try:
            from ..shared.deps import QColor as _QC
            c = _QC(col)
            return gpu_vignette(img, a, p["softness"] / 100.0, rnd,
                                (c.blueF(), c.greenF(), c.redF()),
                                alpha_mode=(mode == "alpha"))
        except (GpuFxUnavailable, Exception):
            pass
    key  = (h, w, round(a, 3), round(p["softness"], 1), round(rnd, 2))
    mask = _VIG.get(key)
    if mask is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - w / 2) / (w / 2); ny = (yy - h / 2) / (h / 2)
        # roundness: 0=max(|x|,|y|) box, 1=sqrt(x²+y²) circle
        r_box = np.maximum(np.abs(nx), np.abs(ny))
        r_cir = np.sqrt(nx ** 2 + ny ** 2) / 1.4142
        r = r_box + (r_cir - r_box) * rnd
        start = 1.0 - p["softness"] / 100 * 0.95
        mask = np.clip((r - start) / max(1e-3, 1 - start), 0, 1) ** 2
        _VIG[key] = mask
        while len(_VIG) > 12: _VIG.pop(next(iter(_VIG)))
    v = (mask * a).astype(np.float32)   # 0=no vignette, 1=full
    out = img.copy()
    if mode == "alpha":
        out[..., 3] = np.clip(img[..., 3].astype(np.float32) * (1 - v) + .5, 0, 255).astype(np.uint8)
    else:
        from ..shared.deps import QColor as _QC
        c = _QC(col)
        tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
        f  = img[..., :3].astype(np.float32)
        blended = f * (1 - v[..., None]) + tc * 255 * v[..., None]
        out[..., :3] = np.clip(blended + .5, 0, 255).astype(np.uint8)
    return out


def fx_glow(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k)
    thr    = p["threshold"] / 100
    blend  = p.get("blend_mode", "screen")
    col    = p.get("color", None)
    if _GPU_FX:
        try:
            blurred = gpu_gaussian_blur(img, radius)
            tint = (1.0, 1.0, 1.0)
            if col:
                from ..shared.deps import QColor as _QC
                c = _QC(col); tint = (c.redF(), c.greenF(), c.blueF())
            return gpu_glow(img, blurred, a, thr, tint_rgb=tint, add=(blend == "add"))
        except (GpuFxUnavailable, Exception):
            pass
    f = img[..., :3].astype(np.float32)
    lum = (f @ np.array([0.114, 0.587, 0.299], np.float32)) * (1 / 255)
    bright_mask = np.clip((lum - thr) / max(1e-3, 1 - thr), 0, 1)[..., None]
    bright = bright_mask * f
    glow_rgb = _gauss(bright, radius)
    if col:
        from ..shared.deps import QColor as _QC
        c = _QC(col); tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
        glow_rgb = glow_rgb * (1 / max(glow_rgb.max(), 1e-4)) * tc * 255 * (glow_rgb.max() / 255)
    out = img.copy()
    if blend == "add":
        out[..., :3] = np.clip(f + glow_rgb * a + .5, 0, 255).astype(np.uint8)
    else:
        out[..., :3] = np.clip(255 - (255 - f) * (255 - glow_rgb * a) / 255 + .5, 0, 255).astype(np.uint8)
    return out


def fx_grain(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]; s = max(1, int(round(p["size"] * ctx.k)))
    color_grain = p.get("color_grain", False)
    rng = np.random.default_rng(int(ctx.lt * 24) * 104729 + 17)
    gh, gw = max(1, h // s), max(1, w // s)
    if color_grain:
        n = rng.standard_normal((gh, gw, 3)).astype(np.float32)
    else:
        n = rng.standard_normal((gh, gw)).astype(np.float32)[..., None] * np.ones(3, np.float32)
    if s > 1: n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)
    if n.ndim == 2: n = n[..., None]
    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) + n * 40 * a + .5, 0, 255).astype(np.uint8); return out


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


# ───────────────────────── hue shift ─────────────────────────
def fx_hue_shift(img, p, ctx):
    shift = p["shift"]
    if shift == 0: return img
    rgb = np.ascontiguousarray(img[..., :3])
    hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + shift / 2.0) % 180
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR); return out


# ───────────────────────── color temperature ─────────────────────────
def fx_color_temperature(img, p, ctx):
    """Warm (positive) = more orange, Cool (negative) = more blue. Matches AM's Color Temperature."""
    temp = p["temperature"] / 100.0
    tint = p.get("tint", 0.0) / 100.0   # green (pos) / magenta (neg) axis
    if temp == 0 and tint == 0: return img
    f = img[..., :3].astype(np.float32)
    # Temperature: warm shifts R up and B down along a curve that feels perceptually linear
    f[..., 2] = np.clip(f[..., 2] + temp * 30, 0, 255)   # R
    f[..., 0] = np.clip(f[..., 0] - temp * 30, 0, 255)   # B
    # Tint: green/magenta
    f[..., 1] = np.clip(f[..., 1] + tint * 20, 0, 255)   # G
    f[..., 0] = np.clip(f[..., 0] - tint * 20, 0, 255)   # B (opposed)
    out = img.copy(); out[..., :3] = np.clip(f + .5, 0, 255).astype(np.uint8); return out


# ───────────────────────── highlights & shadows ─────────────────────────
def fx_highlights_shadows(img, p, ctx):
    """Separate highlights and shadows control — like Lightroom / AM Highlights and Shadows."""
    hi = p["highlights"] / 100.0
    sh = p["shadows"] / 100.0
    if hi == 0 and sh == 0: return img
    f = img[..., :3].astype(np.float32) * (1 / 255)
    lum = f[..., 0] * 0.114 + f[..., 1] * 0.587 + f[..., 2] * 0.299
    hi_mask = np.clip((lum - 0.5) * 2, 0, 1)[..., None]
    sh_mask = np.clip((0.5 - lum) * 2, 0, 1)[..., None]
    f = np.clip(f + hi_mask * hi * 0.5 + sh_mask * sh * 0.5, 0, 1)
    out = img.copy(); out[..., :3] = (f * 255 + .5).astype(np.uint8); return out


# ───────────────────────── posterize ─────────────────────────
def fx_posterize(img, p, ctx):
    levels = max(2, int(p["levels"]))
    step = 255.0 / (levels - 1)
    rgb = img[..., :3]
    posterized = (np.round(rgb.astype(np.float32) / step) * step).astype(np.uint8)
    out = img.copy(); out[..., :3] = posterized; return out


# ───────────────────────── threshold ─────────────────────────
def fx_threshold(img, p, ctx):
    thr = int(p["level"])
    invert = p.get("invert", False)
    rgb = img[..., :3].astype(np.float32)
    lum = (rgb @ np.array([0.114, 0.587, 0.299], np.float32))
    mask = (lum >= thr).astype(np.uint8) * 255
    if invert: mask = 255 - mask
    out = img.copy(); out[..., :3] = mask[..., None]; return out


# ───────────────────────── find edges ─────────────────────────
def fx_find_edges(img, p, ctx):
    amount = p["amount"] / 100.0
    invert = p.get("invert", False)
    mode   = p.get("mode", "luminance")   # luminance | color
    sigma  = max(0.4, p.get("softness", 1.0) * ctx.k)
    rgb = np.ascontiguousarray(img[..., :3])
    if mode == "color":
        blurred = cv2.GaussianBlur(rgb, (0, 0), sigma).astype(np.float32)
        edges = np.abs(rgb.astype(np.float32) - blurred)
        edges = np.clip(edges * (amount * 4), 0, 255).astype(np.uint8)
    else:
        gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
        blurred_g = cv2.GaussianBlur(gray, (0, 0), sigma)
        edge_g = cv2.Laplacian(blurred_g, cv2.CV_32F)
        edge_g = np.clip(np.abs(edge_g) * amount * 4, 0, 255).astype(np.uint8)
        edges = cv2.cvtColor(edge_g, cv2.COLOR_GRAY2BGR)
    if invert: edges = 255 - edges
    out = img.copy(); out[..., :3] = edges; return out


# ───────────────────────── luma key ─────────────────────────
def fx_luma_key(img, p, ctx):
    """Key out pixels by luminance. Mode bright = keep brights, dark = keep darks."""
    thr  = p["threshold"] / 100.0
    soft = max(0.001, p.get("softness", 10.0) / 100.0)
    mode = p.get("mode", "dark")   # dark | bright
    rgb  = img[..., :3].astype(np.float32) * (1 / 255)
    lum  = rgb[..., 0] * 0.114 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.299
    if mode == "bright":
        alpha = np.clip((thr - lum) / soft, 0, 1)
    else:  # dark: key out darks
        alpha = np.clip((lum - thr) / soft, 0, 1)
    out = img.copy()
    out[..., 3] = (img[..., 3].astype(np.float32) * alpha + .5).astype(np.uint8)
    return out


# ───────────────────────── mirror ─────────────────────────
def fx_mirror(img, p, ctx):
    axis = p.get("axis", "horizontal")   # horizontal | vertical | both
    cx   = p.get("cx", 50.0) / 100.0
    cy   = p.get("cy", 50.0) / 100.0
    h, w = img.shape[:2]
    out = img.copy()
    if axis in ("horizontal", "both"):
        split_x = int(w * cx)
        left = out[:, :split_x]
        flipped = cv2.flip(left, 1)
        right_w = w - split_x
        flipped_cropped = flipped[:, max(0, flipped.shape[1] - right_w):]
        fw = min(right_w, flipped_cropped.shape[1])
        out[:, split_x:split_x + fw] = flipped_cropped[:, :fw]
    if axis in ("vertical", "both"):
        split_y = int(h * cy)
        top = out[:split_y, :]
        flipped = cv2.flip(top, 0)
        bot_h = h - split_y
        flipped_cropped = flipped[max(0, flipped.shape[0] - bot_h):, :]
        fh = min(bot_h, flipped_cropped.shape[0])
        out[split_y:split_y + fh, :] = flipped_cropped[:fh, :]
    return out


# ───────────────────────── zoom blur ─────────────────────────
def fx_zoom_blur(img, p, ctx):
    """Radial zoom blur from a center point — like AM's Zoom Blur."""
    amt   = p["amount"] / 100.0
    if amt <= 0.001: return img
    cx    = p.get("cx", 50.0) / 100.0
    cy    = p.get("cy", 50.0) / 100.0
    steps = 5 if ctx.fast else 12
    if _GPU_FX:
        try:
            return gpu_zoom_blur(img, amt, cx, cy, steps)
        except (GpuFxUnavailable, Exception):
            pass
    h, w  = img.shape[:2]; ocx, ocy = w * cx, h * cy
    pm, a = _premul(img)
    acc   = np.zeros_like(pm); acca = np.zeros_like(a)
    for i in range(steps):
        s = 1.0 + amt * 0.5 * i / max(1, steps - 1)
        M = np.array([[s, 0, ocx * (1 - s)], [0, s, ocy * (1 - s)]], np.float32)
        acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)


# ───────────────────────── spin blur ─────────────────────────
def fx_spin_blur(img, p, ctx):
    """Rotational motion blur around a center point."""
    angle_deg = p["angle"]
    if abs(angle_deg) < 0.1: return img
    cx    = p.get("cx", 50.0) / 100.0
    cy    = p.get("cy", 50.0) / 100.0
    steps = 5 if ctx.fast else 12
    if _GPU_FX:
        try:
            return gpu_spin_blur(img, math.radians(angle_deg), cx, cy, steps)
        except (GpuFxUnavailable, Exception):
            pass
    h, w  = img.shape[:2]; ocx, ocy = w * cx, h * cy
    pm, a = _premul(img)
    acc   = np.zeros_like(pm); acca = np.zeros_like(a)
    for i in range(steps):
        ang = math.radians(angle_deg * i / max(1, steps - 1))
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        M = np.array([[cos_a, -sin_a, ocx - ocx * cos_a + ocy * sin_a],
                      [sin_a,  cos_a, ocy - ocx * sin_a - ocy * cos_a + ocy]], np.float32)
        acc  += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        acca += cv2.warpAffine(a,  M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return _unpremul(acc / steps, acca / steps)


# ───────────────────────── inner glow ─────────────────────────
def fx_inner_glow(img, p, ctx):
    """Glow that emanates inward from the alpha edge of the layer."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k)
    col    = p.get("color", "#ffffff")
    from ..shared.deps import QColor as _QC
    c = _QC(col); tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32) * 255
    alpha  = img[..., 3].astype(np.float32) / 255.0
    # Erode alpha and subtract — difference is the inner edge region
    eroded = cv2.GaussianBlur(alpha, (0, 0), radius)
    inner  = np.clip(alpha - eroded, 0, 1) * amount * 2
    inner  = np.clip(inner, 0, 1)
    out    = img.copy()
    f      = img[..., :3].astype(np.float32)
    for ch in range(3):
        out[..., ch] = np.clip(f[..., ch] + inner * tc[ch], 0, 255).astype(np.uint8)
    return out


# ───────────────────────── soft glow ─────────────────────────
def fx_soft_glow(img, p, ctx):
    """Dreamy soft glow: blurred screen overlay — AM's Soft Glow."""
    amount   = p["amount"] / 100.0
    if amount <= 0: return img
    radius   = max(0.5, p["radius"] * ctx.k)
    softness = p.get("softness", 50.0) / 100.0
    f    = img[..., :3].astype(np.float32)
    soft = _gauss(f, radius)
    # Screen blend of soft over original
    screened = 255 - (255 - f) * (255 - soft * softness) / 255
    blended  = f + (screened - f) * amount
    out = img.copy(); out[..., :3] = np.clip(blended + .5, 0, 255).astype(np.uint8); return out


# ───────────────────────── dark glow ─────────────────────────
def fx_dark_glow(img, p, ctx):
    """Shadow-side glow: multiplies dark areas — inverse of Glow."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    radius = max(0.5, p["radius"] * ctx.k)
    thr    = p.get("threshold", 40.0) / 100.0
    f = img[..., :3].astype(np.float32)
    lum = (f @ np.array([0.114, 0.587, 0.299], np.float32)) * (1 / 255)
    dark_mask = np.clip((thr - lum) / max(1e-3, thr), 0, 1)[..., None]
    dark_px   = dark_mask * (255 - f)
    spread    = _gauss(dark_px, radius)
    out = img.copy()
    out[..., :3] = np.clip(f - spread * amount + .5, 0, 255).astype(np.uint8)
    return out


# ───────────────────────── offset ─────────────────────────
def fx_offset(img, p, ctx):
    """Shift the layer with wrap-around (tile) — AM's Offset."""
    h, w  = img.shape[:2]
    ox    = int(round(p["x"] * ctx.k))
    oy    = int(round(p["y"] * ctx.k))
    wrap  = p.get("wrap", True)
    if ox == 0 and oy == 0: return img
    if wrap:
        out = img.copy()
        out[..., :] = np.roll(np.roll(img, ox, axis=1), oy, axis=0)
    else:
        M   = np.array([[1, 0, float(ox)], [0, 1, float(oy)]], np.float32)
        out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return out


# ───────────────────────── flip layer ─────────────────────────
def fx_flip_layer(img, p, ctx):
    axis = p.get("axis", "horizontal")
    if axis == "horizontal": return cv2.flip(img, 1)
    if axis == "vertical":   return cv2.flip(img, 0)
    return cv2.flip(img, -1)   # both


# ───────────────────────── swirl ─────────────────────────
def fx_swirl(img, p, ctx):
    amount = p["amount"]
    if abs(amount) < 0.1: return img
    radius = p.get("radius", 50.0) / 100.0
    h, w   = img.shape[:2]; cx, cy = w / 2, h / 2
    max_r  = min(w, h) * radius / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx; dy = yy - cy; r = np.sqrt(dx**2 + dy**2)
    angle = amount * np.maximum(0, 1 - r / max(1, max_r))
    cos_a = np.cos(angle); sin_a = np.sin(angle)
    src_x = cx + cos_a * dx - sin_a * dy
    src_y = cy + sin_a * dx + cos_a * dy
    return cv2.remap(img, src_x, src_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


# ───────────────────────── spherize ─────────────────────────
def fx_spherize(img, p, ctx):
    amount = p["amount"] / 100.0
    if abs(amount) < 0.01: return img
    h, w   = img.shape[:2]; cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - cx) / cx; ny = (yy - cy) / cy
    r2 = nx**2 + ny**2
    inside = r2 < 1.0
    r = np.sqrt(np.where(inside, r2, 1.0))
    factor = np.where(inside, 1.0 - (1.0 - r) * amount, 1.0)
    src_x  = np.clip(cx + nx * factor * cx, 0, w - 1)
    src_y  = np.clip(cy + ny * factor * cy, 0, h - 1)
    return cv2.remap(img, src_x.astype(np.float32), src_y.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ───────────────────────── noise ─────────────────────────
def fx_noise(img, p, ctx):
    """Block noise / TV static — different from film grain."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    h, w   = img.shape[:2]
    rng    = np.random.default_rng(int(ctx.lt * 30) * 48611 + 7)
    noise  = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    out    = img.copy()
    out[..., :3] = np.clip(img[..., :3].astype(np.float32) * (1 - amount) +
                           noise.astype(np.float32) * amount + .5, 0, 255).astype(np.uint8)
    return out


# ───────────────────────── dissolve ─────────────────────────
def fx_dissolve(img, p, ctx):
    """Random pixel alpha dissolve — AM's Dissolve/Block Dissolve."""
    amount = p["amount"] / 100.0
    if amount <= 0: return img
    h, w   = img.shape[:2]
    rng    = np.random.default_rng(int(ctx.lt * 24) * 65537 + 13)
    mask   = rng.random((h, w), dtype=np.float32)
    keep   = (mask >= amount).astype(np.uint8) * 255
    out    = img.copy()
    out[..., 3] = (img[..., 3].astype(np.float32) * (keep / 255.0) + .5).astype(np.uint8)
    return out


# ───────────────────────── gradient map ─────────────────────────
def fx_gradient_map(img, p, ctx):
    """Map luminance to a two-color gradient — like AM's Gradient Map / Spectral Map."""
    col_lo = p.get("color_lo", "#000000")
    col_hi = p.get("color_hi", "#ffffff")
    amount = p.get("amount", 100.0) / 100.0
    from ..shared.deps import QColor as _QC
    clo = _QC(col_lo); chi = _QC(col_hi)
    lo  = np.array([clo.blueF(), clo.greenF(), clo.redF()], np.float32) * 255
    hi  = np.array([chi.blueF(), chi.greenF(), chi.redF()], np.float32) * 255
    rgb = img[..., :3].astype(np.float32)
    lum = (rgb @ np.array([0.114, 0.587, 0.299], np.float32)) / 255.0
    mapped = lo[None, None, :] + lum[..., None] * (hi - lo)[None, None, :]
    out = img.copy()
    out[..., :3] = np.clip(rgb * (1 - amount) + mapped * amount + .5, 0, 255).astype(np.uint8)
    return out


# ───────────────────────── replace color ─────────────────────────
def fx_replace_color(img, p, ctx):
    """Replace a chosen hue range with another color — AM's Replace Color."""
    src_col  = p.get("source_color", "#ff0000")
    dst_col  = p.get("dest_color",   "#0000ff")
    tol      = p.get("tolerance", 30)
    softness = p.get("softness", 10)
    from ..shared.deps import QColor as _QC
    sc = _QC(src_col); dc = _QC(dst_col)
    shsv = cv2.cvtColor(np.uint8([[[sc.blue(), sc.green(), sc.red()]]]), cv2.COLOR_BGR2HSV)[0, 0]
    rgb  = np.ascontiguousarray(img[..., :3])
    hsv  = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV).astype(np.float32)
    dh   = np.abs(hsv[..., 0].astype(np.float32) - float(shsv[0]))
    dh   = np.minimum(dh, 180 - dh)
    # Soft selection mask
    soft_half = max(1, softness / 2)
    sel  = np.clip(1 - (dh - (tol - soft_half)) / soft_half, 0, 1)
    dest = np.array([dc.blueF(), dc.greenF(), dc.redF()], np.float32) * 255
    out  = img.copy()
    for ch in range(3):
        out[..., ch] = np.clip(rgb[..., ch].astype(np.float32) * (1 - sel) + dest[ch] * sel + .5, 0, 255).astype(np.uint8)
    return out


# ───────────────────────── copy background ─────────────────────────
def fx_copy_background(img, p, ctx):
    """Replace the layer with the composited background beneath it, masked by the layer's alpha.
    Effects applied AFTER this see the background pixels under the layer's shape — like an adjustment layer.
    fill=0  → pure adjustment layer (original layer content invisible, only bg copy shows through its mask).
    fill=100 → show 100% of the original layer on top of the bg copy (same as not using the effect).
    """
    h, w = img.shape[:2]
    bg = getattr(ctx, "bg", None)
    if bg is None:
        # No background provided (e.g. bottom layer); fall back to a black canvas
        bg = np.zeros((h, w, 3), np.uint8)

    # Resize the bg snapshot to match this layer's pixel dimensions if needed
    bh, bw = bg.shape[:2]
    if bh != h or bw != w:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)

    # bg is BGR; we need BGRA
    bg_bgra = cv2.cvtColor(bg, cv2.COLOR_BGR2BGRA)
    bg_bgra[..., 3] = 255

    fill = p["fill"] / 100.0   # 0..1

    if fill <= 0.0:
        # Pure adjustment layer: layer alpha becomes the copy mask, content replaced by bg
        out = bg_bgra.copy()
        out[..., 3] = img[..., 3]   # keep original layer's alpha as the mask
    else:
        # Blend original content over bg according to fill
        a = img[..., 3:4].astype(np.float32) / 255.0
        orig = img[..., :3].astype(np.float32)
        bg3  = bg_bgra[..., :3].astype(np.float32)
        merged = bg3 + (orig - bg3) * fill
        out = np.empty_like(img)
        out[..., :3] = np.clip(merged, 0, 255).astype(np.uint8)
        out[..., 3]  = img[..., 3]

    return out

register("copy_background", "Compositing", "Copy Background",
         [("fill", "Fill (original layer)", "float", 0.0, 0.0, 100.0)],
         fx_copy_background,
         help="Copies the composited background into the layer so that effects applied afterwards act on the background pixels within the layer's shape — turning the layer into an adjustment layer.",
         kw="adjustment layer backdrop composite")


# ───────────────────────── registry ─────────────────────────
# ── Color ──────────────────────────────────────────────────────────────────────
register("tint", "Color", "Tint",
         [("color", "Color", "color", "#2f7bff", None, None),
          ("amount", "Amount", "float", 50.0, 0.0, 100.0)],
         fx_tint)
register("curves", "Color", "Curves",
         [("curve", "Curves", "curve", copy.deepcopy(DEFAULT_CURVE), None, None)],
         fx_curves)
register("adjust", "Color", "Adjust",
         [("brightness",  "Brightness",  "float",  0.0, -100.0, 100.0),
          ("contrast",    "Contrast",    "float",  0.0, -100.0, 100.0),
          ("saturation",  "Saturation",  "float",  0.0, -100.0, 100.0),
          ("hue",         "Hue shift",   "float",  0.0, -180.0, 180.0),
          ("temperature", "Temperature", "float",  0.0, -100.0, 100.0),
          ("vibrance",    "Vibrance",    "float",  0.0, -100.0, 100.0),
          ("highlights",  "Highlights",  "float",  0.0, -100.0, 100.0),
          ("shadows",     "Shadows",     "float",  0.0, -100.0, 100.0)],
         fx_adjust,
         help="Full-featured color adjustment: brightness, contrast, saturation, hue, temperature, vibrance, highlights and shadows.")
register("bw", "Color", "Black & white",
         [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
         fx_bw)
register("invert", "Color", "Invert",
         [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
         fx_invert)
register("hue_shift", "Color", "Hue Shift",
         [("shift", "Hue shift", "float", 0.0, -180.0, 180.0)],
         fx_hue_shift,
         help="Shift all hues by a fixed amount. Keyframe it to cycle through the rainbow.")
register("color_temperature", "Color", "Color Temperature",
         [("temperature", "Temperature", "float", 0.0, -100.0, 100.0),
          ("tint",        "Tint",        "float", 0.0, -100.0, 100.0)],
         fx_color_temperature,
         help="Warm/Cool color temperature and Green/Magenta tint correction — like a camera WB dial.")
register("highlights_shadows", "Color", "Highlights & Shadows",
         [("highlights", "Highlights", "float", 0.0, -100.0, 100.0),
          ("shadows",    "Shadows",    "float", 0.0, -100.0, 100.0)],
         fx_highlights_shadows,
         help="Independently lift or pull the highlights and shadows — like Lightroom's HS controls.")
register("posterize", "Color", "Posterize",
         [("levels", "Levels", "int", 4, 2, 32)],
         fx_posterize,
         help="Reduce the number of tonal levels in the image.")
register("threshold", "Color", "Threshold",
         [("level",  "Level",  "int",  128, 0, 255),
          ("invert", "Invert", "bool", False, None, None)],
         fx_threshold,
         help="High-contrast black-and-white by luminance threshold.")
register("gradient_map", "Color", "Gradient Map",
         [("color_lo", "Shadow color",    "color", "#000000", None, None),
          ("color_hi", "Highlight color", "color", "#ffffff", None, None),
          ("amount",   "Amount",          "float", 100.0, 0.0, 100.0)],
         fx_gradient_map,
         help="Maps image luminance to a two-color gradient — good for duotones and tonal grading.")
register("replace_color", "Color", "Replace Color",
         [("source_color", "Source color", "color", "#ff0000", None, None),
          ("dest_color",   "Dest color",   "color", "#0000ff", None, None),
          ("tolerance",    "Tolerance",    "int",   30, 1, 90),
          ("softness",     "Softness",     "int",   10, 0, 60)],
         fx_replace_color,
         help="Replace a hue range with another color.")

# ── Blur ───────────────────────────────────────────────────────────────────────
register("blur", "Blur", "Gaussian Blur",
         [("amount",     "Amount",     "float", 12.0, 0.0, 200.0),
          ("x_blur",     "Blur X",     "float", 100.0, 0.0, 100.0),
          ("y_blur",     "Blur Y",     "float", 100.0, 0.0, 100.0),
          ("alpha_blur", "Blur Alpha", "bool",  False, None, None)],
         fx_blur,
         help="Gaussian blur with independent X/Y control and optional alpha-edge blur.")
register("motion_blur", "Blur", "Motion Blur",
         [("length",        "Length",        "float", 40.0, 0.0, 300.0),
          ("angle",         "Angle",         "float", 0.0, -180.0, 180.0),
          ("bidirectional", "Bidirectional", "bool",  False, None, None)],
         fx_motion_blur,
         help="Directional motion blur. Bidirectional mode blurs in both directions for a centered look.")
register("radial_blur", "Blur", "Radial Blur",
         [("amount", "Amount",   "float", 40.0, 0.0, 100.0),
          ("mode",   "Mode",     "choice", "zoom", [("zoom", "Zoom"), ("spin", "Spin")], None),
          ("cx",     "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",     "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_radial_blur,
         help="Zoom or spin radial blur from a movable center point.")
register("zoom_blur", "Blur", "Zoom Blur",
         [("amount", "Amount",   "float", 40.0, 0.0, 100.0),
          ("cx",     "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",     "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_zoom_blur,
         help="Radial zoom blur — great for speed lines or warp effects.")
register("spin_blur", "Blur", "Spin Blur",
         [("angle", "Angle",    "float", 15.0, -180.0, 180.0),
          ("cx",    "Center X", "float", 50.0, 0.0, 100.0),
          ("cy",    "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_spin_blur,
         help="Rotational motion blur around a center point.")
register("area_blur", "Blur", "Area Blur",
         [("amount", "Amount", "float", 25.0, 0.0, 100.0)],
         fx_area_blur, area=True)

# ── Distort ────────────────────────────────────────────────────────────────────
register("rgb_split", "Distort", "RGB Split",
         [("amount", "Distance", "float",  8.0,  0.0, 80.0),
          ("angle",  "Angle",    "float",  0.0, -180.0, 180.0),
          ("mode",   "Mode",     "choice", "directional",
           [("directional", "Directional"), ("zoom", "Zoom"), ("radial", "Radial")], None),
          ("cx", "Center X", "float", 50.0, 0.0, 100.0),
          ("cy", "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_rgb_split,
         help="Chromatic aberration with Directional, Zoom, and Radial modes.")
register("pixelate", "Distort", "Pixelate / Mosaic",
         [("size", "Block size", "float", 14.0, 1.0, 120.0)],
         fx_pixelate,
         help="Pixelate the image into square blocks — classic mosaic censor effect.")
register("glitch", "Distort", "Glitch",
         [("amount", "Amount", "float", 40.0, 0.0, 100.0),
          ("seed",   "Seed",   "int",   1,    0,   999)],
         fx_glitch)
register("mirror", "Distort", "Mirror",
         [("axis", "Axis", "choice", "horizontal",
           [("horizontal", "Horizontal"), ("vertical", "Vertical"), ("both", "Both")], None),
          ("cx", "Center X", "float", 50.0, 0.0, 100.0),
          ("cy", "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_mirror,
         help="Mirror the layer along a horizontal, vertical, or both axes.")
register("swirl", "Distort", "Swirl",
         [("amount", "Angle",  "float", 1.5, -10.0, 10.0),
          ("radius", "Radius", "float", 50.0, 1.0, 100.0)],
         fx_swirl,
         help="Swirl/twirl distortion around the layer center.")
register("spherize", "Distort", "Spherize",
         [("amount", "Amount", "float", 50.0, -100.0, 100.0)],
         fx_spherize,
         help="Wrap the layer around a sphere (positive=bulge, negative=pinch).")
register("offset", "Distort", "Offset",
         [("x",    "X",    "float", 0.0, -1000.0, 1000.0),
          ("y",    "Y",    "float", 0.0, -1000.0, 1000.0),
          ("wrap", "Wrap", "bool",  True, None, None)],
         fx_offset,
         help="Shift the layer with optional wrap-around tiling.")

# ── Stylize ────────────────────────────────────────────────────────────────────
register("sharpen", "Stylize", "Sharpen",
         [("amount",    "Amount",    "float", 60.0, 0.0, 300.0),
          ("radius",    "Radius",    "float", 1.0,  0.1, 10.0),
          ("threshold", "Threshold", "float", 0.0,  0.0, 50.0)],
         fx_sharpen,
         help="Unsharp mask sharpening with radius and threshold controls.")
register("vignette", "Stylize", "Vignette",
         [("amount",    "Amount",    "float",  50.0, 0.0, 100.0),
          ("softness",  "Softness",  "float",  60.0, 0.0, 100.0),
          ("roundness", "Roundness", "float",  50.0, 0.0, 100.0),
          ("color",     "Color",     "color",  "#000000", None, None),
          ("mode",      "Mode",      "choice", "darken",
           [("darken", "Darken"), ("color", "Color"), ("alpha", "Alpha")], None)],
         fx_vignette,
         help="Vignette with adjustable roundness, custom color, and alpha mode.")
register("glow", "Stylize", "Glow",
         [("amount",     "Amount",     "float",  60.0, 0.0, 100.0),
          ("radius",     "Radius",     "float",  20.0, 0.0, 100.0),
          ("threshold",  "Threshold",  "float",  60.0, 0.0, 100.0),
          ("blend_mode", "Blend mode", "choice", "screen",
           [("screen", "Screen"), ("add", "Add")], None),
          ("color",      "Color tint", "color",  "", None, None)],
         fx_glow,
         help="Glow with Screen/Add blend mode and optional color tint.")
register("soft_glow", "Stylize", "Soft Glow",
         [("amount",   "Amount",   "float", 60.0, 0.0, 100.0),
          ("radius",   "Radius",   "float", 25.0, 0.0, 100.0),
          ("softness", "Softness", "float", 50.0, 0.0, 100.0)],
         fx_soft_glow,
         help="Dreamy blurred screen-blend glow — softer and more diffuse than Glow.")
register("dark_glow", "Stylize", "Dark Glow",
         [("amount",    "Amount",    "float", 60.0, 0.0, 100.0),
          ("radius",    "Radius",    "float", 20.0, 0.0, 100.0),
          ("threshold", "Threshold", "float", 40.0, 0.0, 100.0)],
         fx_dark_glow,
         help="Inverse glow that spreads from shadows — creates moody, smoky dark edges.")
register("inner_glow", "Stylize", "Inner Glow",
         [("amount", "Amount", "float", 60.0, 0.0, 100.0),
          ("radius", "Radius", "float", 20.0, 0.0, 100.0),
          ("color",  "Color",  "color", "#ffffff", None, None)],
         fx_inner_glow,
         help="Glow emitted inward from the layer's alpha edge.")
register("grain", "Stylize", "Film Grain",
         [("amount",      "Amount",      "float", 25.0, 0.0, 100.0),
          ("size",        "Grain size",  "float", 1.0,  1.0, 10.0),
          ("color_grain", "Color grain", "bool",  False, None, None)],
         fx_grain,
         help="Film grain noise. Color grain adds per-channel color noise like real film stock.")
register("noise", "Stylize", "Noise",
         [("amount", "Amount", "float", 30.0, 0.0, 100.0)],
         fx_noise,
         help="Additive white noise / TV static.")
register("dissolve", "Stylize", "Dissolve",
         [("amount", "Amount", "float", 50.0, 0.0, 100.0)],
         fx_dissolve,
         help="Random pixel dissolve using the layer's existing alpha.")
register("find_edges", "Stylize", "Find Edges",
         [("amount",   "Amount",   "float",  60.0, 0.0, 100.0),
          ("softness", "Softness", "float",  1.0,  0.1, 10.0),
          ("mode",     "Mode",     "choice", "luminance",
           [("luminance", "Luminance"), ("color", "Color")], None),
          ("invert",   "Invert",   "bool",   False, None, None)],
         fx_find_edges,
         help="Detect and highlight edges. Combine with Copy Background for neon edge effects.")

# ── Transform ──────────────────────────────────────────────────────────────────
register("flip_layer", "Distort", "Flip Layer",
         [("axis", "Axis", "choice", "horizontal",
           [("horizontal", "Horizontal"), ("vertical", "Vertical"), ("both", "Both")], None)],
         fx_flip_layer,
         help="Flip the layer horizontally, vertically, or both.")

# ── Key ────────────────────────────────────────────────────────────────────────
register("chroma", "Key", "Chroma Key",
         [("color",     "Key color",  "color", "#00ff00", None, None),
          ("tolerance", "Tolerance",  "int",   55, 1, 180)],
         fx_chroma)
register("luma_key", "Key", "Luma Key",
         [("threshold", "Threshold", "float", 50.0, 0.0, 100.0),
          ("softness",  "Softness",  "float", 10.0, 0.1, 50.0),
          ("mode",      "Mode",      "choice", "dark",
           [("dark", "Key darks out"), ("bright", "Key brights out")], None)],
         fx_luma_key,
         help="Remove pixels by luminance. Key darks out = keep bright areas; Key brights out = keep darks.")

from . import smartkey as _sk
register("smart_key", "Key", "Better Chroma Key",
         [("mode", "Mode", "choice", "color", _sk.MODE_CHOICES, None),
          ("color", "Background color", "color", "#00ff00", None, None),
          ("tolerance", "Tolerance", "float", 35.0, 0.0, 100.0),
          ("softness", "Edge softness", "float", 25.0, 0.0, 100.0),
          ("spill", "Remove color spill", "float", 60.0, 0.0, 100.0),
          ("quality", "Render quality", "choice", "normal", _sk.QUALITY_CHOICES, None),
          ("edge_mode", "Edge color", "choice", "auto", _sk.EDGE_CHOICES, None),
          ("edge_color", "Edge color", "color", "#303030", None, None),
          ("edge_width", "Edge width", "float", 3.0, 0.0, 20.0),
          ("edge_amount", "Edge amount", "float", 70.0, 0.0, 100.0),
          ("choke", "Shrink / grow edge", "float", 0.0, -20.0, 20.0),
          ("feather", "Feather", "float", 0.0, 0.0, 20.0),
          ("view", "View", "choice", "result", _sk.VIEW_CHOICES, None)],
         _sk.fx_smart_key,
         help="Background color: pick the screen color; the edge of the subject is repainted so no green fringe is left. "
              "Select object: paint the object, press Render, and the clip is rendered with the background cut away (works on any background). "
              "Turn the effect off, delete it or press Undo and the original media comes back.")


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

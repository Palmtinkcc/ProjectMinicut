"""Custom Effect System — Patch 50
User-built effects stored in ~/.minicut/custom_effects/.
Each effect is a .mcfx file (JSON) containing:
  - metadata: id, name, category, description, author, version
  - params: list of parameter specs (same format as kit.F/I/C/B/CH)
  - graph: FX node graph (nodes + links)

At load time each .mcfx is compiled into a Python function and registered
in the main FX registry under "custom:<id>".  The compiled function is a
real Python callable — same signature as any fxpack effect — so it runs at
full speed, supports keyframes, and integrates with every feature (masks,
blend modes, export, proxy, etc.).

NODE TYPES available in the FX node editor:
  Image nodes:   input, output, blend, mask_alpha, crop, flip
  Color nodes:   brightness, contrast, hue_sat, curves_simple, tint, invert, bw, threshold
  Blur nodes:    gaussian, motion_blur_fx, radial_blur_fx, box_blur_node
  Distort nodes: displace_node, warp_noise, wave_warp_node, chromatic_ab
  Composite:     over, screen, multiply, add_blend, difference
  Utility:       param_float, param_int, param_color, param_bool
                 constant, math_node, mix, coord_offset
"""
from ..effects import FX, register as _register_fx
from ..fxpack.kit import *
import json, os, hashlib, re, types, traceback

CUSTOM_FX_DIR = os.path.join(os.path.expanduser("~"), ".minicut", "custom_effects")
CUSTOM_CATEGORIES_FILE = os.path.join(CUSTOM_FX_DIR, "_categories.json")

# registry: id -> {meta, graph, fn, error}
CUSTOM_REGISTRY: dict = {}

# ── FX node type specs ────────────────────────────────────────────────────────
# Each node type: title, inputs, outputs, params, compile_snippet
# compile_snippet: Python expression/statement template using {inputs} and {params}
# Inputs are named img0..imgN (BGRA uint8) or v0..vN (float/color).
# Output named 'out' (image) or 'val' (float).

FX_NODE_TYPES: dict = {
    # ── Image IO ──────────────────────────────────────────────────────────────
    "fx_input": {
        "cat": "Image", "title": "Image Input",
        "ins": [], "outs": ["Image"],
        "params": [],
        "out_type": "image",
        "snippet": "out = img",
    },
    "fx_output": {
        "cat": "Image", "title": "Image Output",
        "ins": [("Image", "image")], "outs": [],
        "params": [],
        "out_type": None,
        "snippet": "result = img0",
    },
    # ── Color ─────────────────────────────────────────────────────────────────
    "fx_brightness": {
        "cat": "Color", "title": "Brightness / Contrast",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("brightness", "Brightness", "float", 0.0, -100.0, 100.0),
                   ("contrast",   "Contrast",   "float", 0.0, -100.0, 100.0)],
        "out_type": "image",
        "snippet": (
            "out = _fx_bc(img0, {brightness}/100.0, {contrast}/100.0)"
        ),
    },
    "fx_hue_sat": {
        "cat": "Color", "title": "Hue / Saturation",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("hue", "Hue shift", "float", 0.0, -180.0, 180.0),
                   ("sat", "Saturation", "float", 0.0, -100.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_huesat(img0, {hue}, {sat}/100.0)",
    },
    "fx_tint_node": {
        "cat": "Color", "title": "Tint",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("color", "Color", "color", "#2f7bff"),
                   ("amount", "Amount", "float", 50.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_tint_node(img0, {color!r}, {amount}/100.0)",
    },
    "fx_invert_node": {
        "cat": "Color", "title": "Invert",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_invert_node(img0, {amount}/100.0)",
    },
    "fx_bw_node": {
        "cat": "Color", "title": "Black & White",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_bw_node(img0, {amount}/100.0)",
    },
    "fx_threshold": {
        "cat": "Color", "title": "Threshold",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("level", "Level", "float", 50.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_threshold(img0, {level}/100.0)",
    },
    # ── Blur ──────────────────────────────────────────────────────────────────
    "fx_blur_node": {
        "cat": "Blur", "title": "Gaussian Blur",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amount", "Radius", "float", 10.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = blur_bgra(img0, {amount} * ctx.k * 0.5) if {amount} > 0.1 else img0",
    },
    "fx_box_blur": {
        "cat": "Blur", "title": "Box Blur",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amount", "Size", "float", 10.0, 1.0, 100.0)],
        "out_type": "image",
        "snippet": (
            "out = _box_blur_node(img0, max(1, int({amount} * ctx.k * 0.5)))"
        ),
    },
    # ── Distort ───────────────────────────────────────────────────────────────
    "fx_displace": {
        "cat": "Distort", "title": "Displace",
        "ins": [("Image", "image"), ("Map", "image")], "outs": ["Image"],
        "params": [("strength", "Strength", "float", 20.0, 0.0, 200.0)],
        "out_type": "image",
        "snippet": "out = _fx_displace_node(img0, img1, {strength} * ctx.k)",
    },
    "fx_wave_warp": {
        "cat": "Distort", "title": "Wave Warp",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amp",   "Amplitude", "float", 20.0,  0.0, 200.0),
                   ("freq",  "Frequency", "float", 4.0,   0.1, 40.0),
                   ("speed", "Speed",     "float", 1.0,   0.0, 10.0),
                   ("angle", "Angle",     "float", 0.0, -180.0, 180.0)],
        "out_type": "image",
        "snippet": (
            "out = _fx_wave_node(img0, ctx, {amp}*ctx.k, {freq}, {speed}, {angle})"
        ),
    },
    "fx_chromatic_ab": {
        "cat": "Distort", "title": "Chromatic Aberration",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("amount", "Amount", "float", 8.0, 0.0, 80.0),
                   ("angle",  "Angle",  "float", 0.0, -180.0, 180.0)],
        "out_type": "image",
        "snippet": "out = _fx_chrab(img0, ctx, {amount}*ctx.k, {angle})",
    },
    "fx_pixelate_node": {
        "cat": "Distort", "title": "Pixelate",
        "ins": [("Image", "image")], "outs": ["Image"],
        "params": [("size", "Block size", "float", 14.0, 1.0, 120.0)],
        "out_type": "image",
        "snippet": "out = _fx_pix_node(img0, max(1, int({size} * ctx.k)))",
    },
    # ── Composite ─────────────────────────────────────────────────────────────
    "fx_over": {
        "cat": "Composite", "title": "Over (A over B)",
        "ins": [("Top (A)", "image"), ("Bottom (B)", "image")], "outs": ["Image"],
        "params": [("opacity", "Opacity", "float", 100.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_over(img0, img1, {opacity}/100.0)",
    },
    "fx_blend_mode": {
        "cat": "Composite", "title": "Blend Mode",
        "ins": [("Top", "image"), ("Bottom", "image")], "outs": ["Image"],
        "params": [("mode", "Mode", "choice", "screen",
                    [("screen","Screen"),("multiply","Multiply"),("add","Add"),
                     ("overlay","Overlay"),("difference","Difference"),
                     ("darken","Darken"),("lighten","Lighten")]),
                   ("opacity", "Opacity", "float", 100.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_blend_mode_node(img0, img1, {mode!r}, {opacity}/100.0)",
    },
    "fx_mask_alpha": {
        "cat": "Composite", "title": "Apply Mask",
        "ins": [("Image", "image"), ("Mask", "image")], "outs": ["Image"],
        "params": [("invert", "Invert mask", "bool", False)],
        "out_type": "image",
        "snippet": "out = _fx_apply_mask(img0, img1, {invert})",
    },
    # ── Utility ───────────────────────────────────────────────────────────────
    "fx_param_float": {
        "cat": "Parameter", "title": "Float Parameter",
        "ins": [], "outs": ["Value"],
        "params": [("key",   "Param key",  "text",  "amount"),
                   ("label", "Label",      "text",  "Amount"),
                   ("value", "Default",    "float", 50.0, 0.0, 100.0),
                   ("lo",    "Min",        "float", 0.0,  -1e6, 1e6),
                   ("hi",    "Max",        "float", 100.0,-1e6, 1e6)],
        "out_type": "float",
        "snippet": "val = float(p.get({key!r}, {value}))",
    },
    "fx_param_int": {
        "cat": "Parameter", "title": "Integer Parameter",
        "ins": [], "outs": ["Value"],
        "params": [("key",   "Param key",  "text",  "amount"),
                   ("label", "Label",      "text",  "Amount"),
                   ("value", "Default",    "int",   50, 0, 100),
                   ("lo",    "Min",        "int",   0,  -100000, 100000),
                   ("hi",    "Max",        "int",   100,-100000, 100000)],
        "out_type": "float",
        "snippet": "val = float(int(p.get({key!r}, {value})))",
    },
    "fx_param_color": {
        "cat": "Parameter", "title": "Color Parameter",
        "ins": [], "outs": ["Color (BGR float)"],
        "params": [("key",   "Param key", "text",  "color"),
                   ("label", "Label",     "text",  "Color"),
                   ("value", "Default",   "color", "#ff8800")],
        "out_type": "color",
        "snippet": "val = _fx_bgr(p.get({key!r}, {value!r}))",
    },
    "fx_constant": {
        "cat": "Utility", "title": "Constant",
        "ins": [], "outs": ["Value"],
        "params": [("value", "Value", "float", 1.0, -1e9, 1e9)],
        "out_type": "float",
        "snippet": "val = {value}",
    },
    "fx_mix": {
        "cat": "Utility", "title": "Mix Images",
        "ins": [("Image A", "image"), ("Image B", "image")], "outs": ["Image"],
        "params": [("t", "Mix (0=A 1=B)", "float", 0.5, 0.0, 1.0)],
        "out_type": "image",
        "snippet": "out = _fx_mix_images(img0, img1, {t})",
    },
    "fx_noise_tex": {
        "cat": "Source", "title": "Noise Texture",
        "ins": [], "outs": ["Image"],
        "params": [("scale",  "Scale",  "float", 80.0, 1.0, 500.0),
                   ("speed",  "Speed",  "float", 0.5,  0.0, 10.0),
                   ("seed",   "Seed",   "int",   1,    0,   999),
                   ("octaves","Octaves","int",   4,    1,   8)],
        "out_type": "image",
        "snippet": "out = _fx_noise_tex(img, ctx, {scale}*ctx.k, {speed}, {seed}, {octaves})",
    },
    "fx_time": {
        "cat": "Utility", "title": "Time",
        "ins": [], "outs": ["Global time", "Clip time", "Progress 0→1"],
        "params": [],
        "out_type": "float",
        "snippet": "val = (ctx.gt, ctx.lt, max(0.0, min(1.0, ctx.lt / max(1e-6, ctx.dur))))",
    },
    "fx_math": {
        "cat": "Utility", "title": "Math (float)",
        "ins": [("A", "float"), ("B", "float")], "outs": ["Value"],
        "params": [("op", "Op", "choice", "add",
                    [("add","A+B"),("sub","A−B"),("mul","A×B"),("div","A÷B"),
                     ("max","Max"),("min","Min"),("pow","Pow")])],
        "out_type": "float",
        "snippet": "val = _fx_math_node(v0, v1, {op!r})",
    },
}

# ── Patch 52: more nodes (picture sources and two value nodes) ────────────────
FX_NODE_TYPES.update({
    "fx_solid": {
        "cat": "Source", "title": "Solid Color",
        "ins": [], "outs": ["Image"],
        "params": [("color", "Color", "color", "#ff3366"), ("opacity", "Opacity", "float", 100.0, 0.0, 100.0)],
        "out_type": "image",
        "snippet": "out = _fx_solid(img, {color!r}, {opacity}/100.0)",
    },
    "fx_gradient": {
        "cat": "Source", "title": "Gradient",
        "ins": [], "outs": ["Image"],
        "params": [("color_a", "Color A", "color", "#ff3366"), ("color_b", "Color B", "color", "#2f7bff"),
                   ("angle", "Angle", "float", 90.0, -360.0, 360.0)],
        "out_type": "image",
        "snippet": "out = _fx_gradient(img, {color_a!r}, {color_b!r}, {angle})",
    },
    "fx_checker": {
        "cat": "Source", "title": "Checkerboard",
        "ins": [], "outs": ["Image"],
        "params": [("size", "Square size", "float", 32.0, 2.0, 400.0),
                   ("color_a", "Color A", "color", "#e8e8e8"), ("color_b", "Color B", "color", "#303030")],
        "out_type": "image",
        "snippet": "out = _fx_checker(img, {size} * ctx.k, {color_a!r}, {color_b!r})",
    },
    "fx_lfo": {
        "cat": "Utility", "title": "Wave (LFO)",
        "ins": [], "outs": ["Value"],
        "params": [("shape", "Shape", "choice", "sine", [("sine", "Sine"), ("triangle", "Triangle"), ("saw", "Saw"), ("square", "Square")]),
                   ("speed", "Cycles / second", "float", 0.5, 0.0, 20.0),
                   ("amount", "Amount", "float", 1.0, -1000000.0, 1000000.0),
                   ("offset", "Offset", "float", 0.0, -1000000.0, 1000000.0),
                   ("phase", "Phase (0-1)", "float", 0.0, 0.0, 1.0)],
        "out_type": "float", "nosock": False,
        "snippet": "val = _fx_lfo(ctx, {shape!r}, {speed}, {amount}, {offset}, {phase})",
    },
    "fx_map_range": {
        "cat": "Utility", "title": "Map Range",
        "ins": [("Value", "float")], "outs": ["Value"],
        "params": [("in_lo", "From low", "float", 0.0, -1000000.0, 1000000.0), ("in_hi", "From high", "float", 1.0, -1000000.0, 1000000.0),
                   ("out_lo", "To low", "float", 0.0, -1000000.0, 1000000.0), ("out_hi", "To high", "float", 100.0, -1000000.0, 1000000.0),
                   ("clamp", "Clamp", "bool", True)],
        "out_type": "float",
        "snippet": "val = _fx_map(v0, {in_lo}, {in_hi}, {out_lo}, {out_hi}, {clamp})",
    },
})
# Nodes whose own parameters are settings of the node itself (never wired from other nodes)
for _t in ("fx_param_float", "fx_param_int", "fx_param_color", "fx_constant"): FX_NODE_TYPES[_t]["nosock"] = True


def in_sockets(typ: str) -> list:
    """The input sockets of a node type, in order: [(label, kind, param_key or None)].
    First the picture / value inputs, then one socket for every number or colour parameter (so any of them can be
    driven by another node). A link's 'ti' is the position in this list."""
    spec = FX_NODE_TYPES.get(typ)
    if not spec: return []
    socks = [(lab, kind, None) for lab, kind in spec.get("ins", [])]
    if not spec.get("nosock"):
        for ps in spec.get("params", []):
            if ps[2] in ("float", "int"): socks.append((ps[1], "float", ps[0]))
            elif ps[2] == "color": socks.append((ps[1], "color", ps[0]))
    return socks


def out_kind(typ: str):
    """What the output sockets of a node type carry: 'image', 'float', 'color' (None = no output)."""
    spec = FX_NODE_TYPES.get(typ, {})
    return spec.get("out_type") if spec.get("outs") else None


def exposed_key(nid, pkey) -> str:
    """The name under which an exposed node parameter lives in the clip's effect (and so in the inspector)."""
    return "x%s_%s" % (re.sub(r"[^a-zA-Z0-9]", "", str(nid))[:12], re.sub(r"[^a-zA-Z0-9_]", "_", str(pkey)))


# ── Helper functions called by compiled effects ───────────────────────────────
# (Patch 51) Every helper returns the SAME array when it would change nothing (no copy, no work) and never changes its
# input in place. Heavy per-pixel Python loops were replaced by OpenCV / lookup tables.
import re as _re
from types import SimpleNamespace as _NS

_HEX_COLOR = _re.compile(r"^#[0-9a-fA-F]{3,8}$")
_VAR_RE = _re.compile(r"\b(img|v)(\d+)\b")


def _fx_ctx(ctx):
    """The context the real renderer gives an effect only has k / lt / fast / clip. Nodes need t, gt and dur as well."""
    lt = float(getattr(ctx, "lt", 0.0) or 0.0)
    clip = getattr(ctx, "clip", None)
    clip = clip if isinstance(clip, dict) else {}
    try: dur = float(clip.get("dur") or getattr(ctx, "dur", 0.0) or 0.0)
    except Exception: dur = 0.0
    try: start = float(clip.get("start") or 0.0)
    except Exception: start = 0.0
    try: k = max(1e-3, float(getattr(ctx, "k", 1.0) or 1.0))
    except Exception: k = 1.0
    return _NS(k=k, lt=lt, t=lt, gt=start + lt, dur=(dur if dur > 1e-6 else 1.0), fast=bool(getattr(ctx, "fast", False)))


def _fx_bgr(col):
    """'#rrggbb' -> float32 [b, g, r] in 0..1 (no Qt needed for hex colours)."""
    if isinstance(col, np.ndarray): return col.astype(np.float32).ravel()[:3]
    s = str(col).strip()
    if _re.match(r"^#?[0-9a-fA-F]{6}$", s):
        v = int(s.lstrip("#"), 16)
        return np.array([(v & 255) / 255.0, ((v >> 8) & 255) / 255.0, ((v >> 16) & 255) / 255.0], np.float32)
    try:
        c = QColor(s)
        if c.isValid(): return np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
    except Exception: pass
    return np.zeros(3, np.float32)


def _fx_finalize(res, ref):
    """Whatever the graph produced becomes a contiguous uint8 BGRA picture of the same size as the input
    (the renderer silently ignores an effect that returns anything else)."""
    if res is None or not isinstance(res, np.ndarray) or res.ndim not in (2, 3): return ref
    if res.dtype != np.uint8: res = np.clip(res, 0, 255).astype(np.uint8)
    if res.ndim == 2: res = res[..., None]
    c = res.shape[2]
    if c == 1: res = cv2.cvtColor(np.ascontiguousarray(res), cv2.COLOR_GRAY2BGRA)
    elif c == 3: res = cv2.cvtColor(np.ascontiguousarray(res), cv2.COLOR_BGR2BGRA)
    elif c != 4: return ref
    if res.shape[:2] != ref.shape[:2]: res = cv2.resize(res, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(res)


def _same_size(a, ref):
    return a if a.shape[:2] == ref.shape[:2] else cv2.resize(a, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_LINEAR)


def _lut_bgr(img, lut):
    out = img.copy(); out[..., :3] = cv2.LUT(np.ascontiguousarray(img[..., :3]), lut); return out


def _fx_bc(img, brightness, contrast):
    if abs(brightness) < 1e-6 and abs(contrast) < 1e-6: return img
    x = np.arange(256, dtype=np.float32) * (1 / 255)
    y = x * (1 + contrast) + brightness - contrast * 0.5
    return _lut_bgr(img, np.clip(y * 255 + 0.5, 0, 255).astype(np.uint8))


def _fx_huesat(img, hue_deg, sat_delta):
    if abs(hue_deg) < 1e-6 and abs(sat_delta) < 1e-6: return img
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV_FULL)      # hue 0..255 = 0..360 degrees
    if abs(hue_deg) >= 1e-6:
        hsv[..., 0] += np.uint8(int(round(hue_deg / 360.0 * 256.0)) & 255)              # uint8 wraps around = the hue circle
    if abs(sat_delta) >= 1e-6:
        hsv[..., 1] = cv2.convertScaleAbs(np.ascontiguousarray(hsv[..., 1]), alpha=max(0.0, 1.0 + sat_delta))
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR_FULL); return out


def _fx_tint_node(img, color_hex, amount):
    amount = min(1.0, max(0.0, amount))
    if amount <= 0: return img
    col = _fx_bgr(color_hex); x = np.arange(256, dtype=np.float32)
    lut = np.empty((256, 1, 3), np.uint8)
    for ch in range(3): lut[:, 0, ch] = np.clip(x * (1 - amount) + col[ch] * 255.0 * amount + 0.5, 0, 255).astype(np.uint8)
    return _lut_bgr(img, lut)


def _fx_invert_node(img, amount):
    amount = min(1.0, max(0.0, amount))
    if amount <= 0: return img
    x = np.arange(256, dtype=np.float32)
    return _lut_bgr(img, np.clip(x * (1 - amount) + (255.0 - x) * amount + 0.5, 0, 255).astype(np.uint8))


def _fx_bw_node(img, amount):
    amount = min(1.0, max(0.0, amount))
    if amount <= 0: return img
    bgr = np.ascontiguousarray(img[..., :3])
    gray = cv2.cvtColor(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    out = img.copy(); out[..., :3] = gray if amount >= 1.0 else cv2.addWeighted(bgr, 1 - amount, gray, amount, 0); return out


def _fx_threshold(img, level):
    g = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2GRAY)
    thr = int(math.ceil(min(1.0, max(0.0, level)) * 255.0 - 1e-9))
    mask = (g >= thr).astype(np.uint8) * 255 if thr <= 255 else np.zeros_like(g)
    out = np.empty_like(img); out[..., 0] = out[..., 1] = out[..., 2] = mask; out[..., 3] = img[..., 3]; return out


def _box_blur_node(img, k):
    if k < 2: return img
    k = int(k) | 1
    r = img.copy(); r[..., :3] = cv2.blur(np.ascontiguousarray(img[..., :3]), (k, k)); return r


def _fx_displace_node(img, mapimg, strength):
    if abs(strength) < 0.05: return img
    mapimg = _same_size(mapimg, img)
    h, w = img.shape[:2]
    gray = mapimg[..., :3].mean(axis=2, dtype=np.float32) * (1 / 255) * 2 - 1
    x, y = coords(h, w)
    return remap(img, x + gray * strength, y + gray * strength)


def _fx_wave_node(img, ctx, amp, freq, speed, angle_deg):
    if abs(amp) < 0.05: return img
    h, w = img.shape[:2]; x, y = coords(h, w)
    ang = math.radians(angle_deg)
    proj_ = x * math.cos(ang) + y * math.sin(ang)
    offset = amp * np.sin(proj_ * (freq * 2 * math.pi / max(h, w)) + ctx.t * speed * math.pi * 2)
    return remap(img, x + offset * math.cos(ang + math.pi / 2), y + offset * math.sin(ang + math.pi / 2))


def _fx_chrab(img, ctx, amount, angle_deg):
    if abs(amount) < 0.05: return img
    h, w = img.shape[:2]; ang = math.radians(angle_deg)
    dx = amount * math.cos(ang); dy = amount * math.sin(ang)
    x, y = coords(h, w)
    out = img.copy()
    for ch, sgn in ((2, 1.0), (0, -1.0)):
        out[..., ch] = cv2.remap(np.ascontiguousarray(img[..., ch]), (x + sgn * dx).astype(np.float32), (y + sgn * dy).astype(np.float32),
                                 cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


def _fx_pix_node(img, k):
    if k <= 1: return img
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // k), max(1, h // k)), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def _fx_over(top, bot, opacity):
    """Normal 'over' with real alpha handling (an opaque bottom is the fast, usual case)."""
    opacity = min(1.0, max(0.0, opacity))
    if opacity <= 0: return bot
    top = _same_size(top, bot)
    if int(bot[..., 3].min()) == 255:                       # opaque bottom (the usual case): the app's fast uint8 compositing
        from ..fastcomp import _alpha_comp
        roi = np.ascontiguousarray(bot[..., :3]).copy()
        _alpha_comp(roi, np.ascontiguousarray(top[..., :3]), np.ascontiguousarray(top[..., 3]), opacity)
        out = bot.copy(); out[..., :3] = roi; return out
    at = top[..., 3:4].astype(np.float32) * (opacity / 255.0)
    ft = top[..., :3].astype(np.float32); fb = bot[..., :3].astype(np.float32)
    ab = bot[..., 3:4].astype(np.float32) * (1 / 255.0)
    ao = at + ab * (1 - at)
    col = np.where(ao > 1e-6, (ft * at + fb * ab * (1 - at)) / np.maximum(ao, 1e-6), 0.0)
    out = np.empty_like(bot); out[..., :3] = np.clip(col + 0.5, 0, 255).astype(np.uint8); out[..., 3:4] = np.clip(ao * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def _fx_blend_mode_node(top, bot, mode, opacity):
    opacity = min(1.0, max(0.0, opacity))
    if opacity <= 0: return bot
    top = _same_size(top, bot)
    from ..fastcomp import blend_mode as _bm
    roi = np.ascontiguousarray(bot[..., :3]).copy()
    _bm(roi, np.ascontiguousarray(top[..., :3]), np.ascontiguousarray(top[..., 3]), opacity, mode)
    out = bot.copy(); out[..., :3] = roi; return out


def _fx_apply_mask(img, mask_img, invert=False):
    mask_img = _same_size(mask_img, img)
    gray = lum8(mask_img)
    if invert: gray = 1.0 - gray
    out = img.copy(); out[..., 3] = np.clip(img[..., 3].astype(np.float32) * gray + 0.5, 0, 255).astype(np.uint8); return out


def _fx_mix_images(a, b, t):
    t = max(0.0, min(1.0, float(t)))
    if t <= 0: return a
    b = _same_size(b, a)
    if t >= 1: return b
    return cv2.addWeighted(a, 1 - t, b, t, 0)


import threading as _threading
_NOISE_STATIC = OrderedDict()
_NOISE_LOCK = _threading.Lock()         # frames are rendered on several threads

def _fx_noise_tex(img, ctx, scale, speed, seed, octaves):
    h, w = img.shape[:2]
    key = (h, w, round(float(scale), 3), int(seed), int(octaves))
    if speed <= 1e-9:                                        # a still texture is the same every frame: make it once
        with _NOISE_LOCK:
            hit = _NOISE_STATIC.get(key)
            if hit is not None: _NOISE_STATIC.move_to_end(key)
        if hit is not None: return hit.copy()
    n = fbm(h, w, max(2, scale), int(seed), ctx.t * speed, max(1, int(octaves)))
    g = np.clip(n * 255.0 + 0.5, 0, 255).astype(np.uint8)    # black -> white ramp
    out = np.empty((h, w, 4), np.uint8); out[..., 0] = out[..., 1] = out[..., 2] = g; out[..., 3] = 255
    if speed <= 1e-9:
        with _NOISE_LOCK:
            _NOISE_STATIC[key] = out
            while len(_NOISE_STATIC) > 4: _NOISE_STATIC.popitem(last=False)
        return out.copy()
    return out


def _fx_math_node(a, b, op):
    try:
        if op == "add": r = a + b
        elif op == "sub": r = a - b
        elif op == "mul": r = a * b
        elif op == "div": r = a / b if abs(b) > 1e-9 else 0.0
        elif op == "max": r = max(a, b)
        elif op == "min": r = min(a, b)
        elif op == "pow":
            if a == 0: r = 0.0
            elif a < 0 and abs(b - round(b)) > 1e-9: r = 0.0
            else: r = float(a) ** max(-8.0, min(8.0, float(b)))
        else: r = 0.0
        r = float(r)
        return r if (r == r and abs(r) < 1e9) else 0.0
    except Exception:
        return 0.0


_FX_HELPERS = {
    "np": np, "cv2": cv2, "math": math,
    "blur_bgra": blur_bgra, "fbm": fbm, "noise": noise, "coords": coords,
    "remap": remap, "displace": displace, "affine": affine, "xform": xform,
    "lum8": lum8, "lum": lum, "f3": f3, "pack": pack, "bgr": bgr,
    "hsv_bgr": hsv_bgr, "ramp": ramp, "blend": blend, "edges": edges,
    "QColor": QColor,
    "_fx_ctx": _fx_ctx, "_fx_bgr": _fx_bgr, "_fx_finalize": _fx_finalize,
    "_fx_bc": _fx_bc, "_fx_huesat": _fx_huesat, "_fx_tint_node": _fx_tint_node,
    "_fx_invert_node": _fx_invert_node, "_fx_bw_node": _fx_bw_node,
    "_fx_threshold": _fx_threshold, "_box_blur_node": _box_blur_node,
    "_fx_displace_node": _fx_displace_node, "_fx_wave_node": _fx_wave_node,
    "_fx_chrab": _fx_chrab, "_fx_pix_node": _fx_pix_node,
    "_fx_over": _fx_over, "_fx_blend_mode_node": _fx_blend_mode_node,
    "_fx_apply_mask": _fx_apply_mask, "_fx_mix_images": _fx_mix_images,
    "_fx_noise_tex": _fx_noise_tex, "_fx_math_node": _fx_math_node,
}

# ── Patch 52: helpers of the new nodes ────────────────────────────────────────

def _u8(col):
    return np.clip(_fx_bgr(col) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _fx_solid(img, color, opacity):
    h, w = img.shape[:2]
    out = np.empty((h, w, 4), np.uint8); out[..., :3] = _u8(color)
    out[..., 3] = int(round(255 * min(1.0, max(0.0, opacity)))); return out


def _fx_gradient(img, color_a, color_b, angle_deg):
    h, w = img.shape[:2]
    a = _fx_bgr(color_a) * 255.0; b = _fx_bgr(color_b) * 255.0
    ang = math.radians(angle_deg); cx, cy = math.cos(ang), math.sin(ang)
    span = abs(w * cx) + abs(h * cy) or 1.0
    tx = ((np.arange(w, dtype=np.float32) + 0.5 - w / 2.0) * cx) / span
    ty = ((np.arange(h, dtype=np.float32) + 0.5 - h / 2.0) * cy) / span
    t = np.clip(tx[None, :] + ty[:, None] + 0.5, 0.0, 1.0)
    idx = (t * 255.0 + 0.5).astype(np.uint8)
    ramp_ = np.clip(a[None, :] + (b - a)[None, :] * (np.arange(256, dtype=np.float32)[:, None] / 255.0) + 0.5, 0, 255).astype(np.uint8)
    out = np.empty((h, w, 4), np.uint8); out[..., :3] = ramp_[idx]; out[..., 3] = 255; return out


def _fx_checker(img, size, color_a, color_b):
    h, w = img.shape[:2]; s = max(2, int(round(size)))
    m = (((np.arange(h) // s) & 1)[:, None] ^ ((np.arange(w) // s) & 1)[None, :]).astype(np.intp)
    pal = np.stack([_u8(color_a), _u8(color_b)])
    out = np.empty((h, w, 4), np.uint8); out[..., :3] = pal[m]; out[..., 3] = 255; return out


def _fx_lfo(ctx, shape, speed, amount, offset, phase):
    ph = (ctx.t * speed + phase) % 1.0
    if shape == "triangle": w_ = 1.0 - 4.0 * abs(ph - 0.5)
    elif shape == "saw": w_ = 2.0 * ph - 1.0
    elif shape == "square": w_ = 1.0 if ph < 0.5 else -1.0
    else: w_ = math.sin(2.0 * math.pi * ph)
    return float(offset + amount * w_)


def _fx_map(v, in_lo, in_hi, out_lo, out_hi, clamp):
    t = 0.0 if abs(in_hi - in_lo) < 1e-12 else (v - in_lo) / (in_hi - in_lo)
    if clamp: t = max(0.0, min(1.0, t))
    return float(out_lo + (out_hi - out_lo) * t)


_FX_HELPERS.update({"_fx_solid": _fx_solid, "_fx_gradient": _fx_gradient, "_fx_checker": _fx_checker,
                    "_fx_lfo": _fx_lfo, "_fx_map": _fx_map})


# ── Compiler ──────────────────────────────────────────────────────────────────

def _safe_id(s: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


def _coerce_param(ps, raw):
    """A node parameter as a safe Python value of its declared kind (numbers are clamped to the declared range).
    Only these values ever reach the generated code, so a hand-edited or imported .mcfx cannot inject code."""
    kind = ps[2]; dflt = ps[3]
    lo = ps[4] if len(ps) > 4 else None; hi = ps[5] if len(ps) > 5 else None
    try:
        if kind in ("float", "int"):
            v = float(raw)
            if v != v or v in (float("inf"), float("-inf")): v = float(dflt)
            if lo is not None: v = max(float(lo), v)
            if hi is not None: v = min(float(hi), v)
            return int(round(v)) if kind == "int" else v
        if kind == "bool": return bool(raw)
        if kind == "color":
            s = str(raw).strip()
            return s if _HEX_COLOR.match(s) else str(dflt)
        if kind == "choice":
            vals = [o[0] if isinstance(o, (list, tuple)) else o for o in (lo or [])]
            return raw if raw in vals else dflt
        return str(raw)[:64]
    except Exception:
        return dflt


class _Raw:
    """Code that is pasted into the generated source as it is (not quoted): used for linked / exposed parameters."""
    __slots__ = ("t",)
    def __init__(self, t): self.t = t
    def __repr__(self): return self.t
    __str__ = __repr__
    def __format__(self, spec): return self.t


def _fx_cf(v, lo, hi):
    try: v = float(v)
    except Exception: return float(lo)
    if v != v: return float(lo)
    return float(max(lo, min(hi, v)))


def _fx_ci(v, lo, hi): return int(round(_fx_cf(v, lo, hi)))


def _fx_pf(p, key, dflt, lo, hi):         # exposed float parameter, read from the clip's effect values
    return _fx_cf(p.get(key, dflt), lo, hi)


def _fx_pi(p, key, dflt, lo, hi): return int(round(_fx_cf(p.get(key, dflt), lo, hi)))


def _fx_pc(p, key, dflt, allowed):        # exposed choice
    v = p.get(key, dflt); return v if v in allowed else dflt


def _fx_pb(p, key, dflt): return bool(p.get(key, dflt))


def _fx_pcol(p, key, dflt):               # exposed colour
    v = p.get(key, dflt); v = str(v)
    return v if _HEX_COLOR.match(v) else dflt


_FX_HELPERS.update({"_fx_cf": _fx_cf, "_fx_ci": _fx_ci, "_fx_pf": _fx_pf, "_fx_pi": _fx_pi,
                    "_fx_pc": _fx_pc, "_fx_pb": _fx_pb, "_fx_pcol": _fx_pcol})


def compile_effect(fx_graph: dict, param_specs: list) -> types.FunctionType:
    """Compile a FX node graph into  fn(img, p, ctx) -> BGRA uint8  (same size as img).

    Only the nodes that lead to the Output node are compiled and run. Raises ValueError with a readable message for a
    graph that cannot work (no Output, a loop, a link between different socket types). Soft problems (an input that is
    not connected -> the original picture is used) are listed in  fn._fx_warnings.

    A number / colour parameter of a node is, in this order: the value of the node that is linked to its socket, the
    value of the effect's own slider when the parameter is exposed (node['ex']), or the value typed on the node."""
    graph = fx_graph or {}
    nodes = {}
    for n in graph.get("nodes", []):
        if isinstance(n, dict) and "id" in n and n.get("type") in FX_NODE_TYPES: nodes[str(n["id"])] = n
    socks = {nid: in_sockets(n["type"]) for nid, n in nodes.items()}
    links = {}                                   # (to_id, to_slot) -> (from_id, from_slot)
    for lk in graph.get("links", []):
        try: a, fo, b, ti = str(lk["from"]), int(lk.get("fo", 0)), str(lk["to"]), int(lk.get("ti", 0))
        except Exception: continue
        if a not in nodes or b not in nodes: continue
        if not (0 <= ti < len(socks[b])): continue
        if not (0 <= fo < max(1, len(FX_NODE_TYPES[nodes[a]["type"]].get("outs", [])))): continue
        links[(b, ti)] = (a, fo)

    def title(nid): return FX_NODE_TYPES[nodes[nid]["type"]].get("title", nodes[nid]["type"])
    def is_muted(nid): return bool(nodes[nid].get("mute")) and nodes[nid]["type"] not in ("fx_input", "fx_output")
    def live_in(nid):
        """The input slots that matter. A muted node passes its first picture straight through and ignores the rest."""
        s = socks[nid]
        if is_muted(nid): return [0] if (s and s[0][1] == "image" and out_kind(nodes[nid]["type"]) == "image") else []
        return list(range(len(s)))

    outputs = [nid for nid, n in nodes.items() if n["type"] == "fx_output"]
    if not outputs: raise ValueError("The effect has no Image Output node.")
    out_id = next((o for o in outputs if (o, 0) in links), outputs[0])

    # topological order of the nodes the Output depends on (iterative DFS, loop detection)
    order, state = [], {}
    stack = [(out_id, 0)]; state[out_id] = 1; path = [out_id]
    while stack:
        nid, i = stack[-1]
        slots = live_in(nid)
        if i < len(slots):
            stack[-1] = (nid, i + 1)
            src = links.get((nid, slots[i]))
            if src is None: continue
            s_ = src[0]
            if state.get(s_) == 1:
                loop = path[path.index(s_):] + [s_]
                raise ValueError("The graph has a loop: " + " -> ".join(title(x) for x in loop))
            if state.get(s_) is None:
                state[s_] = 1; path.append(s_); stack.append((s_, 0))
        else:
            state[nid] = 2; order.append(nid); stack.pop(); path.pop()

    # socket types must match
    for pos, nid in enumerate(order):
        for i in live_in(nid):
            lab, want, _pk = socks[nid][i]
            src = links.get((nid, i))
            if src is None: continue
            got = out_kind(nodes[src[0]]["type"])
            if got != want:
                raise ValueError("'%s' (%s) cannot go into '%s' input %s (%s)." % (title(src[0]), got, title(nid), lab, want))

    last_use = {}
    for pos, nid in enumerate(order):
        for i in live_in(nid):
            src = links.get((nid, i))
            if src: last_use[src[0]] = pos

    def ivar(nid): return "_i%d" % order.index(nid)
    def fvar(nid, slot): return "_f%d_%d" % (order.index(nid), slot)

    warnings = []
    lines = ["def _effect(img, p, ctx):", "    ctx = _fx_ctx(ctx)", "    _result = img"]

    def free_after(nid, pos):                            # a picture nobody needs any more is released at once (memory)
        for i in live_in(nid):
            src = links.get((nid, i))
            if src and last_use.get(src[0]) == pos and out_kind(nodes[src[0]]["type"]) == "image":
                lines.append("    %s = None" % ivar(src[0]))

    for pos, nid in enumerate(order):
        n = nodes[nid]; spec = FX_NODE_TYPES[n["type"]]
        if n["type"] == "fx_output":
            if (nid, 0) in links: lines.append("    _result = %s" % ivar(links[(nid, 0)][0]))
            else: warnings.append("The Output is not connected: the effect returns the original picture.")
            continue
        kind = out_kind(n["type"])
        if is_muted(nid):                                  # bypass: no work at all
            if kind == "image":
                src = links.get((nid, 0))
                lines.append("    %s = %s" % (ivar(nid), ivar(src[0]) if src else "img"))
            else:
                lines.append("    %s = 0.0" % " = ".join(fvar(nid, s_) for s_ in range(max(1, len(spec.get("outs", []))))))
            free_after(nid, pos); continue

        np_ = n.get("p", {}) if isinstance(n.get("p", {}), dict) else {}
        ex = n.get("ex", {}) if isinstance(n.get("ex", {}), dict) else {}
        sock_of = {pk: i for i, (_l, _k, pk) in enumerate(socks[nid]) if pk is not None}
        vals = {}
        for ps in spec.get("params", []):
            key, kind_p = ps[0], ps[2]
            const = _coerce_param(ps, np_.get(key, ps[3]))
            lo = ps[4] if len(ps) > 4 else None; hi = ps[5] if len(ps) > 5 else None
            src = links.get((nid, sock_of[key])) if key in sock_of else None
            if src is not None:                            # 1. another node drives this parameter
                v = fvar(src[0], src[1])
                if kind_p == "float": vals[key] = _Raw("_fx_cf(%s, %r, %r)" % (v, float(lo if lo is not None else -1e9), float(hi if hi is not None else 1e9)))
                elif kind_p == "int": vals[key] = _Raw("_fx_ci(%s, %r, %r)" % (v, float(lo if lo is not None else -1e9), float(hi if hi is not None else 1e9)))
                else: vals[key] = _Raw(v)
            elif key in ex and kind_p != "text":           # 2. the effect's own slider (inspector)
                ek = exposed_key(nid, key)
                if kind_p == "float": vals[key] = _Raw("_fx_pf(p, %r, %r, %r, %r)" % (ek, const, float(lo if lo is not None else -1e9), float(hi if hi is not None else 1e9)))
                elif kind_p == "int": vals[key] = _Raw("_fx_pi(p, %r, %r, %r, %r)" % (ek, const, float(lo if lo is not None else -1e9), float(hi if hi is not None else 1e9)))
                elif kind_p == "bool": vals[key] = _Raw("_fx_pb(p, %r, %r)" % (ek, const))
                elif kind_p == "choice":
                    allowed = tuple(o[0] if isinstance(o, (list, tuple)) else o for o in (lo or []))
                    vals[key] = _Raw("_fx_pc(p, %r, %r, %r)" % (ek, const, allowed))
                else: vals[key] = _Raw("_fx_pcol(p, %r, %r)" % (ek, const))
            else:                                          # 3. the value typed on the node
                vals[key] = const

        def ident(m, nid=nid):
            k_, idx = m.group(1), int(m.group(2))
            src = links.get((nid, idx))
            if k_ == "img":
                if src: return ivar(src[0])
                warnings.append("%s: input %s is not connected (the original picture is used)." % (title(nid), socks[nid][idx][0] if idx < len(socks[nid]) else idx))
                return "img"
            return fvar(src[0], src[1]) if src else "0.0"
        code = _VAR_RE.sub(ident, spec.get("snippet", "pass"))
        try: code = code.format(**vals)
        except (KeyError, IndexError, ValueError) as ex_: raise ValueError("Node '%s' cannot be compiled: %s" % (title(nid), ex_))

        if n["type"] == "fx_input": lines.append("    %s = img" % ivar(nid))
        elif kind == "image":
            lines.append("    " + code); lines.append("    %s = out" % ivar(nid))
        else:
            lines.append("    " + code)
            slots = max(1, len(spec.get("outs", [])))
            lines.append("    %s = val" % ", ".join(fvar(nid, s_) for s_ in range(slots)))
        free_after(nid, pos)
    lines.append("    return _fx_finalize(_result, img)")
    src_code = "\n".join(lines)

    globs = dict(_FX_HELPERS)
    try:
        exec(compile(src_code, "<custom_effect>", "exec"), globs)
        fn = globs["_effect"]
    except Exception as ex_:
        raise ValueError("Compile error: %s\nSource:\n%s" % (ex_, src_code))
    fn._fx_warnings = list(dict.fromkeys(warnings)); fn._fx_source = src_code
    return fn


def collect_param_specs(graph: dict) -> list:
    """The sliders the effect offers in the inspector: one for every Parameter node and one for every exposed node
    parameter (an exposed parameter that another node already drives is left out - the slider would do nothing)."""
    graph = graph or {}
    linked = set()
    for lk in graph.get("links", []):
        try: linked.add((str(lk["to"]), int(lk.get("ti", 0))))
        except Exception: pass
    specs, seen = [], set()
    for n in graph.get("nodes", []):
        if not isinstance(n, dict) or n.get("type") not in FX_NODE_TYPES or "id" not in n: continue
        typ = n["type"]; spec = FX_NODE_TYPES[typ]; p = n.get("p", {}) if isinstance(n.get("p", {}), dict) else {}
        if typ in ("fx_param_float", "fx_param_int", "fx_param_color"):
            key = str(p.get("key") or "").strip() or ("color" if typ == "fx_param_color" else "amount")
            if key in seen: continue
            seen.add(key); label = str(p.get("label") or key)[:40]
            try:
                if typ == "fx_param_color":
                    c = str(p.get("value", "#ff8800")); specs.append((key, label, "color", c if _HEX_COLOR.match(c) else "#ff8800", None, None))
                else:
                    lo = float(p.get("lo", 0)); hi = float(p.get("hi", 100)); val = float(p.get("value", 50))
                    if hi <= lo: hi = lo + 1.0
                    val = max(lo, min(hi, val))
                    if typ == "fx_param_int": specs.append((key, label, "int", int(round(val)), int(round(lo)), max(int(round(lo)) + 1, int(round(hi)))))
                    else: specs.append((key, label, "float", val, lo, hi))
            except (TypeError, ValueError): continue
            continue
        ex = n.get("ex") or {}
        if not isinstance(ex, dict) or not ex: continue
        socks = in_sockets(typ); sock_of = {pk: i for i, (_l, _k, pk) in enumerate(socks) if pk is not None}
        for ps in spec.get("params", []):
            key, kind_p = ps[0], ps[2]
            if key not in ex or kind_p == "text": continue
            if key in sock_of and (str(n["id"]), sock_of[key]) in linked: continue
            ek = exposed_key(n["id"], key)
            if ek in seen: continue
            seen.add(ek); label = str(ex.get(key) or ps[1])[:40] or ps[1]
            val = _coerce_param(ps, (n.get("p") or {}).get(key, ps[3]))
            if kind_p == "float": specs.append((ek, label, "float", float(val), float(ps[4]), float(ps[5])))
            elif kind_p == "int": specs.append((ek, label, "int", int(val), int(ps[4]), int(ps[5])))
            elif kind_p == "bool": specs.append((ek, label, "bool", bool(val), None, None))
            elif kind_p == "choice": specs.append((ek, label, "choice", val, [tuple(o) if isinstance(o, (list, tuple)) else (o, o) for o in ps[4]], None))
            elif kind_p == "color": specs.append((ek, label, "color", str(val), None, None))
    return specs


# ── Load / Save .mcfx files ───────────────────────────────────────────────────

def _mcfx_path(effect_id: str) -> str:
    return os.path.join(CUSTOM_FX_DIR, effect_id + ".mcfx")

def save_effect(meta: dict, param_specs: list, graph: dict) -> str:
    """Save custom effect to disk (written to a temporary file first, so a crash can never leave a half-written effect).
    Returns the effect id."""
    os.makedirs(CUSTOM_FX_DIR, exist_ok=True)
    eid = meta.get("id") or ("custom_" + hashlib.sha1(meta["name"].encode("utf-8")).hexdigest()[:8])
    eid = re.sub(r"[^a-z0-9_]", "_", eid.lower())
    if not re.search(r"[a-z0-9]", eid): eid = "custom_" + hashlib.sha1(str(meta.get("name", eid)).encode("utf-8")).hexdigest()[:8]
    meta["id"] = eid
    data = {"meta": meta, "params": param_specs, "graph": graph, "version": 1}
    path = _mcfx_path(eid); tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return eid

def load_effect(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        meta = data["meta"]
        if not meta.get("id"): meta["id"] = _safe_id(os.path.splitext(os.path.basename(path))[0])
        params = data.get("params", []); graph = data.get("graph", {})
        fn = compile_effect(graph, params)
        eid = "custom:" + meta["id"]
        CUSTOM_REGISTRY[eid] = {"meta": meta, "params": params, "graph": graph, "fn": fn, "error": None}
        return data
    except Exception as ex:
        print("[custom_fx] failed to load %s: %s" % (path, ex))
        CUSTOM_REGISTRY[path] = {"meta": {"name": os.path.basename(path)}, "params": [], "graph": {}, "fn": None, "error": str(ex).splitlines()[0] if str(ex) else "error"}
        return None

def delete_effect(effect_id: str):
    """Delete a custom effect from disk and FX registry."""
    p = _mcfx_path(effect_id)
    if os.path.exists(p): os.remove(p)
    key = "custom:" + effect_id
    CUSTOM_REGISTRY.pop(key, None)
    FX.pop(key, None)

def export_effect(effect_id: str, dest_path: str):
    src = _mcfx_path(effect_id)
    import shutil; shutil.copy2(src, dest_path)

def import_effect(src_path: str) -> str | None:
    try:
        with open(src_path, encoding="utf-8") as f: data = json.load(f)
        meta = data["meta"]
        eid = meta.get("id", "imported")
        # avoid overwriting built-in effects
        eid = re.sub(r"[^a-z0-9_]", "_", eid.lower())
        meta["id"] = eid
        compile_effect(data.get("graph", {}), data.get("params", []))      # refuse a file that cannot work
        save_effect(meta, data.get("params", []), data.get("graph", {}))
        return eid
    except Exception as ex:
        print("[custom_fx] import failed:", ex); return None

def load_all():
    """Load all .mcfx files from CUSTOM_FX_DIR and register them into FX. Safe to call again at any time: effects
    whose file is gone disappear, the others are replaced (the new version is registered before old leftovers go)."""
    for k in [k for k in CUSTOM_REGISTRY if not k.startswith("custom:")]: CUSTOM_REGISTRY.pop(k, None)     # old load errors
    seen = set()
    if os.path.isdir(CUSTOM_FX_DIR):
        for fname in sorted(os.listdir(CUSTOM_FX_DIR)):
            if not fname.endswith(".mcfx"): continue
            data = load_effect(os.path.join(CUSTOM_FX_DIR, fname))
            if data is None: continue
            meta = data["meta"]; params = data.get("params", [])
            eid = "custom:" + meta["id"]
            fn = CUSTOM_REGISTRY[eid]["fn"]
            cat = meta.get("category", "Custom") or "Custom"
            title = meta.get("name", eid)
            fx_params = [tuple(ps) for ps in params if isinstance(ps, (list, tuple)) and len(ps) >= 6]
            try:
                _register_fx(eid, cat, title, fx_params, fn, help=meta.get("description", ""))
                seen.add(eid)
            except Exception as ex:
                print("[custom_fx] register failed %s: %s" % (eid, ex))
    for k in [k for k in list(FX) if k.startswith("custom:") and k not in seen]: FX.pop(k, None)
    for k in [k for k in list(CUSTOM_REGISTRY) if k.startswith("custom:") and k not in seen]: CUSTOM_REGISTRY.pop(k, None)

def get_categories() -> list:
    """User-defined categories."""
    if os.path.exists(CUSTOM_CATEGORIES_FILE):
        try:
            with open(CUSTOM_CATEGORIES_FILE, encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return ["Custom"]

def save_categories(cats: list):
    os.makedirs(CUSTOM_FX_DIR, exist_ok=True)
    with open(CUSTOM_CATEGORIES_FILE, "w", encoding="utf-8") as f: json.dump(cats, f)

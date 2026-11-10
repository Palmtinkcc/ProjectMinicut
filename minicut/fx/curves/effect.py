"""curves: Curves. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import DEFAULT_CURVE, IDENT, _LUT_CACHE, curve_eval, register

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

register("curves", "Color", "Curves",
         [("curve", "Curves", "curve", copy.deepcopy(DEFAULT_CURVE), None, None)],
         fx_curves)

ID = "curves"

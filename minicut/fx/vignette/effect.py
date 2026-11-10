"""vignette: Vignette. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, _VIG, gpu_vignette, register

def fx_vignette(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    h, w = img.shape[:2]
    rnd  = p.get("roundness", 50.0) / 100.0
    col  = p.get("color", "#000000")
    mode = p.get("mode", "darken")
    if _GPU_FX:
        try:
            from ...shared.deps import QColor as _QC
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
        from ...shared.deps import QColor as _QC
        c = _QC(col)
        tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
        f  = img[..., :3].astype(np.float32)
        blended = f * (1 - v[..., None]) + tc * 255 * v[..., None]
        out[..., :3] = np.clip(blended + .5, 0, 255).astype(np.uint8)
    return out

register("vignette", "Stylize", "Vignette",
         [("amount",    "Amount",    "float",  50.0, 0.0, 100.0),
          ("softness",  "Softness",  "float",  60.0, 0.0, 100.0),
          ("roundness", "Roundness", "float",  50.0, 0.0, 100.0),
          ("color",     "Color",     "color",  "#000000", None, None),
          ("mode",      "Mode",      "choice", "darken",
           [("darken", "Darken"), ("color", "Color"), ("alpha", "Alpha")], None)],
         fx_vignette,
         help="Vignette with adjustable roundness, custom color, and alpha mode.")

ID = "vignette"

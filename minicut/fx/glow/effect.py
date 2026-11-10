"""glow: Glow. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, _gauss, gpu_gaussian_blur, gpu_glow, register

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
                from ...shared.deps import QColor as _QC
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
        from ...shared.deps import QColor as _QC
        c = _QC(col); tc = np.array([c.blueF(), c.greenF(), c.redF()], np.float32)
        glow_rgb = glow_rgb * (1 / max(glow_rgb.max(), 1e-4)) * tc * 255 * (glow_rgb.max() / 255)
    out = img.copy()
    if blend == "add":
        out[..., :3] = np.clip(f + glow_rgb * a + .5, 0, 255).astype(np.uint8)
    else:
        out[..., :3] = np.clip(255 - (255 - f) * (255 - glow_rgb * a) / 255 + .5, 0, 255).astype(np.uint8)
    return out

register("glow", "Stylize", "Glow",
         [("amount",     "Amount",     "float",  60.0, 0.0, 100.0),
          ("radius",     "Radius",     "float",  20.0, 0.0, 100.0),
          ("threshold",  "Threshold",  "float",  60.0, 0.0, 100.0),
          ("blend_mode", "Blend mode", "choice", "screen",
           [("screen", "Screen"), ("add", "Add")], None),
          ("color",      "Color tint", "color",  "", None, None)],
         fx_glow,
         help="Glow with Screen/Add blend mode and optional color tint.")

ID = "glow"

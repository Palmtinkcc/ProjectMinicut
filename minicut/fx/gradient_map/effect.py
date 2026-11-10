"""gradient_map: Gradient Map. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_gradient_map(img, p, ctx):
    """Map luminance to a two-color gradient — like AM's Gradient Map / Spectral Map."""
    col_lo = p.get("color_lo", "#000000")
    col_hi = p.get("color_hi", "#ffffff")
    amount = p.get("amount", 100.0) / 100.0
    from ...shared.deps import QColor as _QC
    clo = _QC(col_lo); chi = _QC(col_hi)
    lo  = np.array([clo.blueF(), clo.greenF(), clo.redF()], np.float32) * 255
    hi  = np.array([chi.blueF(), chi.greenF(), chi.redF()], np.float32) * 255
    rgb = img[..., :3].astype(np.float32)
    lum = (rgb @ np.array([0.114, 0.587, 0.299], np.float32)) / 255.0
    mapped = lo[None, None, :] + lum[..., None] * (hi - lo)[None, None, :]
    out = img.copy()
    out[..., :3] = np.clip(rgb * (1 - amount) + mapped * amount + .5, 0, 255).astype(np.uint8)
    return out

register("gradient_map", "Color", "Gradient Map",
         [("color_lo", "Shadow color",    "color", "#000000", None, None),
          ("color_hi", "Highlight color", "color", "#ffffff", None, None),
          ("amount",   "Amount",          "float", 100.0, 0.0, 100.0)],
         fx_gradient_map,
         help="Maps image luminance to a two-color gradient — good for duotones and tonal grading.")

ID = "gradient_map"

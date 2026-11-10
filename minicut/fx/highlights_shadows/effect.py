"""highlights_shadows: Highlights & Shadows. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

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

register("highlights_shadows", "Color", "Highlights & Shadows",
         [("highlights", "Highlights", "float", 0.0, -100.0, 100.0),
          ("shadows",    "Shadows",    "float", 0.0, -100.0, 100.0)],
         fx_highlights_shadows,
         help="Independently lift or pull the highlights and shadows — like Lightroom's HS controls.")

ID = "highlights_shadows"

"""posterize: Posterize. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_posterize(img, p, ctx):
    levels = max(2, int(p["levels"]))
    step = 255.0 / (levels - 1)
    rgb = img[..., :3]
    posterized = (np.round(rgb.astype(np.float32) / step) * step).astype(np.uint8)
    out = img.copy(); out[..., :3] = posterized; return out

register("posterize", "Color", "Posterize",
         [("levels", "Levels", "int", 4, 2, 32)],
         fx_posterize,
         help="Reduce the number of tonal levels in the image.")

ID = "posterize"

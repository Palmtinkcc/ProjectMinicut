"""offset: Offset. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

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

register("offset", "Distort", "Offset",
         [("x",    "X",    "float", 0.0, -1000.0, 1000.0),
          ("y",    "Y",    "float", 0.0, -1000.0, 1000.0),
          ("wrap", "Wrap", "bool",  True, None, None)],
         fx_offset,
         help="Shift the layer with optional wrap-around tiling.")

ID = "offset"

"""replace_color: Replace Color. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_replace_color(img, p, ctx):
    """Replace a chosen hue range with another color — AM's Replace Color."""
    src_col  = p.get("source_color", "#ff0000")
    dst_col  = p.get("dest_color",   "#0000ff")
    tol      = p.get("tolerance", 30)
    softness = p.get("softness", 10)
    from ...shared.deps import QColor as _QC
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

register("replace_color", "Color", "Replace Color",
         [("source_color", "Source color", "color", "#ff0000", None, None),
          ("dest_color",   "Dest color",   "color", "#0000ff", None, None),
          ("tolerance",    "Tolerance",    "int",   30, 1, 90),
          ("softness",     "Softness",     "int",   10, 0, 60)],
         fx_replace_color,
         help="Replace a hue range with another color.")

ID = "replace_color"

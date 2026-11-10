"""bgcopy: Copy background. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_bgcopy(img, p, ctx):
    # Scale > 100 zooms the copy OUT so it fills the empty border that Spill creates.
    # Use BORDER_REFLECT so pixels outside the original frame are mirrored (not black).
    h, w = img.shape[:2]
    sc = p["scale"] / 100.0
    M = xform(h, w, sc=sc)
    bg = cv2.warpAffine(
        np.ascontiguousarray(img), M.astype(np.float32), (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    bg = blur_bgra(bg, p["blur"] * ctx.k * 0.6)
    return blend(img, f3(bg) * (1 - p["dim"] / 100.0), bg[..., 3].astype(np.float32) / 255.0, "behind", 1.0)

reg("bgcopy", C1, "Copy background", [F("scale", "Size of the copy", 130, 100, 400), F("blur", "Blur", 35, 0, 100), F("dim", "Darken", 35, 0, 100)], fx_bgcopy,
    "Fills the empty space around the media (turn on Spill outside the media) with a bigger, blurred copy of itself.", "blur background fill")

ID = "bgcopy"

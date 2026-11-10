"""area_blur: Area Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _area_mask, _mix, blur_bgra, register

def fx_area_blur(img, p, ctx):
    ih, iw = img.shape[:2]; m = _area_mask(p, ctx.holder, iw, ih); blurred = blur_bgra(img, p["amount"] * ctx.k)
    return blurred if m is None else _mix(img, blurred, m)

register("area_blur", "Blur", "Area Blur",
         [("amount", "Amount", "float", 25.0, 0.0, 100.0)],
         fx_area_blur, area=True)

ID = "area_blur"

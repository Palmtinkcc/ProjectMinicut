"""blur: Gaussian Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _blur_rgb_only, _premul, _unpremul, blur_bgra, register

def fx_blur(img, p, ctx):
    amt = p["amount"] * ctx.k
    if amt < 0.3: return img
    sx = amt * p["x_blur"] / 100.0
    sy = amt * p["y_blur"] / 100.0
    if sx < 0.3 and sy < 0.3: return img
    if abs(sx - sy) < 0.5:
        # isotropic fast path
        return blur_bgra(img, sx) if p.get("alpha_blur", False) else _blur_rgb_only(img, sx)
    # anisotropic: blur each axis separately
    pm, a = _premul(img)
    def _gauss1d(arr, sigma, axis):
        if sigma < 0.3: return arr
        kk = int(sigma * 3) * 2 + 1
        if axis == 0: return cv2.GaussianBlur(arr, (1, kk), sigma)
        return cv2.GaussianBlur(arr, (kk, 1), sigma)
    rgb = _gauss1d(_gauss1d(pm, sx, 1), sy, 0)
    al  = _gauss1d(_gauss1d(a,  sx, 1), sy, 0) if p.get("alpha_blur", False) else a
    return _unpremul(rgb, al)

register("blur", "Blur", "Gaussian Blur",
         [("amount",     "Amount",     "float", 12.0, 0.0, 200.0),
          ("x_blur",     "Blur X",     "float", 100.0, 0.0, 100.0),
          ("y_blur",     "Blur Y",     "float", 100.0, 0.0, 100.0),
          ("alpha_blur", "Blur Alpha", "bool",  False, None, None)],
         fx_blur,
         help="Gaussian blur with independent X/Y control and optional alpha-edge blur.")

ID = "blur"

"""hslmix: HSL Mixer. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_hslmix(img, p, ctx):
    hsv8 = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV_FULL); hsv = hsv8.astype(np.float32)
    # The hue is a whole number 0..255, so the shifts are worked out once for each of the 256 hues and looked up (the same numbers, a few hundred times less work)
    hl = np.arange(256, dtype=np.float32) / 255.0; dhl = np.zeros_like(hl); dsl = np.zeros_like(hl); dvl = np.zeros_like(hl)
    for k, _, c in _BANDS:
        d = np.abs(((hl - c + 0.5) % 1.0) - 0.5); wgt = np.clip(1 - d * 6, 0, 1)
        dhl += wgt * p[k + "_h"] / 360.0; dsl += wgt * p[k + "_s"] / 100.0; dvl += wgt * p[k + "_l"] / 100.0
    hi = hsv8[..., 0]; hh = hl[hi]; dh = dhl[hi]; ds = dsl[hi]; dv = dvl[hi]
    hsv[..., 0] = ((hh + dh) % 1.0) * 255.0; hsv[..., 1] = np.clip(hsv[..., 1] * (1 + ds), 0, 255); hsv[..., 2] = np.clip(hsv[..., 2] * (1 + dv), 0, 255)
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR_FULL); return out

reg("hslmix", C1, "HSL Mixer", sum([[F(k + "_h", n + " hue", 0, -60, 60), F(k + "_s", n + " saturation", 0, -100, 100), F(k + "_l", n + " lightness", 0, -100, 100)] for k, n, _ in _BANDS], []), fx_hslmix,
    "Change the hue, saturation and lightness of each color family separately (all the reds, all the blues ...).", "color mixer hsl")

ID = "hslmix"

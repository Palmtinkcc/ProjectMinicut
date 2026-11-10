"""rays: Rays. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_rays(img, p, ctx):
    h, w = img.shape[:2]; f = f3(img); g = lum(f); t = p["threshold"] / 100.0; m = (np.clip((g - t) / max(1e-3, 1 - t), 0, 1)[..., None] * f * (img[..., 3:4] * (1 / 255))).astype(np.float32)
    n = 8 if ctx.fast else 16; acc = np.zeros_like(m); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; ln = p["length"] / 100.0
    for i in range(n):
        s = 1 + ln * i / n; M = xform(h, w, sc=s, cx=cx, cy=cy); acc += cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT) * (0.93 ** i)
    rays = acc / n * (p["amount"] / 25.0) * bgr(p["color"]); return blend(img, np.clip(rays, 0, 1), None, "screen", 1.0)

reg("rays", C1, "Rays", [F("amount", "Amount", 60, 0, 100), F("length", "Length", 60, 5, 150), F("threshold", "Bright from", 55, 0, 95), F("cx", "Center X", 50, 0, 100), F("cy", "Center Y", 30, 0, 100), C("color", "Color", "#fff1c9")], fx_rays,
    "Light rays that stream out from the bright parts of the picture.", "god rays light shafts")

ID = "rays"

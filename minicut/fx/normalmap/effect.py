"""normalmap: Normal map. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_normalmap(img, p, ctx):
    L = lum8(img)
    if p["blur"] > 0: L = cv2.GaussianBlur(L, (0, 0), p["blur"] * ctx.k * 0.5)
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3) * p["strength"] / 4.0; gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3) * p["strength"] / 4.0 * (-1 if p["flip"] else 1); nz = np.ones_like(gx); n = np.stack([-gx, -gy, nz], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    rgb = n * 0.5 + 0.5; a = p["amount"] / 100.0; return pack(f3(img) * (1 - a) + rgb[..., ::-1] * a, like=img)

reg("normalmap", SS, "Normal map", [F("strength", "Strength", 12, 0.5, 60), F("blur", "Smooth", 1.0, 0, 20), B("flip", "Flip green", False), F("amount", "Amount", 100, 0, 100)], fx_normalmap, "Turns the picture into the blue-purple map that 3D programs use for surface detail.", "bump 3d texture")

ID = "normalmap"

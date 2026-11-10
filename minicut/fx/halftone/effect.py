"""halftone: Halftone / dots. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_halftone(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); a = np.deg2rad(p["angle"]); x, y = coords(h, w); u = x * np.cos(a) + y * np.sin(a); v = -x * np.sin(a) + y * np.cos(a); iu, iv = np.floor(u / s) + 0.5, np.floor(v / s) + 0.5
    cx = (iu * s) * np.cos(a) - (iv * s) * np.sin(a); cy = (iu * s) * np.sin(a) + (iv * s) * np.cos(a); samp = remap(img, np.clip(cx, 0, w - 1), np.clip(cy, 0, h - 1), cv2.BORDER_REPLICATE); f = f3(samp); L = lum(f)
    val = (1 - L) if not p["invert"] else L; r = np.sqrt(np.clip(val, 0, 1)) * s * 0.72 * (p["dot"] / 100.0 * 1.4); d = np.sqrt((u - iu * s) ** 2 + (v - iv * s) ** 2); m = np.clip((r - d) / max(0.8, 1.0 * ctx.k) + 0.5, 0, 1)
    ink = f if p["color_dots"] else np.broadcast_to(bgr(p["ink"]), f.shape); paper = bgr(p["paper"]); out = paper * (1 - m[..., None]) + ink * m[..., None]; return pack(out, like=img)

reg("halftone", IK, "Halftone / dots", [F("size", "Dot spacing", 9, 3, 60), F("angle", "Angle", 45, -90, 90), F("dot", "Dot size", 100, 30, 150), B("color_dots", "Colored dots", False), B("invert", "Light dots on dark", False), C("ink", "Ink", "#111111"), C("paper", "Paper", "#f5efe0")], fx_halftone, "The picture is made of dots, big in dark parts and small in light ones, like a newspaper.", "newspaper print dots comic")

ID = "halftone"

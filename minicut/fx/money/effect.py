"""money: Money filter. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_money(img, p, ctx):
    h, w = img.shape[:2]; L = lum8(img); L = cv2.GaussianBlur(L, (0, 0), max(0.5, 0.8 * ctx.k)); x, y = coords(h, w); sp = S(ctx, p["spacing"]); a = np.deg2rad(p["angle"]); u = x * np.cos(a) + y * np.sin(a) + np.sin(x / S(ctx, 24) + y / S(ctx, 70)) * sp * 1.3 * p["curve"] / 100.0
    ph = (u / sp) % 1.0; tri = np.abs(ph - 0.5) * 2; ink = np.clip((0.5 * (1 - L) * 1.25 + 0.12 - tri * 0.5) * 6, 0, 1); rx, ry = x - w / 2, y - h / 2; ros = 0.5 + 0.5 * np.sin(np.sqrt(rx * rx + ry * ry) / (sp * 1.1) + np.arctan2(ry, rx) * 8); ink = np.clip(ink + (ros > 0.97) * 0.35 * p["rosette"] / 100.0, 0, 1)
    paper = bgr(p["paper"]) * (0.96 + 0.04 * noise(h, w, S(ctx, 20), 5)[..., None]); out = paper * (1 - ink[..., None]) + bgr(p["ink"]) * ink[..., None]; return pack(np.clip(out, 0, 1), like=img)

reg("money", IK, "Money filter", [F("spacing", "Line spacing", 5, 2, 20), F("angle", "Angle", 20, -90, 90), F("curve", "Curve", 60, 0, 100), F("rosette", "Rosette pattern", 40, 0, 100), C("ink", "Ink", "#1f5a3a"), C("paper", "Paper", "#e8efd6")], fx_money, "The picture engraved with fine curved lines, like the portrait on a banknote.", "banknote engraving currency")

ID = "money"

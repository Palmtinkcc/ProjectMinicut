"""waveloq: Waveloq. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_waveloq(img, p, ctx):
    h, w = img.shape[:2]; sp = S(ctx, p["spacing"]); n = max(2, int(h / sp)); L = cv2.resize(lum8(img), (w, n), interpolation=cv2.INTER_AREA); x, y = coords(h, w); idx = np.clip(np.round(y / sp - 0.5).astype(int), 0, n - 1); xi = np.clip(x.astype(int), 0, w - 1)
    amp = sp * 0.48 * p["wave"] / 100.0 * (1 - L if p["invert"] else L); cyl = (idx + 0.5) * sp + amp[idx, xi] * np.sin(x / S(ctx, p["freq"]) * 2 * np.pi + ctx.lt * p["speed"]); d = np.abs(y - cyl); m = np.clip((S(ctx, p["thick"]) * 0.5 - d) / max(0.7, ctx.k) + 0.5, 0, 1)
    col = f3(img) if p["color_lines"] else np.broadcast_to(bgr(p["ink"]), (h, w, 3)); return pack(bgr(p["paper"]) * (1 - m[..., None]) + col * m[..., None], like=img)

reg("waveloq", IK, "Waveloq", [F("spacing", "Line spacing", 10, 4, 40), F("wave", "Wave height", 80, 0, 100), F("freq", "Wave length", 10, 3, 60), F("thick", "Line thickness", 1.6, 0.5, 8), F("speed", "Speed", 1.5, 0, 10), B("invert", "Dark makes the waves", False), B("color_lines", "Colored lines", False), C("ink", "Ink", "#f3f3f3"), C("paper", "Paper", "#0a0a0f")], fx_waveloq, "The picture drawn with wavy lines: the brighter, the taller the waves (like a pulsar album cover).", "line art wave joy division pulsar")

ID = "waveloq"

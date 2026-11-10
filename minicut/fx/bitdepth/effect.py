"""bitdepth: 4 / 8 / 16 bit. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_bitdepth(img, p, ctx):
    h, w = img.shape[:2]; s = max(1, int(S(ctx, p["pixel"]))); small = cv2.resize(img, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA); f = f3(small); sh, sw = f.shape[:2]
    if p["dither"] > 0: b = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16.0 - 0.5; f = f + np.tile(b, (sh // 4 + 1, sw // 4 + 1))[:sh, :sw, None] * (p["dither"] / 100.0) * 0.5
    bits = p["bits"]
    if bits == "4": q = np.clip(np.round(f), 0, 1); br = (lum(f) > 0.55)[..., None] * 0.35; q = np.clip(q * 0.65 + br * (q > 0), 0, 1)
    elif bits == "8": lv = np.array([7, 7, 3], np.float32); q = np.round(np.clip(f, 0, 1) * lv) / lv
    else: lv = np.array([31, 63, 31], np.float32); q = np.round(np.clip(f, 0, 1) * lv[::-1]) / lv[::-1]
    out = pack(np.clip(q, 0, 1), small[..., 3]); return cv2.resize(out, (w, h), interpolation=cv2.INTER_NEAREST)

reg("bitdepth", IK, "4 / 8 / 16 bit", [CH("bits", "Colors", "8", [("4", "4-bit (16 colors)"), ("8", "8-bit (256 colors)"), ("16", "16-bit (65 536 colors)")]), F("pixel", "Pixel size", 3, 1, 30), F("dither", "Dither", 60, 0, 100)], fx_bitdepth, "Old video-game graphics: big pixels and few colors.", "retro game pixel art palette")

ID = "bitdepth"

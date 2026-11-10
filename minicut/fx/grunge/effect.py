"""grunge: Grunge. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_grunge(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["scale"]); f = fbm(h, w, s * 6, int(p["seed"]), 0, 5) * 0.6 + noise(h, w, max(2, s * 0.4), int(p["seed"]) + 3) * 0.4; f = np.clip((f - 0.5) * (2 + p["contrast"] / 20.0) + 0.5, 0, 1)
    r = np.random.default_rng(int(p["seed"])); sc_ = np.zeros((h, w), np.float32)
    for _ in range(int(p["scratches"])): x0, y0 = r.integers(0, w), r.integers(0, h); cv2.line(sc_, (x0, y0), (int(x0 + r.normal(0, w * 0.2)), int(y0 + r.normal(0, h * 0.2))), 1.0, 1, cv2.LINE_AA)
    m = np.clip(f + sc_ * 0.6, 0, 1); return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m * (p["amount"] / 100.0), p["mode"], 1.0)

reg("grunge", PR, "Grunge", [F("amount", "Amount", 60, 0, 100), F("scale", "Dirt size", 20, 2, 100), F("contrast", "Contrast", 30, 0, 100), I("scratches", "Scratches", 25, 0, 200), C("color", "Color", "#1b1208"), MODE("over"), SEED()], fx_grunge, "Dirt, stains and scratches laid over the picture.", "dirty texture worn")

ID = "grunge"

"""vhsdist: VHS distortion. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_vhsdist(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; y = np.arange(h, dtype=np.float32); r = rng(ctx, p["seed"], 25); t = ctx.lt * p["speed"]
    wob = np.sin(y * 0.045 + t * 3) * 0.5 + np.sin(y * 0.13 - t * 5) * 0.3; low = np.clip((y / h - 0.65) / 0.35, 0, 1) ** 2; pos = (t * 0.17) % 1.0; band = np.clip(1 - np.abs(y / h - pos) / (p["band"] / 100.0 * 0.12 + 1e-3), 0, 1)
    sh = (wob * w * 0.004 + (low * 18 + band * 40) * r.normal(0.6, 0.5, h)) * a * ctx.k; out = shift_rows(img, sh.astype(np.float32))
    bl = out.copy(); bl[..., 2] = cv2.GaussianBlur(out[..., 2], (0, 0), max(0.5, 3 * ctx.k * a), borderType=cv2.BORDER_REPLICATE); return bl

reg("vhsdist", V, "VHS distortion", [F("amount", "Amount", 50, 0, 100), F("band", "Tracking band", 40, 0, 100), SPEED(1.0), SEED()], fx_vhsdist, "Wobbling lines, a moving tracking band and color bleeding, like a worn tape.", "vsh tape wobble")

ID = "vhsdist"

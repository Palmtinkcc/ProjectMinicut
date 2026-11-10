"""noiseover: Noise overlay. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_noiseover(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); s = S(ctx, p["size"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); n = r.random((gh, gw, 1 if p["mono"] else 3)).astype(np.float32)
    n = cv2.resize(n, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]; n = n[..., None] if n.ndim == 2 else n; n = np.broadcast_to(n, (h, w, 3))
    return blend(img, np.ascontiguousarray(n), None, p["mode"], p["amount"] / 100.0)

reg("noiseover", V, "Noise overlay", [F("amount", "Amount", 30, 0, 100), F("size", "Grain size", 2, 1, 20), F("rate", "Changes / s", 24, 0, 60), B("mono", "Gray noise", True), MODE("overlay"), SEED()], fx_noiseover, "A layer of animated noise on top, like analog video grain.", "grain static")

ID = "noiseover"

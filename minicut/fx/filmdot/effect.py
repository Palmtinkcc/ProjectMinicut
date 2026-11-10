"""filmdot: Film dot. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_filmdot(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 12); cv = np.zeros((h, w), np.float32); dk = np.zeros((h, w), np.float32)
    for _ in range(int(5 + a * 120)):
        x, y = int(r.integers(0, w)), int(r.integers(0, h)); rad = max(1, int(S(ctx, r.uniform(0.6, 2.6) * p["size"]))); cv2.circle(cv if r.random() < 0.7 else dk, (x, y), rad, 1.0, -1, cv2.LINE_AA)
    for _ in range(int(a * 4 * p["scratch"] / 50.0)):
        x = int(r.integers(0, w)); cv2.line(cv, (x, int(r.integers(0, h // 2))), (x + int(r.normal(0, 3)), int(r.integers(h // 2, h))), 0.7, 1, cv2.LINE_AA)
    for _ in range(int(a * 6)):
        pts = np.cumsum(r.normal(0, 3, (6, 2)), axis=0) + [r.integers(0, w), r.integers(0, h)]; cv2.polylines(dk, [pts.astype(np.int32)], False, 0.8, 1, cv2.LINE_AA)
    f = f3(img); f = f * (1 - dk[..., None] * 0.85) + cv[..., None] * 0.9; return pack(np.clip(f, 0, 1), like=img)

reg("filmdot", V, "Film dot", [F("amount", "Amount", 50, 0, 100), F("size", "Dot size", 1.0, 0.3, 4), F("scratch", "Scratches", 50, 0, 100), SEED()], fx_filmdot, "Dust specks, hairs and scratches that flash on old film.", "dust scratches film")

ID = "filmdot"

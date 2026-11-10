"""blockdissolve: Block dissolve. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_color import *

def fx_blockdissolve(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); b = S(ctx, p["block"]); gh, gw = int(np.ceil(h / b)), int(np.ceil(w / b))
    r = np.random.default_rng(int(p["seed"]) + 11).random((gh, gw)).astype(np.float32); r = cv2.resize(r, (int(gw * b) + 1, int(gh * b) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]
    return _alpha_mul(img, (r >= pr).astype(np.float32))

reg("blockdissolve", C2, "Block dissolve", WIPE(50) + [F("block", "Block size", 28, 4, 200), SEED()], fx_blockdissolve, "Random squares of the picture disappear. Progress 100 = everything gone.", "pixel dissolve squares")

ID = "blockdissolve"

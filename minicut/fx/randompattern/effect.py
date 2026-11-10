"""randompattern: Random pattern. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_randompattern(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); s = S(ctx, p["cell"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s))
    grid = (r.random((gh, gw)) < a * 0.6).astype(np.uint8)
    if p["pattern"] == "stripes": grid = np.repeat((r.random((1, gw)) < a * 0.6).astype(np.uint8), gh, 0)
    elif p["pattern"] == "rows": grid = np.repeat((r.random((gh, 1)) < a * 0.6).astype(np.uint8), gw, 1)
    m = cv2.resize(grid, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w].astype(bool); out = img.copy(); k = int(r.integers(0, 3))
    if k == 0: out[m, :3] = 255 - out[m, :3]
    elif k == 1: out[m, :3] = out[m][:, [2, 0, 1]]
    else: sh = int(r.normal(0, w * 0.06)); out[m] = np.roll(img, sh, axis=1)[m]
    return out

reg("randompattern", G, "Random pattern", GP([F("cell", "Cell size", 30, 4, 200), CH("pattern", "Pattern", "blocks", [("blocks", "Blocks"), ("stripes", "Columns"), ("rows", "Rows")])]), fx_randompattern, "A random pattern of cells is inverted, color-swapped or shifted.", "checker mask")

ID = "randompattern"

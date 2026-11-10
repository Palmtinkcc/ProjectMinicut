"""checkwipe: Checker board wipe. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_checkwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); s = S(ctx, p["size"]); x, y = coords(h, w); i = np.floor(x / s); j = np.floor(y / s); nx = max(1, w / s)
    th = 0.5 * ((i + j) % 2) + 0.5 * (i / nx if p["sweep"] else np.random.default_rng(int(p["seed"])).random() * 0 + ((i * 0.618 + j * 0.382) % 1.0)); th = th * 0.98 + 0.01
    return _am(img, (pr < th).astype(np.float32))

reg("checkwipe", WP, "Checker board wipe", WIPE(40) + [F("size", "Square size", 40, 6, 240), B("sweep", "Sweep from the left", True), SEED()], fx_checkwipe, "Squares disappear in a chess-board pattern.", "squares chess transition")

ID = "checkwipe"

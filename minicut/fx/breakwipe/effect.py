"""breakwipe: Break. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_breakwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); yy = np.arange(h, dtype=np.float32); crack = w * 0.5 + (noise2(h, 1, 1, S(ctx, 40), int(p["seed"]))[:, 0] - 0.5) * w * p["jagged"] / 100.0 * 0.5
    m = (x < crack[:, None]).astype(np.float32); left = _am(img, m); right = _am(img, 1 - m); d = pr * w * 0.6 * ctx.k / ctx.k; a = p["tilt"] * pr
    L = affine(left, xform(h, w, -d, pr * h * 0.2, -a, 1.0, 0.0, 1.0)); R = affine(right, xform(h, w, d, pr * h * 0.3, a, 1.0, 1.0, 1.0)); return _over(L, R)

reg("breakwipe", WP, "Break", WIPE(40) + [F("jagged", "Crack roughness", 50, 0, 100), F("tilt", "Tilt", 25, 0, 90), SEED()], fx_breakwipe, "The picture breaks along a jagged crack and the two halves fall apart.", "split crack")

ID = "breakwipe"

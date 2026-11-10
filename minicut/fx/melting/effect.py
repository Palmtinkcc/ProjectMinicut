"""melting: Melting screen. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_melting(img, p, ctx):
    h, w = img.shape[:2]; rh, rw = ref_size(h, w); ox, oy = ref_origin()      # the media: the whole picture, unless the effect spills outside the media
    pr = prog(p, ctx); x, y = coords(h, w); s = S(ctx, p["width"]); xr, yr = x - ox, y - oy
    col = np.random.default_rng(int(p["seed"])).random(int(rw / s) + 3).astype(np.float32); col = cv2.resize(col[None, :], (rw, 1), interpolation=cv2.INTER_CUBIC)[0]
    col = col[np.clip(xr[0].astype(np.int32), 0, rw - 1)]
    drip = (0.3 + col * 0.7)[None, :] * pr * rh * 1.3 * (1 + 0.3 * np.sin(xr / (s * 3))); ysrc = y - drip * (0.4 + 0.6 * np.clip(yr / rh, 0, None)); return remap_clear(img, x, ysrc)       # what melts away leaves empty space at the top; nothing is mirrored back

reg("melting", WG, "Melting screen", WIPE(50) + [F("width", "Drip width", 30, 4, 200), SEED()], fx_melting, "The picture melts and drips down the screen.", "drip slime")

ID = "melting"

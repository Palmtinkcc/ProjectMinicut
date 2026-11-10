"""blocknoise: Block noise. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def fx_blocknoise(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); s = S(ctx, p["block"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); n = r.random((gh, gw)).astype(np.float32)
    n = cv2.resize(n, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]; n = np.clip((n - 0.5) * (1 + p["contrast"] / 40.0) + 0.5, 0, 1)
    return blend(img, ramp(n, [(0, p["c1"]), (1, p["c2"])]), None, p["mode"], p["opacity"] / 100.0)

reg("blocknoise", PR, "Block noise", [F("block", "Block size", 24, 2, 200), F("rate", "Changes / s", 8, 0, 60), F("contrast", "Contrast", 20, 0, 100), C("c1", "Dark", "#000000"), C("c2", "Light", "#ffffff"), MODE("overlay"), OPAC(60), SEED()], fx_blocknoise, "Randomly colored squares laid over the picture, changing by themselves.", "squares mosaic noise")

ID = "blocknoise"

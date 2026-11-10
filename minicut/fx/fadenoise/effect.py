"""fadenoise: Fade noise. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_fadenoise(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); s = S(ctx, p["grain"]); r = np.random.default_rng(int(p["seed"])).random((int(h / s) + 1, int(w / s) + 1)).astype(np.float32); n = cv2.resize(r, (int(w) + int(s), int(h) + int(s)), interpolation=cv2.INTER_NEAREST)[:h, :w]
    x = coords(h, w)[0] / w; f = n * (1 - p["sweep"] / 100.0) + x * (p["sweep"] / 100.0); soft = 0.15; return _am(img, 1 - sm(pr * (1 + soft) - soft, f - soft * 0.0, f + 1e-6 + soft) if False else np.clip((f - (pr * (1 + soft) - soft)) / soft, 0, 1))

reg("fadenoise", WP, "Fade noise", WIPE(40) + [F("grain", "Grain size", 2, 1, 40), F("sweep", "Sweep from the left", 0, 0, 100), SEED()], fx_fadenoise, "The picture fades away grain by grain, like film noise.", "grain dissolve static")

ID = "fadenoise"

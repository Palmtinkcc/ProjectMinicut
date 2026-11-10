"""ripplewater: Ripple water. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_ripplewater(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); dxs = np.zeros((h, w), np.float32); dys = np.zeros((h, w), np.float32); shade = np.zeros((h, w), np.float32); L = S(ctx, p["length"])
    for i in range(int(p["drops"])):
        r = np.random.default_rng(int(p["seed"]) * 37 + i); per = r.uniform(1.5, 3.0) / max(p["speed"], 0.05); ph = (ctx.lt + r.random() * per) % per; px, py = r.random() * w, r.random() * h; d = np.hypot(x - px, y - py); rad = ph * min(w, h) * 0.35 * p["speed"]
        env = np.exp(-((d - rad) / (L * 1.3)) ** 2) * np.exp(-ph / per * 2.5) * np.sin((d - rad) / L * 2 * np.pi); dxs += env * (x - px) / np.maximum(d, 1) * p["amount"] * ctx.k; dys += env * (y - py) / np.maximum(d, 1) * p["amount"] * ctx.k; shade += env
    out = remap(img, x + dxs, y + dys); f = f3(out) * (1 + shade[..., None] * 0.35 * p["shade"] / 100.0); return pack(np.clip(f, 0, 1), like=out)

reg("ripplewater", WG, "Ripple water", [I("drops", "Drops", 5, 1, 12), F("amount", "Strength", 10, 0, 60), F("length", "Ring width", 18, 4, 100), F("shade", "Light and dark", 60, 0, 100), F("speed", "Speed", 1.0, 0.2, 4), SEED()], fx_ripplewater, "Drops hit the water and rings spread out and fade.", "drops pond rings")

ID = "ripplewater"

"""paperburn: Paper burn. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_paperburn(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); ox, oy = w * p["x"] / 100.0, h * p["y"] / 100.0; far = max(np.hypot(ox, oy), np.hypot(w - ox, oy), np.hypot(ox, h - oy), np.hypot(w - ox, h - oy)); d = np.hypot(x - ox, y - oy) / far
    n = fbm(h, w, S(ctx, p["scale"]) * 2, int(p["seed"]), 0, 5); f = d * 0.7 + (1 - n) * 0.3; t = pr * 1.15 - 0.1; burnt = f < t; band = p["char"] / 100.0 * 0.12 + 0.01
    char = np.clip(1 - (f - t) / band, 0, 1) * (~burnt); glow = np.clip(1 - np.abs(f - t) / (band * 0.35), 0, 1)
    f3_ = f3(img) * (1 - char[..., None] * 0.9) + ramp(glow, [(0, "#000000"), (0.5, "#b32d00"), (1, "#ffcf5a")]) * glow[..., None] * 1.2; out = pack(np.clip(f3_, 0, 1), img[..., 3]); out = _am(out, (~burnt).astype(np.float32) * 1.0)
    sp = np.random.default_rng(int(p["seed"]) + 5); cv = np.zeros((h, w), np.float32)
    for _ in range(int(40 * min(1, pr * 3) * (1 if pr < 0.98 else 0))):
        px, py = sp.integers(0, w), sp.integers(0, h)
        if abs(f[py, px] - t) < 0.15: cv2.circle(cv, (int(px), int(py - pr * 40 * ctx.k)), max(1, int(S(ctx, 1.2))), 1.0, -1, cv2.LINE_AA)
    return blend(out, np.broadcast_to(bgr("#ffb347"), (h, w, 3)), glow_of(cv, 1.5 * ctx.k) * 1.5, "add", 1.0)

reg("paperburn", WP, "Paper burn", WIPE(40) + [F("x", "Fire starts X", 20, 0, 100), F("y", "Fire starts Y", 80, 0, 100), F("char", "Charred edge", 50, 0, 100), F("scale", "Edge roughness", 25, 4, 150), SEED()], fx_paperburn, "Like a sheet of paper that catches fire: a scorched edge, glowing embers and sparks.", "fire ash")

ID = "paperburn"

"""neural: Neural activity fade. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_neural(h, w, p, ctx, t):
    r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); P = np.stack([r.random(n) * w, r.random(n) * h], 1); ph = r.random(n) * 6.28
    P += np.stack([np.sin(t * 0.5 + ph) * w * 0.03, np.cos(t * 0.4 + ph * 1.3) * h * 0.03], 1); cv_l = np.zeros((h, w), np.float32); cv_n = np.zeros((h, w), np.float32); R = w * p["reach"] / 100.0 * 0.4
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(*(P[i] - P[j]))
            if d < R:
                pulse = 0.5 + 0.5 * np.sin(t * 2.5 + ph[i] + ph[j]); a = (1 - d / R) * pulse; cv2.line(cv_l, tuple(P[i].astype(int)), tuple(P[j].astype(int)), float(a), max(1, int(ctx.k)), cv2.LINE_AA)
    for i in range(n): cv2.circle(cv_n, tuple(P[i].astype(int)), max(2, int(S(ctx, 3))), float(0.5 + 0.5 * np.sin(t * 2 + ph[i])), -1, cv2.LINE_AA)
    gl = glow_of(cv_n, 5 * ctx.k) * 3 + glow_of(cv_l, 2 * ctx.k); v = np.clip(cv_l + cv_n + gl, 0, 1)[..., None]; return bgr(p["c1"]) * (1 - v) + bgr(p["c2"]) * v, None

reg("neural", BG, "Neural activity fade", BGP([I("count", "Neurons", 40, 8, 120), F("reach", "Reach", 45, 10, 100), C("c1", "Background", "#04060f"), C("c2", "Signals", "#7cc4ff")]), bgfx(g_neural), "A network of nodes and lines whose signals fade in and out like neurons firing.", "network brain nodes")

ID = "neural"

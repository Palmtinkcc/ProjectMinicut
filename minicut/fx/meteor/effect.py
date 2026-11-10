"""meteor: Meteor. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_particle import *

def fx_meteor(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); t = ctx.lt * p["speed"]; a = np.deg2rad(p["angle"]); d = np.array([np.cos(a), np.sin(a)])
    for i in range(int(p["count"])):
        r = np.random.default_rng(int(p["seed"]) * 51 + i); per = r.uniform(0.8, 2.2); ph = ((t + r.random() * per) % per) / per; L = S(ctx, p["length"]) * r.uniform(0.6, 1.4); start = np.array([r.uniform(-0.2, 1.2) * w, r.uniform(-0.3, 0.6) * h]); head = start + d * (ph * (w + h) * 0.9)
        for k in range(12): f = 1 - k / 12.0; q = head - d * L * k / 12.0; cv2.circle(cv, (int(q[0]), int(q[1])), max(1, int(S(ctx, p["size"] * 0.5) * f)), tuple(float(c * f * f) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)

reg("meteor", PT, "Meteor", PTP([F("length", "Tail length", 120, 10, 500), F("angle", "Direction", 35, -180, 180)])[:0] + [I("count", "Amount", 8, 1, 60), F("size", "Size", 5, 1, 30), F("length", "Tail length", 120, 10, 500), F("angle", "Direction", 35, -180, 180), F("speed", "Speed", 1.0, 0.1, 8), C("color", "Color", "#cfe8ff"), MODE("add"), OPAC(100), SEED()], fx_meteor, "Shooting stars with glowing tails.", "shooting star comet")

ID = "meteor"

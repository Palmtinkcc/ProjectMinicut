"""Repeat, Shake & transform and Move effects."""
from .kit import *

RP = "Repeat"
def _over(base, lay):
    """Alpha-over of two premultiplied-safe BGRA pictures: lay on top of base."""
    return blend(base, f3(lay), lay[..., 3].astype(np.float32) / 255.0, "over", 1.0) if base[..., 3].max() > 0 else lay
def _comp(copies, h, w):
    """Stack BGRA copies (first = bottom) with alpha-over, premultiplied."""
    acc = np.zeros((h, w, 3), np.float32); acc_a = np.zeros((h, w), np.float32)
    for c in copies:
        a = c[..., 3].astype(np.float32) * (1 / 255); acc = f3(c) * a[..., None] + acc * (1 - a[..., None]); acc_a = a + acc_a * (1 - a)
    return pack(acc / np.maximum(acc_a[..., None], 1e-4), acc_a)
def _small(img, sc): h, w = img.shape[:2]; return cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
def _place(img, M): return affine(img, M)


def fx_repgrid(img, p, ctx):
    h, w = img.shape[:2]; nx, ny = int(p["cols"]), int(p["rows"]); gap = p["gap"] / 100.0; small = _small(img, 1.0 / nx if nx >= ny else 1.0 / ny); small = cv2.resize(img, (max(1, int(w / nx * (1 - gap))), max(1, int(h / ny * (1 - gap)))), interpolation=cv2.INTER_AREA)
    out = np.zeros_like(img); cw, ch = w / nx, h / ny
    for j in range(ny):
        for i in range(nx):
            tile = small
            if p["mirror"]: tile = small[:, ::-1] if i % 2 else small; tile = tile[::-1] if j % 2 else tile
            x0 = int(i * cw + (cw - tile.shape[1]) / 2); y0 = int(j * ch + (ch - tile.shape[0]) / 2); out[y0:y0 + tile.shape[0], x0:x0 + tile.shape[1]] = tile
    return out
reg("repgrid", RP, "Grid repeat", [I("cols", "Columns", 3, 1, 12), I("rows", "Rows", 3, 1, 12), F("gap", "Gap", 6, 0, 60), B("mirror", "Mirror every other one", False)], fx_repgrid, "The picture is repeated in a grid of small copies.", "tile mosaic copies")


def fx_repline(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); ang = np.deg2rad(p["angle"]); step = p["distance"] * ctx.k; copies = []
    for i in range(n - 1, -1, -1):
        sc_ = p["size"] / 100.0 * (1 - p["shrink"] / 100.0 * i / max(1, n - 1)); M = xform(h, w, np.cos(ang) * step * i - np.cos(ang) * step * (n - 1) / 2 * p["center"], np.sin(ang) * step * i - np.sin(ang) * step * (n - 1) / 2 * p["center"], 0, sc_); c = _place(img, M)
        c[..., 3] = (c[..., 3] * (1 - p["fade"] / 100.0 * i / max(1, n - 1))).astype(np.uint8); copies.append(c)
    return _comp(copies, h, w)
reg("repline", RP, "Line repeat", [I("count", "Copies", 6, 2, 30), F("size", "Size", 50, 5, 120), F("distance", "Distance", 60, 0, 400), F("angle", "Angle", 0, -180, 180), F("shrink", "Shrink", 25, 0, 90), F("fade", "Fade", 30, 0, 100), F("center", "Centered", 1, 0, 1)], fx_repline, "Copies of the picture in a row, each smaller and fainter.", "array row copies")


def fx_repradial(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); R = p["radius"] * ctx.k; copies = []
    for i in range(n):
        a = 2 * np.pi * i / n + np.deg2rad(p["start"] + ctx.lt * p["spin"]); M = xform(h, w, np.cos(a) * R, np.sin(a) * R, np.rad2deg(a) * p["turn"] / 100.0, p["size"] / 100.0); copies.append(_place(img, M))
    return _comp(copies, h, w)
reg("repradial", RP, "Radial repeat", [I("count", "Copies", 6, 2, 36), F("radius", "Radius", 90, 0, 600), F("size", "Size of each", 45, 5, 150), F("turn", "Turn each", 100, 0, 100), F("start", "Start angle", 0, -180, 180), F("spin", "Spin (deg / s)", 20, -360, 360)], fx_repradial, "Copies of the picture placed around a circle.", "circle kaleidoscope ring")


def fx_reppath(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["count"]); copies = []
    for i in range(n):
        u = i / max(1, n - 1) + ctx.lt * p["speed"] * 0.1; u -= np.floor(u) if p["loop"] else 0
        if p["path"] == "wave": px = (u - 0.5) * w * 0.9; py = np.sin(u * 2 * np.pi * 2) * h * 0.25; rot = np.cos(u * 4 * np.pi) * 25
        elif p["path"] == "circle": px = np.cos(u * 2 * np.pi) * w * 0.3; py = np.sin(u * 2 * np.pi) * h * 0.3; rot = np.rad2deg(u * 2 * np.pi)
        else: rr = u * min(w, h) * 0.45; px = np.cos(u * 6 * np.pi) * rr; py = np.sin(u * 6 * np.pi) * rr; rot = np.rad2deg(u * 6 * np.pi)
        copies.append(_place(img, xform(h, w, px, py, rot * p["turn"] / 100.0, p["size"] / 100.0)))
    return _comp(copies, h, w)
reg("reppath", RP, "Repeat along path", [I("count", "Copies", 10, 2, 40), CH("path", "Path", "wave", [("wave", "Wave"), ("circle", "Circle"), ("spiral", "Spiral")]), F("size", "Size of each", 35, 5, 120), F("turn", "Turn with the path", 100, 0, 100), F("speed", "Speed", 1.0, -10, 10), B("loop", "Loop", True)], fx_reppath, "Copies of the picture placed along a wave, a circle or a spiral (and they can travel along it).", "trail curve snake")


def fx_repscatter(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); copies = []; t = ctx.lt * p["drift"]
    for i in range(n):
        ph = r.random(3) * 6.28; sc_ = r.uniform(min(p["min"], p["max"]), max(p["min"], p["max"], 1e-3)) / 100.0
        copies.append(_place(img, xform(h, w, (r.uniform(-0.5, 0.5) * w * p["spread"] / 50.0) + np.sin(t + ph[0]) * w * 0.02, (r.uniform(-0.5, 0.5) * h * p["spread"] / 50.0) + np.cos(t + ph[1]) * h * 0.02, r.normal(0, p["rot"]), sc_)))
    return _comp(copies, h, w)
reg("repscatter", RP, "Scatter repeat", [I("count", "Copies", 14, 2, 80), F("spread", "Spread", 60, 0, 100), F("min", "Smallest", 15, 2, 100), F("max", "Biggest", 40, 2, 150), F("rot", "Tilt", 20, 0, 90), F("drift", "Drift", 1.0, 0, 10), SEED()], fx_repscatter, "Copies scattered at random places, sizes and angles.", "random confetti copies")


# ------------------------------------------------------------------ shake & transform
SH = "Shake & transform"
def _tf(img, ctx, tx, ty, rot=0.0, sc_=1.0, cx=0.5, cy=0.5):
    h, w = img.shape[:2]; return affine(img, xform(h, w, tx * ctx.k, ty * ctx.k, rot, sc_, cx, cy))


def fx_shake(img, p, ctx):
    r = rng(ctx, p["seed"], p["speed"]); a = p["amount"]; return _tf(img, ctx, r.normal(0, a * 0.5), r.normal(0, a * 0.5), r.normal(0, p["tilt"] * 0.4))
reg("shake", SH, "Simple shake", [F("amount", "Strength", 12, 0, 100), F("tilt", "Tilt", 1.5, 0, 15), F("speed", "Shakes / s", 24, 1, 60), SEED()], fx_shake, "A quick random shake.", "jitter vibrate")


def fx_swing(img, p, ctx):
    ang = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["angle"]; return _tf(img, ctx, 0, 0, ang, 1.0, 0.5, p["pivot"] / 100.0)
reg("swing", SH, "Swing", [F("angle", "Angle", 12, 0, 90), F("speed", "Swings / s", 0.7, 0.05, 8), F("pivot", "Pivot height (0 = top)", 0, -50, 150)], fx_swing, "The picture swings from a point like a pendulum.", "pendulum rotate sway")


def fx_impact(img, p, ctx):
    ph = (ctx.lt * p["rate"]) % 1.0; k = np.exp(-ph * p["decay"]); r = np.random.default_rng(int(p["seed"]) + int(ctx.lt * p["rate"]) * 31); ang = r.uniform(0, 6.28)
    d = p["strength"] * k * np.cos(ph * 60); return _tf(img, ctx, np.cos(ang) * d, np.sin(ang) * d, r.normal(0, 1) * k * p["tilt"], 1 + p["zoom"] / 100.0 * k)
reg("impact", SH, "Impact shake", [F("strength", "Strength", 50, 0, 300), F("rate", "Hits / s", 1.0, 0.1, 8), F("decay", "Calms down", 6, 1, 20), F("tilt", "Tilt", 3, 0, 20), F("zoom", "Punch zoom", 6, 0, 40), SEED()], fx_impact, "A hard hit: a strong shake and a little zoom that calms down, over and over.", "punch hit bang")


def fx_handheld(img, p, ctx):
    h, w = img.shape[:2]; t = ctx.lt * p["speed"]; sd = int(p["seed"]); n = lambda k: (noise(8, 8, 2, sd + k, t)[4, 4] - 0.5) * 2 * 2.2
    s = 1 + p["amount"] / 400.0; return _tf(img, ctx, n(1) * p["amount"], n(2) * p["amount"], n(3) * p["amount"] * 0.04, s)
reg("handheld", SH, "Handheld camera", [F("amount", "Amount", 14, 0, 100), F("speed", "Speed", 1.5, 0.1, 10), SEED()], fx_handheld, "A smooth, slow wobble like a camera held in the hands.", "camera shake smooth")


def fx_earthquake(img, p, ctx):
    t = ctx.lt * p["speed"]; a = p["amount"]; return _tf(img, ctx, np.sin(t * 7.1) * a * 0.6 + np.sin(t * 17.3) * a * 0.4, np.sin(t * 11.7 + 1) * a, np.sin(t * 5.3) * p["tilt"])
reg("earthquake", SH, "Earthquake", [F("amount", "Strength", 30, 0, 200), F("tilt", "Tilt", 2, 0, 15), F("speed", "Speed", 2.0, 0.2, 10)], fx_earthquake, "A heavy, rumbling shake.", "rumble")


def fx_bounce(img, p, ctx):
    ph = (ctx.lt * p["speed"]) % 1.0; y = -abs(np.sin(ph * np.pi)) * p["height"]; sq = 1 - 0.12 * p["squash"] / 100.0 * (1 - abs(np.sin(ph * np.pi))); return _tf(img, ctx, 0, y, 0, 1.0 / sq if False else 1.0, 0.5, 1.0) if p["squash"] <= 0 else affine(img, np.float32([[1 + (1 - sq), 0, -img.shape[1] * (1 - sq) / 2], [0, sq, y * ctx.k + img.shape[0] * (1 - sq)]]))
reg("bounce", SH, "Bounce", [F("height", "Height", 60, 0, 400), F("speed", "Bounces / s", 1.2, 0.1, 6), F("squash", "Squash", 40, 0, 100)], fx_bounce, "The picture bounces up and down and squashes when it lands.", "jump ball")


def fx_wobbleskew(img, p, ctx):
    h, w = img.shape[:2]; k = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["amount"] / 100.0 * 0.35; M = np.float32([[1, k, -k * h / 2], [np.sin(ctx.lt * p["speed"] * 2 * np.pi + 1) * p["amount"] / 100.0 * 0.08, 1, 0]]); return affine(img, M)
reg("wobbleskew", SH, "Skew wobble", [F("amount", "Amount", 40, 0, 100), F("speed", "Wobbles / s", 0.8, 0.1, 6)], fx_wobbleskew, "The picture leans left and right like jelly.", "jelly lean")


# ------------------------------------------------------------------ move
MV = "Move"
def fx_slide(img, p, ctx):
    a = np.deg2rad(p["angle"]); d = np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["distance"]; return _tf(img, ctx, np.cos(a) * d, np.sin(a) * d)
reg("slide", MV, "Swing (slide)", [F("distance", "Distance", 60, 0, 600), F("angle", "Direction", 0, -180, 180), F("speed", "Cycles / s", 0.5, 0.05, 6)], fx_slide, "The picture slides back and forth in a straight line.", "sway pendulum move left right")


def fx_spin(img, p, ctx): return _tf(img, ctx, 0, 0, ctx.lt * p["speed"], 1.0, p["cx"] / 100.0, p["cy"] / 100.0)
reg("spin", MV, "Spin", [F("speed", "Speed (deg / s)", 90, -720, 720), F("cx", "Center X", 50, -50, 150), F("cy", "Center Y", 50, -50, 150)], fx_spin, "The picture turns around and around.", "rotate")


def fx_randdisp(img, p, ctx):
    r = rng(ctx, p["seed"], p["rate"]); return _tf(img, ctx, r.uniform(-1, 1) * p["x"], r.uniform(-1, 1) * p["y"])
reg("randdisp", MV, "Random displacement", [F("x", "Distance X", 80, 0, 600), F("y", "Distance Y", 50, 0, 600), F("rate", "Jumps / s", 4, 0.2, 30), SEED()], fx_randdisp, "The picture jumps to a new random place again and again.", "jump teleport")


def fx_pulse(img, p, ctx):
    s = 1 + np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["amount"] / 100.0 * 0.5; return _tf(img, ctx, 0, 0, 0, max(0.05, s))
reg("pulse", MV, "Pulse size", [F("amount", "Amount", 25, 0, 100), F("speed", "Pulses / s", 1.0, 0.1, 8)], fx_pulse, "The picture grows and shrinks like a heartbeat.", "heartbeat scale")


def fx_jitter(img, p, ctx):
    r = rng(ctx, p["seed"], p["rate"]); t = ctx.lt * p["rate"]; i = int(t); f = t - i; a = np.random.default_rng(int(p["seed"]) * 7 + i); b = np.random.default_rng(int(p["seed"]) * 7 + i + 1)
    va = a.uniform(-1, 1, 3); vb = b.uniform(-1, 1, 3); v = va * (1 - f) + vb * f; return _tf(img, ctx, v[0] * p["amount"], v[1] * p["amount"], v[2] * p["tilt"])
reg("jitter", MV, "Random jitter", [F("amount", "Amount", 8, 0, 100), F("tilt", "Tilt", 0.8, 0, 10), F("rate", "Speed", 10, 0.5, 40), SEED()], fx_jitter, "A small, nervous, smooth trembling.", "tremble")

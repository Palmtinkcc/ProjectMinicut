"""Particle effects (drawn over the picture) and simple 3D shapes."""
from .kit import *

PT = "Particle"
def PTP(extra=()): return list(extra) + [I("count", "Amount", 60, 1, 400), F("size", "Size", 4, 0.5, 40), F("speed", "Speed", 1.0, 0, 10), C("color", "Color", "#ffffff"), MODE("add"), OPAC(100), SEED()]
def _fin(img, canvas, glow, p, ctx):
    lay = np.clip(canvas + glow_of(canvas, glow * ctx.k) * 1.6, 0, 1.5)
    if lay.ndim == 2: lay = lay[..., None] * bgr(p["color"])
    return blend(img, lay, None, p["mode"], p["opacity"] / 100.0)
def _star(cv, x, y, r, a, col):
    for ang in (0, 90):
        d = np.deg2rad(ang); dx, dy = np.cos(d) * r, np.sin(d) * r; cv2.line(cv, (int(x - dx), int(y - dy)), (int(x + dx), int(y + dy)), (a * col[0], a * col[1], a * col[2]), 1, cv2.LINE_AA)
    r2 = r * 0.5
    for ang in (45, 135):
        d = np.deg2rad(ang); dx, dy = np.cos(d) * r2, np.sin(d) * r2; cv2.line(cv, (int(x - dx), int(y - dy)), (int(x + dx), int(y + dy)), (a * col[0] * 0.6, a * col[1] * 0.6, a * col[2] * 0.6), 1, cv2.LINE_AA)


def fx_starglow(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); t = ctx.lt * p["speed"]
    for i in range(int(p["count"])):
        x, y = r.random() * w, r.random() * h; ph = r.random() * 6.28; tw = max(0, np.sin(t * 2 + ph)); rad = S(ctx, p["size"]) * (0.5 + r.random()) * 2.5 * tw
        if rad > 1: _star(cv, x, y, rad, tw, col)
    return _fin(img, cv, 4, p, ctx)
reg("starglow", PT, "Star glow", PTP(), fx_starglow, "Twinkling four-point stars with a soft glow.", "sparkle twinkle")


def fx_fireworks(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col0 = bgr(p["color"]); n = int(p["bursts"]); t = ctx.lt * p["speed"]
    for b in range(n):
        r = np.random.default_rng(int(p["seed"]) * 100 + b); per = r.uniform(1.6, 2.6); cyc = int((t + b * 0.7) // per); ph = ((t + b * 0.7) % per) / per; rr = np.random.default_rng(int(p["seed"]) * 100 + b * 7 + cyc)
        cx, cy = rr.uniform(0.2, 0.8) * w, rr.uniform(0.2, 0.55) * h; hue = rr.random(); col = hsv_bgr(hue, 0.5, 1.0) * 0.7 + col0 * 0.3 if p["rainbow"] else col0; ang = rr.random(int(p["count"])) * 6.28; spd = rr.uniform(0.4, 1.0, int(p["count"])) * h * 0.4
        if ph < 0.18: cv2.circle(cv, (int(cx), int(h - (h - cy) * ph / 0.18)), max(1, int(S(ctx, 2))), (1, 1, 1), -1, cv2.LINE_AA)
        else:
            u = (ph - 0.18) / 0.82; fade = (1 - u) ** 1.5
            for k in range(len(ang)):
                x = cx + np.cos(ang[k]) * spd[k] * u ** 0.6; y = cy + np.sin(ang[k]) * spd[k] * u ** 0.6 + u * u * h * 0.25; cv2.circle(cv, (int(x), int(y)), max(1, int(S(ctx, p["size"] * 0.5))), tuple(float(c * fade) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 4, p, ctx)
reg("fireworks", PT, "Fireworks particle", [I("bursts", "Fireworks", 3, 1, 8), I("count", "Sparks each", 70, 10, 250), F("size", "Size", 4, 1, 20), F("speed", "Speed", 1.0, 0.2, 5), C("color", "Color", "#ffd27a"), B("rainbow", "Every one a different color", True), MODE("add"), OPAC(100), SEED()], fx_fireworks, "Rockets that burst into sparks.", "explosion sparks")


def fx_dotsfield(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); s = S(ctx, p["spacing"]); t = ctx.lt * p["speed"]; yy, xx = np.mgrid[0:int(h / s) + 2, 0:int(w / s) + 2]
    for j in range(yy.shape[0]):
        for i in range(xx.shape[1]):
            ph = np.sin(i * 1.7 + j * 2.3) * 6.28; k = 0.5 + 0.5 * np.sin(t * 2 + ph); cx, cy = i * s + np.sin(t + ph) * s * 0.3, j * s + np.cos(t * 0.8 + ph) * s * 0.3
            if p["layout"] == "random": cx, cy = (np.sin(i * 12.9 + j * 78.2) * 43758 % 1) * w, (np.sin(i * 39.3 + j * 11.1) * 43758 % 1) * h
            cv2.circle(cv, (int(cx), int(cy)), max(1, int(S(ctx, p["size"]) * (0.4 + k * 0.8))), tuple(float(c * k) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 2, p, ctx)
reg("dotsfield", PT, "Dots field", [F("spacing", "Spacing", 28, 8, 120), F("size", "Dot size", 4, 1, 30), F("speed", "Speed", 1.0, 0, 10), CH("layout", "Layout", "grid", [("grid", "Grid"), ("random", "Random")]), C("color", "Color", "#9be7ff"), MODE("add"), OPAC(100), SEED()], fx_dotsfield, "A field of dots that breathe and drift.", "points grid")


def fx_meteor(img, p, ctx):
    h, w = img.shape[:2]; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); t = ctx.lt * p["speed"]; a = np.deg2rad(p["angle"]); d = np.array([np.cos(a), np.sin(a)])
    for i in range(int(p["count"])):
        r = np.random.default_rng(int(p["seed"]) * 51 + i); per = r.uniform(0.8, 2.2); ph = ((t + r.random() * per) % per) / per; L = S(ctx, p["length"]) * r.uniform(0.6, 1.4); start = np.array([r.uniform(-0.2, 1.2) * w, r.uniform(-0.3, 0.6) * h]); head = start + d * (ph * (w + h) * 0.9)
        for k in range(12): f = 1 - k / 12.0; q = head - d * L * k / 12.0; cv2.circle(cv, (int(q[0]), int(q[1])), max(1, int(S(ctx, p["size"] * 0.5) * f)), tuple(float(c * f * f) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)
reg("meteor", PT, "Meteor", PTP([F("length", "Tail length", 120, 10, 500), F("angle", "Direction", 35, -180, 180)])[:0] + [I("count", "Amount", 8, 1, 60), F("size", "Size", 5, 1, 30), F("length", "Tail length", 120, 10, 500), F("angle", "Direction", 35, -180, 180), F("speed", "Speed", 1.0, 0.1, 8), C("color", "Color", "#cfe8ff"), MODE("add"), OPAC(100), SEED()], fx_meteor, "Shooting stars with glowing tails.", "shooting star comet")


def fx_galaxy(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]) * 6; arms = int(p["arms"]); rad = r.random(n) ** 0.7; arm = r.integers(0, arms, n); ang = rad * p["twist"] * 0.2 + arm * 2 * np.pi / arms + r.normal(0, 0.18, n) * (1 - rad * 0.5) + ctx.lt * p["speed"] * 0.3 / (0.3 + rad)
    R = min(w, h) * 0.45 * p["size"] / 50.0; x = w * p["x"] / 100.0 + np.cos(ang) * rad * R * 1.0; y = h * p["y"] / 100.0 + np.sin(ang) * rad * R * 0.55; cv = np.zeros((h, w, 3), np.float32); c0, c1 = bgr(p["core"]), bgr(p["color"])
    ok = (x >= 0) & (x < w) & (y >= 0) & (y < h); xi, yi = x[ok].astype(int), y[ok].astype(int); col = c0[None] * (1 - rad[ok, None]) + c1[None] * rad[ok, None]; np.add.at(cv, (yi, xi), col * (1.2 - rad[ok, None] * 0.6) * 0.6)
    core = disc(h, w, w * p["x"] / 100.0, h * p["y"] / 100.0, R * 0.12, R * 0.25)[..., None] * c0 * 0.9; cv = glow_of(cv, 1.2 * ctx.k) * 1.5 + glow_of(cv, 6 * ctx.k) * 1.5 + core; return blend(img, np.clip(cv, 0, 1.5), None, p["mode"], p["opacity"] / 100.0)
reg("galaxy", PT, "Galaxy", [I("count", "Stars", 600, 50, 4000), I("arms", "Arms", 3, 1, 8), F("twist", "Twist", 40, 0, 100), F("size", "Size", 60, 10, 150), F("speed", "Spin", 1.0, -10, 10), F("x", "Center X", 50, 0, 100), F("y", "Center Y", 50, 0, 100), C("core", "Core", "#fff0c0"), C("color", "Arms", "#6fa8ff"), MODE("add"), OPAC(100), SEED()], fx_galaxy, "A spiral galaxy of stars that slowly turns.", "spiral stars space")


def fx_part3d(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); P = r.uniform(-1, 1, (n, 3)); t = ctx.lt * p["speed"] * 0.25; z = (P[:, 2] * 0.5 + 0.5 - t) % 1.0; zz = 0.15 + z * 2.0
    sx = w / 2 + P[:, 0] / zz * w * 0.45 * 0.5; sy = h / 2 + P[:, 1] / zz * h * 0.45 * 0.5; cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"])
    for i in range(n):
        f = np.clip(1 - z[i], 0, 1); rad = S(ctx, p["size"]) * (0.3 + 1.2 * f); x, y = int(sx[i]), int(sy[i])
        if -rad < x < w + rad and -rad < y < h + rad: cv2.circle(cv, (x, y), max(1, int(rad)), tuple(float(c * (0.2 + 0.8 * f)) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)
reg("part3d", PT, "3D particles", PTP(), fx_part3d, "Particles in 3D space that fly towards you.", "space fly through warp stars")


def fx_bokeh(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); cv = np.zeros((h, w, 3), np.float32); t = ctx.lt * p["speed"]; cols = [bgr(p["color"]), bgr(p["color2"])]
    for i in range(int(p["count"])):
        dep = r.random(); rad = S(ctx, p["size"]) * (0.5 + dep * 1.6); x = (r.random() * w + t * w * 0.04 * (0.3 + dep) * 1.0 + np.sin(t + r.random() * 6) * w * 0.02) % (w + 2 * rad) - rad; y = (r.random() * h - t * h * 0.02 * (0.3 + dep)) % (h + 2 * rad) - rad
        lay = np.zeros((h, w, 3), np.float32) if False else None; c = cols[i % 2] * (0.25 + 0.5 * dep) * (0.5 + 0.5 * np.sin(t * 1.5 + i)); cv2.circle(cv, (int(x), int(y)), max(2, int(rad)), tuple(float(v) for v in c), -1, cv2.LINE_AA)
    return blend(img, np.clip(cv_blur(cv, 1.5 * ctx.k), 0, 1.5), None, p["mode"], p["opacity"] / 100.0)
def cv_blur(a, s): return glow_of(a, s)
reg("bokeh", PT, "Bokeh parallax", [I("count", "Amount", 30, 3, 150), F("size", "Size", 22, 4, 100), F("speed", "Speed", 1.0, 0, 10), C("color", "Color 1", "#ffd27a"), C("color2", "Color 2", "#8fd3ff"), MODE("screen"), OPAC(100), SEED()], fx_bokeh, "Soft glowing circles drifting at different speeds, so near ones move more than far ones.", "lights defocus circles depth")


def fx_constellation(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); ph = r.random((n, 2)) * 6.28; t = ctx.lt * p["speed"]; P = np.stack([(r.random(n) * w + np.sin(t * 0.7 + ph[:, 0]) * w * 0.04), (r.random(n) * h + np.cos(t * 0.6 + ph[:, 1]) * h * 0.04)], 1)
    cv = np.zeros((h, w, 3), np.float32); col = bgr(p["color"]); R = w * p["reach"] / 100.0 * 0.3
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(*(P[i] - P[j]))
            if d < R: a = 1 - d / R; cv2.line(cv, tuple(P[i].astype(int)), tuple(P[j].astype(int)), tuple(float(c * a * 0.8) for c in col), 1, cv2.LINE_AA)
    for i in range(n): cv2.circle(cv, tuple(P[i].astype(int)), max(1, int(S(ctx, p["size"]))), tuple(float(c) for c in col), -1, cv2.LINE_AA)
    return _fin(img, cv, 3, p, ctx)
reg("constellation", PT, "Constellation", [I("count", "Stars", 40, 5, 140), F("reach", "Line reach", 50, 5, 100), F("size", "Star size", 2.5, 0.5, 15), F("speed", "Speed", 1.0, 0, 10), C("color", "Color", "#dbeaff"), MODE("add"), OPAC(100), SEED()], fx_constellation, "Stars joined by thin lines when they are close to each other.", "network dots lines")


def fx_depthpart(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); L = lum8(img); t = ctx.lt * p["speed"]; cv = np.zeros((h, w, 3), np.float32); f = f3(img)
    for i in range(n):
        x0, y0 = r.random() * w, r.random() * h; ph = r.random() * 6.28; xi, yi = int(np.clip(x0, 0, w - 1)), int(np.clip(y0, 0, h - 1)); d = float(L[yi, xi]); x = (x0 + np.sin(t + ph) * w * 0.05 * (0.3 + d)) % w; y = (y0 - t * h * 0.05 * (0.3 + d)) % h
        c = f[yi, xi] * (0.6 + 0.6 * d) if p["from_picture"] else bgr(p["color"]) * (0.4 + 0.6 * d); cv2.circle(cv, (int(x), int(y)), max(1, int(S(ctx, p["size"]) * (0.3 + d * 1.4))), tuple(float(v) for v in c), -1, cv2.LINE_AA)
    return _fin(img, cv, 2.5, p, ctx)
reg("depthpart", PT, "Depth particles", [I("count", "Amount", 120, 10, 500), F("size", "Size", 4, 0.5, 30), F("speed", "Speed", 1.0, 0, 10), B("from_picture", "Use the picture's colors", True), C("color", "Color", "#ffffff"), MODE("add"), OPAC(100), SEED()], fx_depthpart, "Particles that are bigger, brighter and faster over the bright (near) parts of the picture.", "parallax dust")


# ------------------------------------------------------------------ 3D object: the media as the skin of a simple 3D shape
OB = "3D object"
def _rot(ax, ay, az):
    cx, sx, cy, sy, cz, sz = np.cos(ax), np.sin(ax), np.cos(ay), np.sin(ay), np.cos(az), np.sin(az)
    return np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
def OBP(extra=()): return list(extra) + [F("size", "Size", 70, 10, 200), F("rx", "Tilt X", 15, -180, 180), F("ry", "Turn Y", 25, -180, 180), F("rz", "Roll", 0, -180, 180), F("spin", "Spin (deg / s)", 30, -360, 360), F("light", "Shading", 50, 0, 100)]
def _shade(rgba, n, light):
    k = 1 - light / 100.0 * (1 - np.clip(0.35 + 0.65 * (n @ np.array([-0.4, -0.5, 0.75])), 0, 1)); out = rgba.copy(); out[..., :3] = np.clip(rgba[..., :3].astype(np.float32) * k[..., None], 0, 255).astype(np.uint8); return out


def fx_sphere(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); R = p["size"] / 100.0 * 0.5; X, Y = x / R, y / R; r2 = X * X + Y * Y; ins = r2 < 1; Z = np.sqrt(np.clip(1 - r2, 0, 1)); N = np.stack([X, Y, -Z], -1)
    Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); M = N @ Rm; lon = np.arctan2(M[..., 0], -M[..., 2]); lat = np.arcsin(np.clip(M[..., 1], -1, 1))
    ti = ref_crop(img); th_, tw_ = ti.shape[:2]; tex = remap(ti, (lon / (2 * np.pi) + 0.5) * tw_, (lat / np.pi + 0.5) * th_, cv2.BORDER_WRAP); out = _shade(tex, N, p["light"]); aa = np.clip((1 - np.sqrt(r2)) * R * h / 1.5, 0, 1); out[..., 3] = (out[..., 3] * aa).astype(np.uint8); return out
reg("sphere", OB, "Sphere", OBP(), fx_sphere, "The picture wrapped around a turning ball.", "globe ball planet")


def fx_cylinder(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); R = p["size"] / 100.0 * 0.5; X = x / R; ins = np.abs(X) < 1; ang = np.arcsin(np.clip(X, -1, 1)) + np.deg2rad(p["ry"] + ctx.lt * p["spin"])
    u = (ang / (2 * np.pi)) % 1.0; ti = ref_crop(img); th_, tw_ = ti.shape[:2]; yy = (y / (R * 2.6) + 0.5) * th_; tex = remap(ti, u * tw_, yy, cv2.BORDER_REFLECT); N = np.stack([X, np.zeros_like(X), -np.sqrt(np.clip(1 - X * X, 0, 1))], -1); out = _shade(tex, N, p["light"])
    a = ins.astype(np.float32) * (np.abs(y) < R * 1.3); out[..., 3] = (out[..., 3] * cv2.GaussianBlur(a, (0, 0), 0.8)).astype(np.uint8); return out
reg("cylinder", OB, "Cylinder", OBP(), fx_cylinder, "The picture wrapped around a turning can.", "tube roll")


def _quad(img, corners, out_size):
    h, w = img.shape[:2]; src = np.float32([[0, 0], [w, 0], [w, h], [0, h]]); M = cv2.getPerspectiveTransform(src, np.float32(corners)); return cv2.warpPerspective(img, M, (out_size[1], out_size[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _project(pts, Rm, h, w, size, persp):
    p3 = pts @ Rm.T; zc = 3.2 - p3[:, 2] * persp; rh = ref_size(h, w)[0]; sx = w / 2 + p3[:, 0] / zc * rh * size * 2.2; sy = h / 2 + p3[:, 1] / zc * rh * size * 2.2; return np.stack([sx, sy], 1), p3


def fx_cube(img, p, ctx):
    h, w = img.shape[:2]; ti = ref_crop(img); Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); s = 0.5
    V = np.array([[-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s], [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]], np.float32); faces = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
    P2, P3 = _project(V, Rm, h, w, p["size"] / 100.0, p["persp"] / 100.0); out = np.zeros_like(img); order = sorted(range(6), key=lambda i: -np.mean(P3[list(faces[i])][:, 2]) * -1)
    for fi in sorted(range(6), key=lambda i: np.mean(P3[list(faces[i])][:, 2])):
        q = faces[fi]; nrm = np.cross(P3[q[1]] - P3[q[0]], P3[q[2]] - P3[q[1]])
        if nrm[2] > 0: continue
        face = _quad(ti, P2[list(q)], (h, w)); face = _shade(face, np.broadcast_to(-nrm / (np.linalg.norm(nrm) + 1e-6), (h, w, 3)), p["light"]); a = face[..., 3:4].astype(np.float32) / 255; out = (face * a + out * (1 - a)).astype(np.uint8); out[..., 3] = np.maximum(out[..., 3], face[..., 3])
    return out
reg("cube", OB, "Cube", OBP([F("persp", "Perspective", 60, 0, 100)]), fx_cube, "The picture on all six sides of a turning cube.", "box dice")


def fx_card(img, p, ctx):
    h, w = img.shape[:2]; Rm = _rot(np.deg2rad(p["rx"]), np.deg2rad(p["ry"] + ctx.lt * p["spin"]), np.deg2rad(p["rz"])); rh_, rw_ = ref_size(h, w); s = 0.5 * rw_ / rh_; ti = ref_crop(img)
    V = np.array([[-s, -0.5, 0], [s, -0.5, 0], [s, 0.5, 0], [-s, 0.5, 0]], np.float32); P2, P3 = _project(V, Rm, h, w, p["size"] / 100.0 / (w / h) * 1.0 * (w / h), p["persp"] / 100.0)
    out = _quad(ti, P2, (h, w)); nrm = np.cross(P3[1] - P3[0], P3[2] - P3[1])
    if nrm[2] > 0 and not p["both"]: out[..., 3] = 0
    return _shade(out, np.broadcast_to(-np.abs(nrm) / (np.linalg.norm(nrm) + 1e-6), (h, w, 3)), p["light"] * 0.5)
reg("card", OB, "Card flip", OBP([F("persp", "Perspective", 60, 0, 100), B("both", "Show the back too", True)]), fx_card, "The picture as a flat card that turns and tilts in 3D space.", "flip rotate perspective plane")

"""Wipes, breaks and shatter. Progress 0 = the picture is whole, 100 = it is completely gone. Set it by hand, or let it run by itself
(Run by itself = seconds it takes; Start after = a delay; Reverse = the picture appears instead)."""
from .kit import *

WP = "Wipes & shatter"
def _am(img, m):
    out = img.copy(); out[..., 3] = np.clip(img[..., 3].astype(np.float32) * m, 0, 255).astype(np.uint8); return out
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def _over(base, top):
    a = top[..., 3:4].astype(np.float32) / 255.0; ba = base[..., 3:4].astype(np.float32) / 255.0; oa = a + ba * (1 - a)
    rgb = (top[..., :3] * a + base[..., :3].astype(np.float32) * ba * (1 - a)) / np.maximum(oa, 1e-4); return np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), (oa[..., 0] * 255).astype(np.uint8)])


def _paste(canvas, crop, x0, y0, M):
    """Warp `crop` (which sits at x0, y0 of the picture) with the 2x3 matrix M (picture coordinates) and put it over the canvas.
    Only the small window that the piece lands in is worked on."""
    h, w = canvas.shape[:2]; ch, cw = crop.shape[:2]; A = M[:, :2]; t = M[:, 2]
    pts = np.array([[x0, y0], [x0 + cw, y0], [x0 + cw, y0 + ch], [x0, y0 + ch]], np.float32) @ A.T + t
    wx0, wy0 = int(max(0, np.floor(pts[:, 0].min()) - 1)), int(max(0, np.floor(pts[:, 1].min()) - 1)); wx1, wy1 = int(min(w, np.ceil(pts[:, 0].max()) + 2)), int(min(h, np.ceil(pts[:, 1].max()) + 2))
    if wx1 <= wx0 or wy1 <= wy0: return canvas
    Mw = np.hstack([A, (t + A @ np.array([x0, y0]) - np.array([wx0, wy0]))[:, None]]).astype(np.float32)
    win = cv2.warpAffine(np.ascontiguousarray(crop), Mw, (wx1 - wx0, wy1 - wy0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)); canvas[wy0:wy1, wx0:wx1] = _over(canvas[wy0:wy1, wx0:wx1], win); return canvas


def fx_blackbar(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); co, ln = (y, h) if p["dir"] == "horizontal" else (x, w); d = np.minimum(co, ln - 1 - co) / ln; m = (d < pr * 0.5).astype(np.float32); m = cv2.GaussianBlur(m, (0, 0), max(0.4, p["soft"] * ctx.k * 0.3))
    if p["cut"]: return _am(img, 1 - m)
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m, "over", 1.0)
reg("blackbar", WP, "Black bar", WIPE(40) + [CH("dir", "Bars", "horizontal", [("horizontal", "Top and bottom"), ("vertical", "Left and right")]), C("color", "Color", "#000000"), F("soft", "Soft edge", 0, 0, 20), B("cut", "Cut away instead of covering", False)], fx_blackbar, "Bars close in from the edges, like the black bars of a film.", "cinema letterbox")


def fx_burnwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = fbm(h, w, S(ctx, p["scale"]) * 2, int(p["seed"]), 0, 5); y = 1 - coords(h, w)[1] / h; f = n * 0.55 + y * 0.45; t = pr * 1.3 - 0.15; burnt = f < t; edge = np.clip(1 - np.abs(f - t) / (p["edge"] / 100.0 * 0.12 + 1e-3), 0, 1)
    out = _am(img, (~burnt).astype(np.float32)); ember = ramp(edge, [(0, "#1a0500"), (0.4, "#ff2a00"), (0.75, "#ff9a00"), (1.0, "#fff1a8")]); inside = (edge > 0) & (~burnt | (edge > 0.5)); lay = np.where(inside[..., None], ember, 0)
    ch = np.clip((f - t) / 0.06, 0, 1) < 1; return blend(out, lay.astype(np.float32), np.clip(edge * 1.3, 0, 1) * (img[..., 3] * (1 / 255)), "over", 1.0)
reg("burnwipe", WP, "Burning wipe", WIPE(40) + [F("scale", "Noise size", 30, 5, 200), F("edge", "Fire width", 50, 5, 100), SEED()], fx_burnwipe, "The picture burns away from the bottom with a glowing fire edge.", "fire burn")


def fx_breakwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); yy = np.arange(h, dtype=np.float32); crack = w * 0.5 + (noise2(h, 1, 1, S(ctx, 40), int(p["seed"]))[:, 0] - 0.5) * w * p["jagged"] / 100.0 * 0.5
    m = (x < crack[:, None]).astype(np.float32); left = _am(img, m); right = _am(img, 1 - m); d = pr * w * 0.6 * ctx.k / ctx.k; a = p["tilt"] * pr
    L = affine(left, xform(h, w, -d, pr * h * 0.2, -a, 1.0, 0.0, 1.0)); R = affine(right, xform(h, w, d, pr * h * 0.3, a, 1.0, 1.0, 1.0)); return _over(L, R)
reg("breakwipe", WP, "Break", WIPE(40) + [F("jagged", "Crack roughness", 50, 0, 100), F("tilt", "Tilt", 25, 0, 90), SEED()], fx_breakwipe, "The picture breaks along a jagged crack and the two halves fall apart.", "split crack")


def fx_checkwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); s = S(ctx, p["size"]); x, y = coords(h, w); i = np.floor(x / s); j = np.floor(y / s); nx = max(1, w / s)
    th = 0.5 * ((i + j) % 2) + 0.5 * (i / nx if p["sweep"] else np.random.default_rng(int(p["seed"])).random() * 0 + ((i * 0.618 + j * 0.382) % 1.0)); th = th * 0.98 + 0.01
    return _am(img, (pr < th).astype(np.float32))
reg("checkwipe", WP, "Checker board wipe", WIPE(40) + [F("size", "Square size", 40, 6, 240), B("sweep", "Sweep from the left", True), SEED()], fx_checkwipe, "Squares disappear in a chess-board pattern.", "squares chess transition")


def fx_circlewipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); cx, cy = w * p["cx"] / 100.0, h * p["cy"] / 100.0; far = max(np.hypot(cx, cy), np.hypot(w - cx, cy), np.hypot(cx, h - cy), np.hypot(w - cx, h - cy)); r = pr * far
    m = disc(h, w, cx, cy, r, max(1.0, p["feather"] * ctx.k)); return _am(img, m if p["hole"] else 1 - m)
reg("circlewipe", WP, "Circle wipe mask", WIPE(40) + [F("cx", "Center X", 50, 0, 100), F("cy", "Center Y", 50, 0, 100), F("feather", "Soft edge", 8, 0, 100), B("hole", "A hole opens (off: the picture shrinks to the circle)", True)], fx_circlewipe, "A circle grows and wipes the picture away.", "iris round")


def fx_lumakey(img, p, ctx):
    f = f3(img)
    if p["key"] == "color":
        k = bgr(p["color"]); d = np.sqrt(((f - k) ** 2).sum(-1)) / 1.732; m = sm(d, p["tol"] / 100.0 * 0.6, p["tol"] / 100.0 * 0.6 + p["soft"] / 100.0 * 0.4 + 1e-3)
        out = _am(img, 1 - m if p["invert"] else m); return out
    L = lum(f); m = sm(L, p["low"] / 100.0, p["low"] / 100.0 + p["soft"] / 100.0 * 0.3 + 1e-3) * (1 - sm(L, p["high"] / 100.0, p["high"] / 100.0 + p["soft"] / 100.0 * 0.3 + 1e-3)); return _am(img, m if p["invert"] else 1 - m)
reg("lumakey", WP, "Color / luma key", [CH("key", "Key out", "luma", [("luma", "By brightness"), ("color", "By color")]), F("low", "Brightness from", 0, 0, 100), F("high", "Brightness up to", 15, 0, 100), C("color", "Key color", "#00ff00"), F("tol", "Color range", 35, 0, 100), F("soft", "Soft edge", 30, 0, 100), B("invert", "Keep the keyed part instead", False)], fx_lumakey,
    "Makes the dark parts, or one color (green screen), see-through.", "chroma key green screen luminance")


def fx_fadenoise(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); s = S(ctx, p["grain"]); r = np.random.default_rng(int(p["seed"])).random((int(h / s) + 1, int(w / s) + 1)).astype(np.float32); n = cv2.resize(r, (int(w) + int(s), int(h) + int(s)), interpolation=cv2.INTER_NEAREST)[:h, :w]
    x = coords(h, w)[0] / w; f = n * (1 - p["sweep"] / 100.0) + x * (p["sweep"] / 100.0); soft = 0.15; return _am(img, 1 - sm(pr * (1 + soft) - soft, f - soft * 0.0, f + 1e-6 + soft) if False else np.clip((f - (pr * (1 + soft) - soft)) / soft, 0, 1))
reg("fadenoise", WP, "Fade noise", WIPE(40) + [F("grain", "Grain size", 2, 1, 40), F("sweep", "Sweep from the left", 0, 0, 100), SEED()], fx_fadenoise, "The picture fades away grain by grain, like film noise.", "grain dissolve static")


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


def fx_squarebreak(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); nx = int(p["cols"]); s = w / nx; ny = int(np.ceil(h / s)); r = np.random.default_rng(int(p["seed"])); canvas = np.zeros_like(img); order = []
    for j in range(ny):
        for i in range(nx):
            dd = np.hypot((i + 0.5) / nx - p["x"] / 100.0, ((j + 0.5) * s - h * p["y"] / 100.0) / w); lp = np.clip((pr * (1 + 0.8) - dd * 0.9 - r.random() * 0.25) / 0.8, 0, 1); order.append((lp, i, j, r.normal(0, 1)))
    for lp, i, j, rv in sorted(order, key=lambda o: -o[0]):
        x0, y0 = int(i * s), int(j * s); x1, y1 = int(min(w, (i + 1) * s)) + 1, int(min(h, (j + 1) * s)) + 1; tile = img[y0:y1, x0:x1]
        if tile.size == 0: continue
        if lp <= 0: canvas[y0:y1, x0:x1] = tile; continue
        if lp >= 1: continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; sc_ = 1 - lp * 0.7; M = cv2.getRotationMatrix2D((cx, cy), rv * 60 * lp, sc_); M[1, 2] += lp * lp * h * p["fall"] / 100.0 * (0.5 + 0.5 * abs(rv)); M[0, 2] += rv * lp * s * 0.8
        piece = _am(tile, 1 - lp * 0.6); canvas = _paste(canvas, piece, x0, y0, M)
    return canvas
reg("squarebreak", WP, "Square break 3D", WIPE(40) + [I("cols", "Squares across", 12, 3, 30), F("fall", "Fall", 60, 0, 200), F("x", "Starts at X", 50, 0, 100), F("y", "Starts at Y", 50, 0, 100), SEED()], fx_squarebreak, "The picture breaks into squares that turn, shrink and fall away, starting from a point.", "tiles fall cubes")


def fx_plasmawipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = norm_coords(h, w); t = ctx.lt * p["speed"]; k = 12.0 / max(1.0, p["scale"] / 20.0)
    v = (np.sin(x * k + t) + np.sin(y * k * 0.9 - t * 1.3) + np.sin((x + y) * k * 0.7 + t * 0.7) + np.sin(np.sqrt(x * x + y * y) * k * 1.3 - t)) / 8 + 0.5; f = v * 0.5 + (coords(h, w)[0] / w) * 0.5; th = pr * 1.2 - 0.1
    m = (f > th).astype(np.float32); e = np.clip(1 - np.abs(f - th) / 0.06, 0, 1); out = _am(img, m); return blend(out, ramp(0.5 + 0.5 * np.sin(v * 20 + t), [(0, p["c1"]), (1, p["c2"])]), e, "add", 1.0)
reg("plasmawipe", WP, "Plasma wipe", WIPE(40) + [F("scale", "Pattern size", 30, 3, 100), F("speed", "Speed", 1.5, 0, 10), C("c1", "Color 1", "#ff2bd6"), C("c2", "Color 2", "#27e1ff")], fx_plasmawipe, "A bubbling plasma front eats the picture, glowing at its edge.", "energy transition")


def fx_liquidwipe(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); x, y = coords(h, w); a = np.deg2rad(p["angle"]); d = (x - w / 2) * np.cos(a) + (y - h / 2) * np.sin(a); ext = abs(w * np.cos(a)) + abs(h * np.sin(a)); wob = (fbm(h, w, S(ctx, 70), int(p["seed"]), ctx.lt * 0.8, 3) - 0.5) * ext * p["wobble"] / 100.0 + np.sin(coords(h, w)[1] / S(ctx, 40) + ctx.lt * 3) * ext * 0.01
    pos = (pr * 1.2 - 0.1) * ext - ext / 2; m = sm(d + wob, pos - 1.5, pos + 1.5); rim = np.clip(1 - np.abs(d + wob - pos) / (S(ctx, 10)), 0, 1) ** 2; out = _am(img, m); return blend(out, np.ones((h, w, 3), np.float32), rim * 0.6 * m, "add", 1.0)
reg("liquidwipe", WP, "Liquid wipe", WIPE(40) + [F("angle", "Direction", 0, -180, 180), F("wobble", "Wobble", 25, 0, 100), SEED()], fx_liquidwipe, "A wavy, liquid edge sweeps across and removes the picture.", "wave transition sweep")


def fx_shatter(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = int(p["pieces"]); r = np.random.default_rng(int(p["seed"])); sites = np.stack([r.random(n) * w, r.random(n) * h], 1); x, y = coords(h, w)
    lab = np.zeros((h, w), np.int32); best = np.full((h, w), 1e18, np.float32)
    for i, (sx, sy) in enumerate(sites): d = (x - sx) ** 2 + (y - sy) ** 2; upd = d < best; best[upd] = d[upd]; lab[upd] = i
    cx0, cy0 = w * p["x"] / 100.0, h * p["y"] / 100.0; canvas = np.zeros_like(img); items = []
    for i in range(n):
        m = lab == i
        if not m.any(): continue
        ys, xs = np.nonzero(m); cx, cy = xs.mean(), ys.mean(); dd = np.hypot(cx - cx0, cy - cy0) / np.hypot(w, h); lp = np.clip((pr * 1.6 - dd * 0.9 - r.random() * 0.2) / 0.7, 0, 1); items.append((lp, i, m, cx, cy))
    for lp, i, m, cx, cy in sorted(items, key=lambda o: -o[0]):
        ys, xs = np.nonzero(m); y0_, y1_, x0_, x1_ = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1; crop = _am(img[y0_:y1_, x0_:x1_], m[y0_:y1_, x0_:x1_].astype(np.float32))
        if lp <= 0: canvas[y0_:y1_, x0_:x1_] = _over(canvas[y0_:y1_, x0_:x1_], crop); continue
        if lp >= 1: continue
        ang = np.arctan2(cy - cy0, cx - cx0); M = cv2.getRotationMatrix2D((cx, cy), r.normal(0, 90) * lp, 1 - lp * 0.5); M[0, 2] += np.cos(ang) * lp * w * p["power"] / 100.0 * 0.5; M[1, 2] += np.sin(ang) * lp * h * p["power"] / 100.0 * 0.5 + lp * lp * h * p["fall"] / 100.0
        canvas = _paste(canvas, _am(crop, 1 - lp), x0_, y0_, M)
    return canvas
reg("shatter", WP, "Shatter", WIPE(35) + [I("pieces", "Pieces", 24, 4, 60), F("power", "Blast", 60, 0, 200), F("fall", "Fall", 40, 0, 200), F("x", "Hit X", 50, 0, 100), F("y", "Hit Y", 50, 0, 100), SEED()], fx_shatter, "The picture shatters like glass into pieces that fly away from the point of impact.", "glass break fragments")

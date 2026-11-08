"""Strokes & shadows, and Ink & paint & halftone."""
from .kit import *

SS = "Strokes & shadows"
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def _shadow_under(img, a, col, op):
    return blend(img, np.broadcast_to(bgr(col), a.shape + (3,)), np.clip(a, 0, 1), "behind", op)
def _alpha(img): return img[..., 3].astype(np.float32) * (1 / 255)


def fx_cartoon(img, p, ctx):
    f = img[..., :3]; sm_ = cv2.bilateralFilter(np.ascontiguousarray(f), 7, 40, 7) if not ctx.fast else cv2.GaussianBlur(f, (0, 0), 1.5); lv = int(p["levels"]); q = (np.floor(sm_.astype(np.float32) / 255 * lv) + 0.5) / lv; hsv = cv2.cvtColor(np.clip(q * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32); hsv[..., 1] = np.clip(hsv[..., 1] * (1 + p["boost"] / 100.0), 0, 255)
    base = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) / 255; e = edges(img, ctx, 1.0); line = sm(e, 0.12 + (1 - p["detail"] / 100.0) * 0.5, 0.2 + (1 - p["detail"] / 100.0) * 0.5)
    if p["width"] > 1: line = cv2.dilate(line, np.ones((int(S(ctx, p["width"]) // 2) * 2 + 1,) * 2, np.uint8))
    return pack(base * (1 - line[..., None]) + bgr(p["color"]) * line[..., None], like=img)
reg("cartoon", SS, "Cartoon outline", [I("levels", "Color steps", 5, 2, 12), F("boost", "Color boost", 25, 0, 100), F("detail", "Outline detail", 55, 0, 100), F("width", "Outline width", 1.5, 1, 8), C("color", "Outline color", "#101018")], fx_cartoon, "Flat colors with black outlines, like a comic.", "comic toon ink lines")


def fx_dropshadow(img, p, ctx):
    a = np.deg2rad(p["angle"]); d = p["distance"] * ctx.k; al = affine(_alpha(img)[..., None].repeat(4, 2).astype(np.float32), np.float32([[1, 0, np.cos(a) * d], [0, 1, np.sin(a) * d]]))[..., 0]
    if p["size"] > 0: al = cv2.dilate(al, np.ones((int(p["size"] * ctx.k) * 2 + 1,) * 2, np.uint8))
    al = glow_of(al, max(0.5, p["blur"] * ctx.k * 0.5)); return _shadow_under(img, al, p["color"], p["opacity"] / 100.0)
reg("dropshadow", SS, "Drop shadow", [F("distance", "Distance", 20, 0, 200), F("angle", "Angle", 60, -180, 180), F("blur", "Softness", 20, 0, 100), F("size", "Grow", 0, 0, 50), C("color", "Color", "#000000"), OPAC(70)], fx_dropshadow, "A shadow behind the picture (turn on Spill outside the media to see it past the edges).", "shadow offset")


def fx_longshadow(img, p, ctx):
    a = np.deg2rad(p["angle"]); n = int(max(1, p["length"] * ctx.k)); al = _alpha(img); h, w = al.shape; acc = al.copy(); step = 1; d = np.array([np.cos(a), np.sin(a)])
    covered = 1
    while covered < n:
        s = min(step, n - covered); M = np.float32([[1, 0, d[0] * s], [0, 1, d[1] * s]]); acc = np.maximum(acc, cv2.warpAffine(acc, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)); covered += s; step *= 2
    return _shadow_under(img, acc, p["color"], p["opacity"] / 100.0)
reg("longshadow", SS, "Long shadow", [F("length", "Length", 120, 1, 600), F("angle", "Angle", 45, -180, 180), C("color", "Color", "#111111"), OPAC(80)], fx_longshadow, "A long flat shadow stretching away (turn on Spill outside the media).", "flat design extrude")


def fx_gaussshadow(img, p, ctx):
    al = _alpha(img); al = cv2.dilate(al, np.ones((int(p["spread"] * ctx.k) * 2 + 1,) * 2, np.uint8)) if p["spread"] > 0 else al; al = np.clip(glow_of(al, p["blur"] * ctx.k * 0.5) * (1 + p["strength"] / 50.0), 0, 1); return _shadow_under(img, al, p["color"], p["opacity"] / 100.0)
reg("gaussshadow", SS, "Gaussian shadow", [F("blur", "Softness", 40, 1, 200), F("spread", "Spread", 4, 0, 60), F("strength", "Strength", 40, 0, 100), C("color", "Color", "#000000"), OPAC(80)], fx_gaussshadow, "A soft shadow all around the picture.", "soft glow around")


def fx_edgeline(img, p, ctx):
    e = sm(edges(img, ctx, p["width"]), p["threshold"] / 100.0 * 0.4, p["threshold"] / 100.0 * 0.4 + 0.15); return blend(img, np.broadcast_to(bgr(p["color"]), e.shape + (3,)), e * _alpha(img), "over", p["opacity"] / 100.0)
reg("edgeline", SS, "Edge line", [F("width", "Line width", 1.5, 0.5, 8), F("threshold", "Sensitivity", 40, 0, 100), C("color", "Color", "#ffffff"), OPAC(100)], fx_edgeline, "Draws lines along the edges it finds in the picture.", "outline contour")


def fx_emboss(img, p, ctx):
    a = np.deg2rad(p["angle"]); k = np.array([[-np.sin(a) - np.cos(a), -np.sin(a), np.cos(a) - np.sin(a)], [-np.cos(a), 1, np.cos(a)], [np.sin(a) - np.cos(a), np.sin(a), np.sin(a) + np.cos(a)]], np.float32)
    L = lum8(img); g = cv2.filter2D(L if ctx.k <= 1.5 else cv2.GaussianBlur(L, (0, 0), ctx.k * 0.5), -1, k * (p["depth"] / 30.0)); rel = np.clip(0.5 + g * 0.5, 0, 1); f = f3(img); m = p["mix"] / 100.0
    return pack(np.clip(f * (1 - m) + (rel[..., None] if not p["color"] else f * rel[..., None] * 2.0) * m, 0, 1), like=img)
reg("emboss", SS, "Emboss", [F("angle", "Light direction", 135, -180, 180), F("depth", "Depth", 40, 1, 150), F("mix", "Amount", 100, 0, 100), B("color", "Keep the colors", False)], fx_emboss, "The picture looks like it is pressed into metal or paper.", "relief 3d")


def fx_normalmap(img, p, ctx):
    L = lum8(img)
    if p["blur"] > 0: L = cv2.GaussianBlur(L, (0, 0), p["blur"] * ctx.k * 0.5)
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3) * p["strength"] / 4.0; gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3) * p["strength"] / 4.0 * (-1 if p["flip"] else 1); nz = np.ones_like(gx); n = np.stack([-gx, -gy, nz], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    rgb = n * 0.5 + 0.5; a = p["amount"] / 100.0; return pack(f3(img) * (1 - a) + rgb[..., ::-1] * a, like=img)
reg("normalmap", SS, "Normal map", [F("strength", "Strength", 12, 0.5, 60), F("blur", "Smooth", 1.0, 0, 20), B("flip", "Flip green", False), F("amount", "Amount", 100, 0, 100)], fx_normalmap, "Turns the picture into the blue-purple map that 3D programs use for surface detail.", "bump 3d texture")


def fx_neonedge(img, p, ctx):
    e = edges(img, ctx, 1.2); col = bgr(p["color"]); core = sm(e, 0.08, 0.35); gl = glow_of(core, p["glow"] * ctx.k * 0.3) * 2.2 + glow_of(core, p["glow"] * ctx.k) * 1.4; f = f3(img) * (1 - p["dim"] / 100.0)
    return pack(np.clip(f + (gl[..., None] * col) + core[..., None] * 0.7, 0, 1), like=img)
reg("neonedge", SS, "Neon edge", [C("color", "Color", "#ff2bd6"), F("glow", "Glow", 12, 1, 60), F("dim", "Darken picture", 70, 0, 100)], fx_neonedge, "The edges glow like neon tubes on a darkened picture.", "glow outline tron")


def fx_gradshadow(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); a = np.deg2rad(p["angle"]); d = (x * np.cos(a) + y * np.sin(a)); e = (abs(np.cos(a)) * w / h + abs(np.sin(a))) / 2; t = np.clip((d / e + 1) / 2, 0, 1); m = sm(t, 1 - p["size"] / 100.0, 1.0) ** p["curve"]
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m, "over", p["opacity"] / 100.0)
reg("gradshadow", SS, "Gradient shadow", [F("angle", "Direction", 90, -180, 180), F("size", "Size", 60, 5, 100), F("curve", "Curve", 1.0, 0.3, 4), C("color", "Color", "#000000"), OPAC(80)], fx_gradshadow, "A smooth dark gradient from one side, good for text under the picture.", "fade dark side")


def fx_vignettepro(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x / w - 0.5 - p["cx"] / 100.0) * 2; ny = (y / h - 0.5 - p["cy"] / 100.0) * 2; rd = p["round"] / 100.0
    if p["shape"] == "rect": d = np.maximum(np.abs(nx) ** (2 + 6 * (1 - rd)) , np.abs(ny) ** (2 + 6 * (1 - rd))) ** (1.0 / (2 + 6 * (1 - rd)))
    else: d = np.sqrt((nx * (1 if rd > 0.5 else 0.7 + 0.6 * rd)) ** 2 + ny ** 2) if False else np.sqrt((nx * (w / h) ** (-(1 - rd))) ** 2 * 1.0 + ny ** 2) * (1 + 0.0)
    s = p["size"] / 100.0; m = sm(d, s * 1.2 - p["feather"] / 100.0 * 1.0, s * 1.2 + 0.001 + 0.0) if False else sm(d, s - p["feather"] / 100.0 * s + 0.001, s + 0.5 * p["feather"] / 100.0 + 0.002)
    return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m * p["strength"] / 100.0, "over" if not p["multiply"] else "multiply", 1.0)
reg("vignettepro", SS, "Vignette Pro", [F("size", "Size", 85, 20, 150), F("feather", "Feather", 60, 0, 100), F("round", "Roundness", 100, 0, 100), CH("shape", "Shape", "ellipse", [("ellipse", "Ellipse"), ("rect", "Rounded square")]), F("cx", "Center X", 0, -50, 50), F("cy", "Center Y", 0, -50, 50), F("strength", "Strength", 75, 0, 100), C("color", "Color", "#000000"), B("multiply", "Multiply (darken only)", False)], fx_vignettepro, "A dark frame around the picture with full control of its shape, softness and center.", "darken corners")


# ------------------------------------------------------------------ ink & paint & halftone
IK = "Ink & paint"


def fx_crystallize(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); gx, gy = int(np.ceil(w / s)) + 2, int(np.ceil(h / s)) + 2; r = np.random.default_rng(int(p["seed"])); jx = (r.random((gy, gx)) - 0.5) * p["jitter"] / 100.0 * s * 1.6; jy = (r.random((gy, gx)) - 0.5) * p["jitter"] / 100.0 * s * 1.6
    sx = (np.arange(gx)[None, :] + 0.5) * s - s + jx; sy = (np.arange(gy)[:, None] + 0.5) * s - s + jy; x1 = np.arange(w, dtype=np.float32); y1 = np.arange(h, dtype=np.float32); ci = (x1 // s).astype(int) + 1; cj = (y1 // s).astype(int) + 1; lab = np.zeros((h, w), np.int32)
    for b0 in range(0, h, 32):          # the nearest of the 9 candidate sites, band by band (the same sums and comparisons as one pass over the whole picture, without the big temporaries)
        b1 = min(h, b0 + 32); yb = y1[b0:b1, None]; xb = x1[None, :]; best = np.full((b1 - b0, w), 1e18, np.float32); lb = np.zeros((b1 - b0, w), np.int32)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                ii = np.clip(ci + di, 0, gx - 1); jj = np.clip(cj[b0:b1] + dj, 0, gy - 1); d = (xb - sx[jj][:, ii]) ** 2 + (yb - sy[jj][:, ii]) ** 2; upd = d < best
                best = np.where(upd, d.astype(np.float32), best); lb = np.where(upd, jj[:, None] * gx + ii[None, :], lb)
        lab[b0:b1] = lb
    n = gx * gy; cnt = np.bincount(lab.ravel(), minlength=n).astype(np.float32); out = np.zeros_like(img, np.float32)
    for c in range(4): out[..., c] = (np.bincount(lab.ravel(), img[..., c].astype(np.float32).ravel(), minlength=n) / np.maximum(cnt, 1))[lab]
    if p["edge"] > 0:
        e = (lab != np.roll(lab, 1, 0)) | (lab != np.roll(lab, 1, 1)); out[e, :3] *= 1 - p["edge"] / 100.0 * 0.7
    return np.clip(out, 0, 255).astype(np.uint8)
reg("crystallize", IK, "Crystallize", [F("size", "Cell size", 22, 4, 120), F("jitter", "Irregularity", 80, 0, 100), F("edge", "Cell edges", 30, 0, 100), SEED()], fx_crystallize, "The picture becomes flat-colored crystal cells.", "voronoi mosaic stained glass")


def fx_halftone(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); a = np.deg2rad(p["angle"]); x, y = coords(h, w); u = x * np.cos(a) + y * np.sin(a); v = -x * np.sin(a) + y * np.cos(a); iu, iv = np.floor(u / s) + 0.5, np.floor(v / s) + 0.5
    cx = (iu * s) * np.cos(a) - (iv * s) * np.sin(a); cy = (iu * s) * np.sin(a) + (iv * s) * np.cos(a); samp = remap(img, np.clip(cx, 0, w - 1), np.clip(cy, 0, h - 1), cv2.BORDER_REPLICATE); f = f3(samp); L = lum(f)
    val = (1 - L) if not p["invert"] else L; r = np.sqrt(np.clip(val, 0, 1)) * s * 0.72 * (p["dot"] / 100.0 * 1.4); d = np.sqrt((u - iu * s) ** 2 + (v - iv * s) ** 2); m = np.clip((r - d) / max(0.8, 1.0 * ctx.k) + 0.5, 0, 1)
    ink = f if p["color_dots"] else np.broadcast_to(bgr(p["ink"]), f.shape); paper = bgr(p["paper"]); out = paper * (1 - m[..., None]) + ink * m[..., None]; return pack(out, like=img)
reg("halftone", IK, "Halftone / dots", [F("size", "Dot spacing", 9, 3, 60), F("angle", "Angle", 45, -90, 90), F("dot", "Dot size", 100, 30, 150), B("color_dots", "Colored dots", False), B("invert", "Light dots on dark", False), C("ink", "Ink", "#111111"), C("paper", "Paper", "#f5efe0")], fx_halftone, "The picture is made of dots, big in dark parts and small in light ones, like a newspaper.", "newspaper print dots comic")


def fx_ledgrid(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); gw, gh = max(1, int(w / s)), max(1, int(h / s)); small = cv2.resize(img, (gw, gh), interpolation=cv2.INTER_AREA); x, y = coords(h, w); lx = (x / s) % 1.0 - 0.5; ly = (y / s) % 1.0 - 0.5
    d = np.maximum(np.abs(lx), np.abs(ly)) if p["shape"] == "square" else np.sqrt(lx * lx + ly * ly); r = p["fill"] / 100.0 * 0.5; m = np.clip((r - d) * s / max(1.0, ctx.k) + 0.5, 0, 1); cell = small[np.clip((y / s).astype(int), 0, gh - 1), np.clip((x / s).astype(int), 0, gw - 1)]
    f = f3(cell) * (1 + p["bright"] / 100.0); out = f * m[..., None]
    if p["glow"] > 0: out = out + glow_of(out, s * 0.6) * (p["glow"] / 100.0)
    return pack(np.clip(out + bgr(p["gap"]) * (1 - m[..., None]), 0, 1), like=img)
reg("ledgrid", IK, "LED grid", [F("size", "LED size", 10, 3, 60), F("fill", "LED fill", 85, 20, 100), CH("shape", "Shape", "round", [("round", "Round"), ("square", "Square")]), F("bright", "Brightness", 20, -50, 100), F("glow", "Glow", 40, 0, 100), C("gap", "Between LEDs", "#050505")], fx_ledgrid, "The picture shown on a wall of little LED lights.", "led screen pixel matrix")


def fx_waveloq(img, p, ctx):
    h, w = img.shape[:2]; sp = S(ctx, p["spacing"]); n = max(2, int(h / sp)); L = cv2.resize(lum8(img), (w, n), interpolation=cv2.INTER_AREA); x, y = coords(h, w); idx = np.clip(np.round(y / sp - 0.5).astype(int), 0, n - 1); xi = np.clip(x.astype(int), 0, w - 1)
    amp = sp * 0.48 * p["wave"] / 100.0 * (1 - L if p["invert"] else L); cyl = (idx + 0.5) * sp + amp[idx, xi] * np.sin(x / S(ctx, p["freq"]) * 2 * np.pi + ctx.lt * p["speed"]); d = np.abs(y - cyl); m = np.clip((S(ctx, p["thick"]) * 0.5 - d) / max(0.7, ctx.k) + 0.5, 0, 1)
    col = f3(img) if p["color_lines"] else np.broadcast_to(bgr(p["ink"]), (h, w, 3)); return pack(bgr(p["paper"]) * (1 - m[..., None]) + col * m[..., None], like=img)
reg("waveloq", IK, "Waveloq", [F("spacing", "Line spacing", 10, 4, 40), F("wave", "Wave height", 80, 0, 100), F("freq", "Wave length", 10, 3, 60), F("thick", "Line thickness", 1.6, 0.5, 8), F("speed", "Speed", 1.5, 0, 10), B("invert", "Dark makes the waves", False), B("color_lines", "Colored lines", False), C("ink", "Ink", "#f3f3f3"), C("paper", "Paper", "#0a0a0f")], fx_waveloq, "The picture drawn with wavy lines: the brighter, the taller the waves (like a pulsar album cover).", "line art wave joy division pulsar")


def fx_bitdepth(img, p, ctx):
    h, w = img.shape[:2]; s = max(1, int(S(ctx, p["pixel"]))); small = cv2.resize(img, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA); f = f3(small); sh, sw = f.shape[:2]
    if p["dither"] > 0: b = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16.0 - 0.5; f = f + np.tile(b, (sh // 4 + 1, sw // 4 + 1))[:sh, :sw, None] * (p["dither"] / 100.0) * 0.5
    bits = p["bits"]
    if bits == "4": q = np.clip(np.round(f), 0, 1); br = (lum(f) > 0.55)[..., None] * 0.35; q = np.clip(q * 0.65 + br * (q > 0), 0, 1)
    elif bits == "8": lv = np.array([7, 7, 3], np.float32); q = np.round(np.clip(f, 0, 1) * lv) / lv
    else: lv = np.array([31, 63, 31], np.float32); q = np.round(np.clip(f, 0, 1) * lv[::-1]) / lv[::-1]
    out = pack(np.clip(q, 0, 1), small[..., 3]); return cv2.resize(out, (w, h), interpolation=cv2.INTER_NEAREST)
reg("bitdepth", IK, "4 / 8 / 16 bit", [CH("bits", "Colors", "8", [("4", "4-bit (16 colors)"), ("8", "8-bit (256 colors)"), ("16", "16-bit (65 536 colors)")]), F("pixel", "Pixel size", 3, 1, 30), F("dither", "Dither", 60, 0, 100)], fx_bitdepth, "Old video-game graphics: big pixels and few colors.", "retro game pixel art palette")


def fx_psykoblobs(img, p, ctx):
    h, w = img.shape[:2]; t = ctx.lt * p["speed"]; f = fbm(h, w, S(ctx, p["scale"]) * 3, int(p["seed"]), t * 0.5, 3); band = (f * p["bands"] + t * 0.3) % 1.0; col = hsv_bgr(band * 0.9 + p["hue"] / 360.0, 0.85, 1.0); m = sm(np.abs(np.sin(f * np.pi * p["bands"])), 0.0, 0.5) * 0 + (0.5 + 0.5 * np.sin(f * 9 + t))
    d = (f - 0.5) * 40 * ctx.k * p["warp"] / 100.0; base = displace(img, d, d * 0.7); return blend(base, col, np.clip(m, 0, 1), p["mode"], p["opacity"] / 100.0)
reg("psykoblobs", IK, "Psykoblobs", [F("scale", "Blob size", 40, 5, 200), I("bands", "Color bands", 3, 1, 12), F("hue", "Hue", 0, 0, 360), F("warp", "Warp the picture", 40, 0, 100), F("speed", "Speed", 0.8, 0, 8), MODE("over"), OPAC(55), SEED()], fx_psykoblobs, "Psychedelic color blobs that ooze over and bend the picture.", "psychedelic trippy lava")


def fx_psykostripes(img, p, ctx):
    h, w = img.shape[:2]; x, y = norm_coords(h, w); t = ctx.lt * p["speed"]; a = np.deg2rad(p["angle"]); wv = np.sin(x * 6 + t) * 0.15 * p["wave"] / 50.0 + np.sin(y * 9 - t * 1.3) * 0.1 * p["wave"] / 50.0
    u = (x * np.cos(a) + y * np.sin(a) + wv) * (60.0 / max(3.0, p["size"])); col = hsv_bgr(u * 0.5 + t * 0.2 + p["hue"] / 360.0, 0.9, 1.0); m = 0.5 + 0.5 * np.sin(u * np.pi * 2); return blend(img, col, m * 0.0 + 1.0, p["mode"], p["opacity"] / 100.0)
reg("psykostripes", IK, "Psykostripes", [F("size", "Stripe width", 25, 3, 150), F("angle", "Angle", 20, -180, 180), F("wave", "Waviness", 60, 0, 100), F("hue", "Hue", 0, 0, 360), F("speed", "Speed", 1.0, 0, 8), MODE("over"), OPAC(45)], fx_psykostripes, "Wavy rainbow stripes that flow over the picture.", "psychedelic rainbow lines")


def fx_money(img, p, ctx):
    h, w = img.shape[:2]; L = lum8(img); L = cv2.GaussianBlur(L, (0, 0), max(0.5, 0.8 * ctx.k)); x, y = coords(h, w); sp = S(ctx, p["spacing"]); a = np.deg2rad(p["angle"]); u = x * np.cos(a) + y * np.sin(a) + np.sin(x / S(ctx, 24) + y / S(ctx, 70)) * sp * 1.3 * p["curve"] / 100.0
    ph = (u / sp) % 1.0; tri = np.abs(ph - 0.5) * 2; ink = np.clip((0.5 * (1 - L) * 1.25 + 0.12 - tri * 0.5) * 6, 0, 1); rx, ry = x - w / 2, y - h / 2; ros = 0.5 + 0.5 * np.sin(np.sqrt(rx * rx + ry * ry) / (sp * 1.1) + np.arctan2(ry, rx) * 8); ink = np.clip(ink + (ros > 0.97) * 0.35 * p["rosette"] / 100.0, 0, 1)
    paper = bgr(p["paper"]) * (0.96 + 0.04 * noise(h, w, S(ctx, 20), 5)[..., None]); out = paper * (1 - ink[..., None]) + bgr(p["ink"]) * ink[..., None]; return pack(np.clip(out, 0, 1), like=img)
reg("money", IK, "Money filter", [F("spacing", "Line spacing", 5, 2, 20), F("angle", "Angle", 20, -90, 90), F("curve", "Curve", 60, 0, 100), F("rosette", "Rosette pattern", 40, 0, 100), C("ink", "Ink", "#1f5a3a"), C("paper", "Paper", "#e8efd6")], fx_money, "The picture engraved with fine curved lines, like the portrait on a banknote.", "banknote engraving currency")

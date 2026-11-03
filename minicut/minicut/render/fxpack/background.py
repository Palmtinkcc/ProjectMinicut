"""Background effects: patterns made from nothing. They replace the picture, go behind it or blend with it (Blend)."""
from .kit import *

BG = "Background"
def BGP(extra=(), speed=0.5): return list(extra) + [F("scale", "Scale", 50, 5, 200), SPEED(speed, 10), MODE("replace"), OPAC(100), SEED()]


def bgfx(gen):
    def fn(img, p, ctx):
        h, w = img.shape[:2]; pat, pa = gen(h, w, p, ctx, ctx.lt * p["speed"]); return blend(img, np.clip(pat, 0, 1).astype(np.float32), pa, p["mode"], p["opacity"] / 100.0)
    return fn
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def sc(ctx, p): return S(ctx, p["scale"]) * 2.0          # a feature of about this many pixels
def pal3(p, v): return ramp(v, [(0.0, p["c1"]), (0.5, p["c2"]), (1.0, p["c3"])])
CP3 = [C("c1", "Color 1", "#0b1026"), C("c2", "Color 2", "#7b2ff7"), C("c3", "Color 3", "#22d3ee")]


def g_cosweb(h, w, p, ctx, t):
    x, y = norm_coords(h, w); k = 130.0 / max(5.0, p["scale"])
    v = np.cos(x * k * 6 + t) + np.cos(y * k * 6 - t * 0.8) + np.cos((x + y) * k * 4 + t * 0.5) + np.cos(np.sqrt(x * x + y * y) * k * 8 - t); lines = 1 - sm(np.abs(v), 0.02, 0.02 + p["width"] / 100.0 * 0.5)
    return bgr(p["c1"]) * (1 - lines[..., None]) + bgr(p["c2"]) * lines[..., None], None
reg("cosweb", BG, "Cosine web", BGP([F("width", "Line width", 30, 2, 100), C("c1", "Background", "#070b1f"), C("c2", "Lines", "#4fd1ff")]), bgfx(g_cosweb), "A web of glowing lines made from overlapping waves.", "lines waves interference")


def g_blobs(h, w, p, ctx, t):
    x, y = coords(h, w); r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); fld = np.zeros((h, w), np.float32); col = np.zeros((h, w, 3), np.float32); cs = [bgr(p["c1"]), bgr(p["c2"]), bgr(p["c3"])]; R = sc(ctx, p)
    for i in range(n):
        ph = r.random(4) * 6.28; sp = r.uniform(0.4, 1.2); cx = w * (0.5 + 0.38 * np.sin(t * sp + ph[0])); cy = h * (0.5 + 0.38 * np.sin(t * sp * 0.8 + ph[1])); rad = R * r.uniform(0.7, 1.3)
        wgt = rad * rad / ((x - cx) ** 2 + (y - cy) ** 2 + 4.0); fld += wgt; col += wgt[..., None] * cs[i % 3]
    return col / np.maximum(fld[..., None], 1e-4), sm(fld, 0.7, 1.1)
reg("blobs", BG, "Color blobs", BGP([I("count", "Blobs", 7, 2, 20)] + CP3), bgfx(g_blobs), "Soft colored blobs that float around and melt into each other.", "metaballs lava lamp")


def g_wire(h, w, p, ctx, t):
    x, y = coords(h, w); s = sc(ctx, p) * 0.5; u = (x + y) / s + t * 0.3; v = (x - y) / s; d = np.minimum(np.abs(np.sin(np.pi * u)), np.abs(np.sin(np.pi * v))); wire = 1 - sm(d, 0.03, 0.03 + p["thick"] / 100.0 * 0.4)
    shade = 0.6 + 0.4 * np.cos(np.pi * u) * np.cos(np.pi * v); return bgr(p["c1"]) * (1 - wire[..., None]) + bgr(p["c2"]) * (wire * shade)[..., None], None
reg("fencewire", BG, "Fencing wire", BGP([F("thick", "Wire thickness", 25, 3, 100), C("c1", "Background", "#10131a"), C("c2", "Wire", "#c9d2e0")]), bgfx(g_wire), "A chain-link fence of crossing diagonal wires.", "chainlink mesh diamond")


_PAL = {"thermal": [(0, "#050018"), (0.25, "#4b00a0"), (0.5, "#e0004b"), (0.75, "#ffb000"), (1, "#ffffe0")], "viridis": [(0, "#440154"), (0.5, "#21908d"), (1, "#fde725")], "cool": [(0, "#03045e"), (0.5, "#00b4d8"), (1, "#caf0f8")]}
def g_heat(h, w, p, ctx, t): f = fbm(h, w, sc(ctx, p), int(p["seed"]), t); f = np.clip((f - 0.5) * (1 + p["contrast"] / 50.0) + 0.5, 0, 1); return ramp(f, _PAL[p["palette"]]), None
reg("heatmap", BG, "Heat map", BGP([CH("palette", "Colors", "thermal", [("thermal", "Thermal"), ("viridis", "Viridis"), ("cool", "Cool")]), F("contrast", "Contrast", 30, 0, 100)]), bgfx(g_heat), "A thermal-camera map of moving hot and cold areas.", "thermal infrared")


def g_iso(h, w, p, ctx, t):
    f = fbm(h, w, sc(ctx, p) * 2, int(p["seed"]), t, 3); v = np.abs(np.sin(f * np.pi * p["levels"])); line = 1 - sm(v, 0.0, p["width"] / 100.0 * 0.6 + 0.03); return bgr(p["c1"]) * (1 - line[..., None]) + bgr(p["c2"]) * line[..., None], None
reg("isoline", BG, "Isoline", BGP([I("levels", "Lines", 8, 2, 40), F("width", "Line width", 20, 1, 100), C("c1", "Background", "#0e1a14"), C("c2", "Lines", "#6dffb0")]), bgfx(g_iso), "Contour lines like a map of hills, slowly changing.", "contour topographic map")


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


def g_warptex(h, w, p, ctx, t):
    s = sc(ctx, p); x, y = coords(h, w); wx = (fbm(h, w, s * 3, int(p["seed"]), t, 3) - 0.5) * s * p["warp"] / 10.0; wy = (fbm(h, w, s * 3, int(p["seed"]) + 7, t, 3) - 0.5) * s * p["warp"] / 10.0
    u = (x + wx) / s; v = (y + wy) / s
    m = (np.floor(u) + np.floor(v)) % 2 if p["pattern"] == "checker" else (np.sin(u * np.pi * 2) > 0).astype(np.float32); m = np.asarray(m, np.float32)[..., None]; return bgr(p["c1"]) * (1 - m) + bgr(p["c2"]) * m, None
reg("warptex", BG, "Warp texture", BGP([F("warp", "Warp", 40, 0, 100), CH("pattern", "Pattern", "checker", [("checker", "Checker"), ("stripes", "Stripes")]), C("c1", "Color 1", "#1a1a2e"), C("c2", "Color 2", "#e94560")]), bgfx(g_warptex), "A checker or stripe pattern bent and swirled by noise.", "distorted checker")


def g_truchet(h, w, p, ctx, t):
    x, y = coords(h, w); s = sc(ctx, p) * 0.45; u = x / s + t * 0.2; v = y / s; i = np.floor(u).astype(int); j = np.floor(v).astype(int); fx = u - i; fy = v - j
    bit = ((i * 73856093) ^ (j * 19349663) ^ (int(p["seed"]) * 83492791)) & 1; d1 = np.where(bit == 0, np.hypot(fx, fy), np.hypot(1 - fx, fy)); d2 = np.where(bit == 0, np.hypot(1 - fx, 1 - fy), np.hypot(fx, 1 - fy))
    d = np.minimum(np.abs(d1 - 0.5), np.abs(d2 - 0.5)); line = 1 - sm(d, p["thick"] / 200.0 - 0.02, p["thick"] / 200.0 + 0.02)
    if p["fill"]: ins = ((np.minimum(d1, d2) < 0.5) ^ (((i + j) & 1) == 1)).astype(np.float32); m = np.clip(ins * (1 - 0.0) + 0 * line, 0, 1)
    else: m = line
    m = np.asarray(m, np.float32)[..., None]; return bgr(p["c1"]) * (1 - m) + bgr(p["c2"]) * m, None
reg("truchet", BG, "Truchet checker board", BGP([F("thick", "Line width", 20, 2, 100), B("fill", "Filled checker", False), C("c1", "Color 1", "#0d1321"), C("c2", "Color 2", "#f0a202")]), bgfx(g_truchet), "A maze of arcs made from tiles, or a checker board with curved edges.", "maze arcs tiles")


def g_warpnoise(h, w, p, ctx, t):
    s = sc(ctx, p) * 2; sd = int(p["seed"]); q = np.stack([fbm(h, w, s, sd, t * 0.5, 3), fbm(h, w, s, sd + 5, t * 0.5, 3)], -1)
    f = fbm(h, w, s * 0.7, sd + 11, t * 0.3 + float(q[..., 0].mean()) * 3, 3); f = f * 0.6 + q[..., 0] * 0.25 + q[..., 1] * 0.25 + (q[..., 0] - 0.5) * p["warp"] / 80.0; f = np.clip((f - 0.5) * 3.0 + 0.5, 0, 1); return pal3(p, f), None
reg("warpnoise", BG, "Warped noise field", BGP([F("warp", "Warp", 50, 0, 100)] + CP3), bgfx(g_warpnoise), "Smoke-like colored noise that is twisted by more noise.", "domain warp marble smoke")


def g_flix(h, w, p, ctx, t):
    s = sc(ctx, p); f = noise2(h, w, s * 8, s * 0.15 + 2, int(p["seed"]), t) * 0.6 + noise2(h, w, s * 3, s * 0.1 + 2, int(p["seed"]) + 3, t * 1.5) * 0.4; fl = 0.85 + 0.15 * np.sin(ctx.lt * 40) * p["flicker"] / 100.0
    return pal3(p, np.clip(f * fl, 0, 1)), None
reg("flix", BG, "Flix texture", BGP([F("flicker", "Flicker", 40, 0, 100)] + CP3), bgfx(g_flix), "Streaky, flickering light bars like a projected film leader or light leak.", "streaks light leak film")


def g_gradflow(h, w, p, ctx, t):
    x, y = norm_coords(h, w); a = np.deg2rad(p["angle"]); k = 3.0 / max(0.2, p["scale"] / 30.0); wp = (fbm(h, w, sc(ctx, p) * 4, int(p["seed"]), t * 0.4, 3) - 0.5) * p["warp"] / 20.0
    v = 0.5 + 0.5 * np.sin((x * np.cos(a) + y * np.sin(a)) * k + wp * 6 + t); return pal3(p, v), None
reg("gradflow", BG, "Gradient flow", BGP([F("angle", "Angle", 35, -180, 180), F("warp", "Flow", 60, 0, 100)] + CP3), bgfx(g_gradflow), "Smooth colors that flow and swirl like silk.", "mesh gradient silk")


def g_fractal(h, w, p, ctx, t):
    f = 0.5 if ctx.fast else 1.0; sw, sh = max(32, int(w * min(1.0, 320.0 / w) * f)), max(32, int(h * min(1.0, 320.0 / w) * f)); x = (np.linspace(-1, 1, sw, dtype=np.float32) * (sw / sh))[None, :]; y = np.linspace(-1, 1, sh, dtype=np.float32)[:, None]
    zoom = 1.6 / (1 + p["zoom"] / 30.0 * (1 + 0.0)); z = (x + 1j * y) * zoom; n = np.zeros(z.shape, np.float32); it = int(p["detail"])
    if p["kind"] == "julia": cc = 0.74 * np.exp(1j * (t * 0.4 + 0.8)) * (0.8 + 0.2 * p["shape"] / 100.0); zz = z.copy()
    else: cc = z - 0.5; zz = np.zeros_like(z)
    alive = np.ones(z.shape, bool)
    for i in range(it):
        zz = np.where(alive, zz * zz + cc, zz); esc = alive & (np.abs(zz) > 4); n[esc] = i + 1 - np.log2(np.log(np.abs(zz[esc]) + 1e-9) + 1e-9); alive &= ~esc
    v = np.where(alive, 0, 0.5 + 0.5 * np.sin(n * 0.25 + p["shift"] / 10.0)).astype(np.float32); out = pal3(p, v); out[alive] = bgr(p["c1"]) * 0.4
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR), None
reg("fractal", BG, "Fractal texture", [CH("kind", "Fractal", "julia", [("julia", "Julia (moves)"), ("mandel", "Mandelbrot")]), F("zoom", "Zoom", 20, 0, 200), I("detail", "Detail", 40, 10, 120), F("shape", "Shape", 50, 0, 100), F("shift", "Color shift", 0, 0, 62), SPEED(0.5, 10), MODE("replace"), OPAC(100), SEED(),
                        C("c1", "Color 1", "#05001f"), C("c2", "Color 2", "#ff3d81"), C("c3", "Color 3", "#ffe66d"), F("scale", "Scale", 50, 5, 200)], bgfx(g_fractal), "A glowing fractal; the Julia one keeps changing shape.", "mandelbrot julia")


# ------------------------------------------------------------------ procedural
PR = "Procedural"


def fx_blocknoise(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); s = S(ctx, p["block"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); n = r.random((gh, gw)).astype(np.float32)
    n = cv2.resize(n, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]; n = np.clip((n - 0.5) * (1 + p["contrast"] / 40.0) + 0.5, 0, 1)
    return blend(img, ramp(n, [(0, p["c1"]), (1, p["c2"])]), None, p["mode"], p["opacity"] / 100.0)
reg("blocknoise", PR, "Block noise", [F("block", "Block size", 24, 2, 200), F("rate", "Changes / s", 8, 0, 60), F("contrast", "Contrast", 20, 0, 100), C("c1", "Dark", "#000000"), C("c2", "Light", "#ffffff"), MODE("overlay"), OPAC(60), SEED()], fx_blocknoise, "Randomly colored squares laid over the picture, changing by themselves.", "squares mosaic noise")


def fx_contourstrips(img, p, ctx):
    f = f3(img); L = lum(f); n = int(p["bands"]); band = np.floor(L * n) / n; edge = np.abs(((L * n) % 1.0) - 0.5) * 2; line = sm(edge, 1 - p["line"] / 100.0 * 0.4, 1.0)[..., None]
    col = ramp(band, [(0, p["c1"]), (0.5, p["c2"]), (1, p["c3"])]); out = col * (1 - line * 0.5) + line * bgr(p["c1"]) * 0.2; a = p["amount"] / 100.0; return pack(np.clip(f * (1 - a) + out * a, 0, 1), like=img)
reg("contourstrips", PR, "Contour strips", [I("bands", "Strips", 10, 2, 40), F("line", "Edge lines", 50, 0, 100), F("amount", "Amount", 100, 0, 100), C("c1", "Dark", "#0b132b"), C("c2", "Middle", "#3a86ff"), C("c3", "Light", "#fefae0")], fx_contourstrips, "Turns the brightness of the picture into flat colored strips, like a topographic map.", "posterize bands")


def fx_lensflare(img, p, ctx):
    h, w = img.shape[:2]; cx, cy = w * p["x"] / 100.0, h * p["y"] / 100.0; col = bgr(p["color"]); xx, yy = coords(h, w); s = p["size"] / 100.0 * h; ang = ctx.lt * p["drift"] * 0.2
    cx += np.sin(ang) * w * 0.05 * (p["drift"] > 0); d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2); fl = np.exp(-d / (s * 0.18)) * 1.2 + np.exp(-(d / (s * 0.55)) ** 2) * 0.35; streak = np.exp(-np.abs(yy - cy) / (s * 0.02)) * np.exp(-np.abs(xx - cx) / (s * 1.6)) * p["streak"] / 100.0
    out = (fl + streak)[..., None] * col; ox, oy = w / 2 - cx, h / 2 - cy
    for k, (pos, rad, a) in enumerate(((0.5, 0.09, 0.35), (1.0, 0.16, 0.28), (1.5, 0.07, 0.4), (2.1, 0.22, 0.2), (-0.4, 0.12, 0.25))):
        gx, gy = cx + ox * pos * 2, cy + oy * pos * 2; dd = np.sqrt((xx - gx) ** 2 + (yy - gy) ** 2); ring = np.exp(-((dd - rad * h) / (h * 0.012)) ** 2) * 0.6 + sm(rad * h - dd, 0, rad * h) * 0.25
        out += ring[..., None] * (col * 0.6 + np.array([0.5 * (k % 2), 0.3, 0.5 * ((k + 1) % 2)], np.float32) * 0.5) * a * p["ghosts"] / 50.0
    return blend(img, np.clip(out * (p["amount"] / 100.0), 0, 2), None, "add", 1.0)
reg("lensflare", PR, "Lens flare", [F("x", "Light X", 25, -20, 120), F("y", "Light Y", 25, -20, 120), F("size", "Size", 45, 5, 120), F("amount", "Brightness", 90, 0, 200), F("streak", "Streak", 50, 0, 100), F("ghosts", "Reflections", 50, 0, 100), F("drift", "Drift", 0, 0, 10), C("color", "Color", "#ffd9a0")], fx_lensflare, "A bright light with a long streak and the colored rings that a camera lens makes.", "light sun flare anamorphic")


def fx_grunge(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["scale"]); f = fbm(h, w, s * 6, int(p["seed"]), 0, 5) * 0.6 + noise(h, w, max(2, s * 0.4), int(p["seed"]) + 3) * 0.4; f = np.clip((f - 0.5) * (2 + p["contrast"] / 20.0) + 0.5, 0, 1)
    r = np.random.default_rng(int(p["seed"])); sc_ = np.zeros((h, w), np.float32)
    for _ in range(int(p["scratches"])): x0, y0 = r.integers(0, w), r.integers(0, h); cv2.line(sc_, (x0, y0), (int(x0 + r.normal(0, w * 0.2)), int(y0 + r.normal(0, h * 0.2))), 1.0, 1, cv2.LINE_AA)
    m = np.clip(f + sc_ * 0.6, 0, 1); return blend(img, np.broadcast_to(bgr(p["color"]), (h, w, 3)), m * (p["amount"] / 100.0), p["mode"], 1.0)
reg("grunge", PR, "Grunge", [F("amount", "Amount", 60, 0, 100), F("scale", "Dirt size", 20, 2, 100), F("contrast", "Contrast", 30, 0, 100), I("scratches", "Scratches", 25, 0, 200), C("color", "Color", "#1b1208"), MODE("over"), SEED()], fx_grunge, "Dirt, stains and scratches laid over the picture.", "dirty texture worn")


def _bolt(r, a, b, n, jit):
    pts = [np.array(a, np.float32), np.array(b, np.float32)]
    for _ in range(n):
        new = [pts[0]]
        for i in range(len(pts) - 1):
            m = (pts[i] + pts[i + 1]) / 2; d = pts[i + 1] - pts[i]; nrm = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6); new += [m + nrm * r.normal(0, jit * np.linalg.norm(d) * 0.35), pts[i + 1]]
        pts = new
    return np.array(pts)


def fx_energybeam(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); a = (w * p["x1"] / 100.0, h * p["y1"] / 100.0); b = (w * p["x2"] / 100.0, h * p["y2"] / 100.0); core = np.zeros((h, w), np.float32); th = max(1, int(S(ctx, p["thick"])))
    for k in range(int(p["bolts"])):
        pts = _bolt(r, a, b, 6, p["wobble"] / 100.0 * (0.6 + 0.6 * k)); cv2.polylines(core, [pts.astype(np.int32)], False, 1.0 if k == 0 else 0.6, th if k == 0 else max(1, th // 2), cv2.LINE_AA)
    gl = glow_of(core, 3 * ctx.k * p["glow"] / 30.0) * 2.5 + glow_of(core, 10 * ctx.k * p["glow"] / 30.0) * 1.5; col = bgr(p["color"]); lay = np.clip(gl[..., None] * col + core[..., None] * 0.9, 0, 1.5)
    return blend(img, lay, None, "add", 1.0)
reg("energybeam", PR, "Energy beam", [F("x1", "Start X", 10, 0, 100), F("y1", "Start Y", 50, 0, 100), F("x2", "End X", 90, 0, 100), F("y2", "End Y", 50, 0, 100), I("bolts", "Bolts", 3, 1, 8), F("thick", "Thickness", 2, 1, 12), F("wobble", "Wobble", 45, 0, 100), F("glow", "Glow", 40, 1, 100), F("rate", "Changes / s", 18, 1, 60), C("color", "Color", "#6ec6ff"), SEED()], fx_energybeam, "Crackling electric beams between two points.", "lightning laser electric")


def fx_turbulence(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["scale"]) * 4; t = ctx.lt * p["speed"]; f = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for o in range(5): n = noise(h, w, s / 2 ** o, int(p["seed"]) + o * 13, t * (1 + o * 0.3)); f += amp * np.abs(n - 0.5) * 2; tot += amp; amp *= 0.55
    f = np.clip(1 - f / tot * 1.6, 0, 1) ** (1 + p["sharp"] / 30.0); y = coords(h, w)[1] / h; f = f * (1 - y * p["fade"] / 100.0 * 0.8)
    return blend(img, ramp(f, [(0, p["c1"]), (0.5, p["c2"]), (1, p["c3"])]), np.clip(f * 1.4, 0, 1), p["mode"], p["opacity"] / 100.0)
reg("turbulence", PR, "Turbulence", [F("scale", "Scale", 40, 5, 200), F("speed", "Speed", 0.6, 0, 10), F("sharp", "Sharpness", 40, 0, 100), F("fade", "Fade to the bottom", 30, 0, 100), C("c1", "Edge", "#3a0000"), C("c2", "Middle", "#ff6a00"), C("c3", "Core", "#fff3b0"), MODE("screen"), OPAC(100), SEED()], fx_turbulence, "Swirling fire-like turbulence.", "fire smoke plasma")

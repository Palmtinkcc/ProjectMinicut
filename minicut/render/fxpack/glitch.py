"""Glitch effects (they change by themselves with time; Seed and Changes per second control the randomness)."""
from .kit import *

G = "Glitch"
def GP(extra=()): return [F("amount", "Amount", 50, 0, 100), F("speed", "Changes / s", 12, 0, 60), SEED()] + list(extra)
def _r(p, ctx): return rng(ctx, p["seed"], p["speed"])
def _rows(r, h, amt, maxh=0.12):
    """Random horizontal bands covering the picture: list of (y0, y1)."""
    out = []; y = 0
    while y < h:
        hh = int(r.integers(max(1, h // 90), max(2, int(h * maxh)) + 1)); out.append((y, min(h, y + hh))); y += hh
    return out


def fx_glitchbox(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(1 + a * 16)):
        bw = int(w * r.uniform(0.05, 0.4)); bh = int(h * r.uniform(0.02, 0.22)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh))); k = int(r.integers(0, 4))
        reg_ = out[y0:y0 + bh, x0:x0 + bw]; src = img[y0:y0 + bh, :]; dx = int(r.normal(0, w * 0.1 * a))
        if k == 0: reg_[:] = np.roll(src, dx, axis=1)[:, x0:x0 + bw]
        elif k == 1: reg_[..., :3] = 255 - reg_[..., :3]
        elif k == 2: reg_[..., :3] = reg_[..., ::-1][..., 1:4][..., ::-1][..., :3] if False else reg_[..., [2, 0, 1]]
        else: reg_[..., 2] = np.roll(src, dx, axis=1)[:, x0:x0 + bw][..., 2]
    return out
reg("glitchbox", G, "Glitch box", GP(), fx_glitchbox, "Random rectangles slide sideways, flip their colors or swap channels.", "block blocks digital")


def fx_rgbglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); chans = [img[..., i].copy() for i in range(4)]
    for ci in (0, 2):
        sh = np.zeros(h, np.float32)
        for y0, y1 in _rows(r, h, a): sh[y0:y1] = r.normal(0, w * 0.04 * a) + (w * 0.006 * a if ci == 0 else -w * 0.006 * a)
        chans[ci] = shift_rows(chans[ci][..., None], sh)[..., 0] if False else cv2.remap(chans[ci], *( (coords(h, w)[0] - sh[:, None]) % w, coords(h, w)[1]), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return np.dstack(chans)
reg("rgbglitch", G, "RGB glitch", GP(), fx_rgbglitch, "The red and blue channels jump sideways in bands, like a broken video signal.", "channel split")


def fx_pixelglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(2 + a * 14)):
        bw = int(w * r.uniform(0.08, 0.5)); bh = int(h * r.uniform(0.05, 0.3)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh))); s = S(ctx, r.integers(4, 40))
        blk = out[y0:y0 + bh, x0:x0 + bw]
        if blk.size == 0: continue
        sm = cv2.resize(blk, (max(1, int(blk.shape[1] / s)), max(1, int(blk.shape[0] / s))), interpolation=cv2.INTER_AREA); out[y0:y0 + bh, x0:x0 + bw] = cv2.resize(sm, (blk.shape[1], blk.shape[0]), interpolation=cv2.INTER_NEAREST)
    return out
reg("pixelglitch", G, "Pixel glitch", GP(), fx_pixelglitch, "Parts of the picture turn into big blocky pixels for a moment.", "pixelate blocks")


def fx_offsetglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); sh = np.zeros(h, np.float32)
    for y0, y1 in _rows(r, h, a, 0.18):
        if r.random() < 0.15 + 0.6 * a: sh[y0:y1] = r.normal(0, w * 0.12 * a)
    return shift_rows(img, sh)
reg("offsetglitch", G, "Offset glitch", GP(), fx_offsetglitch, "Horizontal strips of the picture are shifted left and right.", "tear shift")


def fx_noiseglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy()
    for _ in range(int(1 + a * 10)):
        bw = int(w * r.uniform(0.1, 0.6)); bh = int(h * r.uniform(0.01, 0.12)); x0 = int(r.integers(0, max(1, w - bw))); y0 = int(r.integers(0, max(1, h - bh)))
        nz = r.integers(0, 256, (bh, bw, 1), dtype=np.uint8) if p["mono"] else r.integers(0, 256, (bh, bw, 3), dtype=np.uint8)
        out[y0:y0 + bh, x0:x0 + bw, :3] = (out[y0:y0 + bh, x0:x0 + bw, :3] * (1 - a * 0.6) + nz * (a * 0.6)).astype(np.uint8)
    return out
reg("noiseglitch", G, "Noise glitch", GP([B("mono", "Gray noise", False)]), fx_noiseglitch, "Bursts of digital noise cover strips of the picture.", "static burst")


def fx_randompattern(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); s = S(ctx, p["cell"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s))
    grid = (r.random((gh, gw)) < a * 0.6).astype(np.uint8)
    if p["pattern"] == "stripes": grid = np.repeat((r.random((1, gw)) < a * 0.6).astype(np.uint8), gh, 0)
    elif p["pattern"] == "rows": grid = np.repeat((r.random((gh, 1)) < a * 0.6).astype(np.uint8), gw, 1)
    m = cv2.resize(grid, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w].astype(bool); out = img.copy(); k = int(r.integers(0, 3))
    if k == 0: out[m, :3] = 255 - out[m, :3]
    elif k == 1: out[m, :3] = out[m][:, [2, 0, 1]]
    else: sh = int(r.normal(0, w * 0.06)); out[m] = np.roll(img, sh, axis=1)[m]
    return out
reg("randompattern", G, "Random pattern", GP([F("cell", "Cell size", 30, 4, 200), CH("pattern", "Pattern", "blocks", [("blocks", "Blocks"), ("stripes", "Columns"), ("rows", "Rows")])]), fx_randompattern, "A random pattern of cells is inverted, color-swapped or shifted.", "checker mask")


def fx_sliceglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); n = int(p["slices"]); vert = p["direction"] == "vertical"; src = np.ascontiguousarray(np.swapaxes(img, 0, 1)) if vert else img
    hh = src.shape[0]; cuts = np.sort(r.integers(0, hh, n)); sh = np.zeros(hh, np.float32); prev = 0
    for c in list(cuts) + [hh]:
        if r.random() < 0.3 + 0.6 * a: sh[prev:c] = r.normal(0, src.shape[1] * 0.1 * a)
        prev = c
    out = shift_rows(src, sh); return np.ascontiguousarray(np.swapaxes(out, 0, 1)) if vert else out
reg("sliceglitch", G, "Slice glitch", GP([I("slices", "Slices", 14, 2, 60), CH("direction", "Direction", "horizontal", [("horizontal", "Horizontal"), ("vertical", "Vertical")])]), fx_sliceglitch, "The picture is cut into thin slices that slide out of place.", "cut slices")


def fx_noiseline(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy(); col = (np.array(bgr(p["color"])) * 255).astype(np.uint8)
    for _ in range(int(2 + a * 60)):
        y = int(r.integers(0, h)); th = max(1, int(S(ctx, r.integers(1, 3)))); x0 = int(r.integers(0, w)); ln = int(w * r.uniform(0.05, 0.6) * (0.4 + a)); x1 = min(w, x0 + ln)
        nz = r.integers(0, 256, (th, x1 - x0, 1), dtype=np.uint8); out[y:y + th, x0:x1, :3] = (nz * 0.5 + col * 0.5).astype(np.uint8) if p["tinted"] else nz
    return out
reg("noiseline", G, "Noise line", GP([C("color", "Color", "#ffffff"), B("tinted", "Tint the lines", False)]), fx_noiseline, "Thin lines of noise flash across the picture.", "static lines")


def fx_scatterglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); s = S(ctx, p["cell"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); mx = a * w * 0.12
    dx = r.normal(0, mx, (gh, gw)).astype(np.float32); dy = r.normal(0, mx * 0.5, (gh, gw)).astype(np.float32); z = r.random((gh, gw)) > a * 0.9
    dx[z] = 0; dy[z] = 0; up = lambda g: cv2.resize(g, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]
    return displace(img, up(dx), up(dy), cv2.BORDER_REFLECT)
reg("scatterglitch", G, "Scatter glitch", GP([F("cell", "Piece size", 12, 2, 80)]), fx_scatterglitch, "Small pieces of the picture are thrown a little away from where they belong.", "scatter pieces")


def fx_deadgpu(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); t = int(S(ctx, p["tile"])); out = img.copy(); gh, gw = h // t + 1, w // t + 1
    for ty in range(gh):
        for tx in range(gw):
            if r.random() > a * 0.35: continue
            y0, x0 = ty * t, tx * t; tile = out[y0:y0 + t, x0:x0 + t]
            if tile.size == 0: continue
            k = int(r.integers(0, 5))
            if k == 0: sy, sx = int(r.integers(0, max(1, h - t))), int(r.integers(0, max(1, w - t))); tile[:] = img[sy:sy + tile.shape[0], sx:sx + tile.shape[1]]
            elif k == 1: tile[..., :3] = tile[..., [1, 2, 0]]
            elif k == 2: tile[..., :3] = r.integers(0, 256, 3, dtype=np.uint8)
            elif k == 3: tile[:, ::2, :3] = 255 - tile[:, ::2, :3]
            else: tile[:] = np.tile(tile[:2], (max(1, tile.shape[0] // 2), 1, 1))[:tile.shape[0]]
    if a > 0.3:
        for _ in range(int(a * 6)): x = int(r.integers(0, w)); ww = int(r.integers(1, max(2, w // 40))); out[:, x:x + ww] = out[:, x:x + 1]
    return out
reg("deadgpu", G, "Dead GPU glitch", GP([F("tile", "Tile size", 16, 4, 64)]), fx_deadgpu, "The look of a failing graphics card: tiles of wrong colors, repeated rows and stretched columns.", "artifact corrupted gpu")


def _sort(img, lo, hi, key, rev, vertical):
    src = np.ascontiguousarray(np.swapaxes(img, 0, 1)) if vertical else img; h, w = src.shape[:2]; f = f3(src); L = lum(f)
    if key == "hue": kv = cv2.cvtColor(np.ascontiguousarray(src[..., :3]), cv2.COLOR_BGR2HSV)[..., 0].astype(np.float32) / 180.0
    elif key == "red": kv = f[..., 2]
    else: kv = L
    sel = (L >= lo) & (L <= hi); start = np.ones((h, w), bool); start[:, 1:] = sel[:, 1:] != sel[:, :-1]; seg = np.cumsum(start.ravel()).astype(np.float64).reshape(h, w)
    k2 = np.where(sel, (1 - kv if rev else kv), np.arange(w, dtype=np.float32)[None, :] / w) * 0.999; order = np.argsort((seg + k2).ravel(), kind="stable")
    out = src.reshape(-1, 4)[order].reshape(h, w, 4); return np.ascontiguousarray(np.swapaxes(out, 0, 1)) if vertical else out


def fx_pixelsort(img, p, ctx):
    return _sort(img, p["low"] / 100.0, p["high"] / 100.0, p["key"], p["reverse"], p["direction"] == "vertical")
reg("pixelsort", G, "Pixel sort", [F("low", "Sort from (brightness)", 20, 0, 100), F("high", "Sort up to", 85, 0, 100), CH("key", "Sort by", "lum", [("lum", "Brightness"), ("hue", "Hue"), ("red", "Red")]),
                                    CH("direction", "Direction", "vertical", [("horizontal", "Horizontal"), ("vertical", "Vertical")]), B("reverse", "Reverse", False)], fx_pixelsort, "Sorts the pixels of each row or column by brightness, a classic glitch-art look.", "sort glitch art")


def fx_sortglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); out = img.copy(); vert = p["direction"] == "vertical"; n = w if vert else h
    for _ in range(int(1 + a * 8)):
        s0 = int(r.integers(0, n)); s1 = min(n, s0 + int(n * r.uniform(0.03, 0.25))); lo = r.uniform(0.0, 0.5); hi = min(1.0, lo + r.uniform(0.2, 0.7)); key = ("lum", "hue", "red")[int(r.integers(0, 3))]
        if vert: out[:, s0:s1] = _sort(out[:, s0:s1], lo, hi, key, bool(r.integers(0, 2)), True)
        else: out[s0:s1] = _sort(out[s0:s1], lo, hi, key, bool(r.integers(0, 2)), False)
    return out
reg("sortglitch", G, "Sort glitch", GP([CH("direction", "Direction", "horizontal", [("horizontal", "Horizontal"), ("vertical", "Vertical")])]), fx_sortglitch, "Random bands of the picture get sorted, each one differently, and change over time.", "pixel sort random")


def fx_hologram(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], 20); f = f3(img); col = bgr(p["color"]); g = lum(f)[..., None]; y = np.arange(h, dtype=np.float32)
    jit = (np.sin(y * 0.15 + ctx.lt * 9) * 0.5 + r.normal(0, 0.5, h)) * (p["jitter"] / 100.0) * w * 0.02; base = shift_rows(img, jit.astype(np.float32)); f = f3(base); g = lum(f)[..., None]
    holo = (f * 0.35 + g * col * 1.1 + col * 0.12); sp = S(ctx, p["lines"]); sl = 0.65 + 0.35 * np.sin((y[:, None] / sp + ctx.lt * p["roll"]) * 2 * np.pi)[..., None]
    e = edges(base, ctx, 1.5)[..., None] * col * 1.5 * (p["glow"] / 100.0); fl = 1 - (p["flicker"] / 100.0) * (0.5 + 0.5 * np.sin(ctx.lt * 47) * r.random())
    a = base[..., 3].astype(np.float32) / 255 * (p["opacity"] / 100.0) * fl * (0.7 + 0.3 * sl[..., 0]); return pack(np.clip(holo * sl + e, 0, 1), a)
reg("hologram", G, "Hologram", [C("color", "Color", "#34e0ff"), F("lines", "Line spacing", 4, 2, 20), F("roll", "Lines move", 3.0, -20, 20), F("jitter", "Jitter", 40, 0, 100), F("flicker", "Flicker", 35, 0, 100), F("glow", "Edge glow", 60, 0, 100), OPAC(80), SEED()], fx_hologram,
    "Turns the picture into a see-through blue-green hologram with moving lines and flicker.", "sci-fi projection")


def fx_bioscanner(img, p, ctx):
    h, w = img.shape[:2]; f = f3(img); L = lum(f); col = bgr(p["color"]); pos = (ctx.lt * p["speed"] * 0.25) % 1.0; y = coords(h, w)[1] / h; d = np.abs(y - pos); beam = np.clip(1 - d / (p["width"] / 100.0 * 0.3 + 1e-3), 0, 1) ** 2
    gs = S(ctx, p["grid"]); x_, y_ = coords(h, w); grid = ((np.abs((x_ % gs) - gs / 2) < 0.6) | (np.abs((y_ % gs) - gs / 2) < 0.6)).astype(np.float32); lift = (L * gs * 0.6)
    wire = np.clip(1 - np.abs(((y_ - lift * beam * 0.0) % gs) - gs / 2) / 1.2, 0, 1) * np.clip(L * 1.5, 0, 1)
    body = f * (0.55 + 0.45 * (1 - beam[..., None])) * 0.8; inside = beam[..., None]; out = body * (1 - inside) + (np.stack([wire] * 3, -1) * col * 1.3 + grid[..., None] * col * 0.4 + f * 0.25) * inside
    out = out + col * 0.06 + (beam[..., None] > 0.9) * col * 0.4; return pack(np.clip(out, 0, 1), like=img)
reg("bioscanner", G, "Bioscanner 3D", [C("color", "Color", "#3dff9a"), F("speed", "Scan speed", 2.0, 0, 10), F("width", "Beam width", 45, 5, 100), F("grid", "Grid size", 10, 4, 60)], fx_bioscanner,
    "A scanning beam sweeps down the picture and shows it as a glowing wireframe grid.", "scan wireframe medical")

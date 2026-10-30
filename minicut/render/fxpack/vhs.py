"""VHS and old-screen effects."""
from .kit import *

V = "VHS"
def _under(img, layer, op):
    """Put `layer` (BGRA) behind the picture."""
    return blend(img, f3(layer), layer[..., 3].astype(np.float32) / 255.0, "behind", op)


def fx_vhsdist(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; y = np.arange(h, dtype=np.float32); r = rng(ctx, p["seed"], 25); t = ctx.lt * p["speed"]
    wob = np.sin(y * 0.045 + t * 3) * 0.5 + np.sin(y * 0.13 - t * 5) * 0.3; low = np.clip((y / h - 0.65) / 0.35, 0, 1) ** 2; pos = (t * 0.17) % 1.0; band = np.clip(1 - np.abs(y / h - pos) / (p["band"] / 100.0 * 0.12 + 1e-3), 0, 1)
    sh = (wob * w * 0.004 + (low * 18 + band * 40) * r.normal(0.6, 0.5, h)) * a * ctx.k; out = shift_rows(img, sh.astype(np.float32))
    bl = out.copy(); bl[..., 2] = cv2.GaussianBlur(out[..., 2], (0, 0), max(0.5, 3 * ctx.k * a), borderType=cv2.BORDER_REPLICATE); return bl
reg("vhsdist", V, "VHS distortion", [F("amount", "Amount", 50, 0, 100), F("band", "Tracking band", 40, 0, 100), SPEED(1.0), SEED()], fx_vhsdist, "Wobbling lines, a moving tracking band and color bleeding, like a worn tape.", "vsh tape wobble")


def fx_vhsnoise(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 30); out = img.copy(); f = f3(out)
    nz = r.random((h, w, 1)).astype(np.float32); f = f + (nz - 0.5) * 0.35 * a; y = np.arange(h)
    for _ in range(int(1 + a * 4)):
        y0 = int(r.integers(0, h)); hh = int(r.integers(2, max(3, h // 14))); f[y0:y0 + hh] = f[y0:y0 + hh] * 0.4 + r.random((min(hh, h - y0), w, 1)).astype(np.float32) * 0.6 * (0.5 + a)
    return pack(np.clip(f, 0, 1), like=img)
reg("vhsnoise", V, "VHS noise", [F("amount", "Amount", 50, 0, 100), SEED()], fx_vhsnoise, "Grainy video noise with a few horizontal static bands.", "vsh static")


def fx_signal(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 8); cyc = (ctx.lt * p["rate"]) % 1.0; burst = float(np.clip((0.35 - cyc) / 0.35, 0, 1)) * a
    if burst <= 0.01: return img
    off = int(r.normal(0, h * 0.2 * burst)); out = np.roll(img, off, axis=0); sh = r.normal(0, w * 0.05 * burst, h).astype(np.float32); out = shift_rows(out, sh)
    st = r.random((h, w, 1)).astype(np.float32); f = f3(out) * (1 - burst * 0.5) + st * burst * 0.5; g = lum(f)[..., None]; f = f * (1 - burst * 0.6) + g * burst * 0.6; return pack(np.clip(f, 0, 1), like=out)
reg("signal", V, "Signal", [F("amount", "Amount", 70, 0, 100), F("rate", "Signal loss per second", 0.7, 0.1, 5), SEED()], fx_signal, "The picture keeps losing its signal: it rolls, tears and fills with static.", "signal loss roll")


def fx_retro(img, p, ctx):
    f = f3(img); g = lum(f)[..., None]; f = f * (1 - p["fade"] / 200.0) + g * (p["fade"] / 300.0); f = f * (1 - p["lift"] / 100.0 * 0.3) + p["lift"] / 100.0 * 0.12
    wm = p["warmth"] / 100.0; f[..., 2] *= 1 + wm * 0.15; f[..., 0] *= 1 - wm * 0.15; o = pack(np.clip(f, 0, 1), like=img)
    if p["soft"] > 0: o = blend(o, f3(blur_bgra(o, p["soft"] * ctx.k * 0.4)), None, "replace", 0.7)
    if p["bleed"] > 0:
        o2 = o.copy(); o2[..., 2] = np.roll(cv2.GaussianBlur(o[..., 2], (0, 0), max(0.5, p["bleed"] * ctx.k * 0.4)), int(p["bleed"] * ctx.k * 0.5), axis=1); o = o2
    return o
reg("retro", V, "Retro", [F("fade", "Faded colors", 45, 0, 100), F("lift", "Lifted blacks", 40, 0, 100), F("warmth", "Warmth", 30, -100, 100), F("soft", "Softness", 25, 0, 100), F("bleed", "Color bleed", 30, 0, 100)], fx_retro, "Soft, faded, warm colors like an old tape or a faded photo.", "vintage old tape")


def fx_scanline(img, p, ctx):
    h, w = img.shape[:2]; y = np.arange(h, dtype=np.float32); sp = S(ctx, p["spacing"]); ph = (y / sp + ctx.lt * p["roll"]) % 1.0; dark = np.clip(1 - np.abs(ph - 0.5) * 2 * (1 / max(0.05, p["thickness"] / 100.0)) + 0.0, 0, 1)
    m = 1 - (1 - dark) * (p["intensity"] / 100.0); f = f3(img) * m[:, None, None] + bgr(p["color"]) * ((1 - m)[:, None, None] * 0); return pack(np.clip(f, 0, 1), like=img)
reg("scanline", V, "Scanline", [F("spacing", "Spacing", 4, 2, 40), F("thickness", "Line thickness", 50, 5, 100), F("intensity", "Darkness", 55, 0, 100), F("roll", "Lines move", 0.0, -20, 20), C("color", "Color", "#000000")], fx_scanline, "Dark horizontal lines over the picture, like a TV screen.", "lines tv crt")


def fx_tapenoise(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 24); out = img.copy()
    for _ in range(int(2 + a * 40)):
        y = int(r.integers(0, h)); x0 = int(r.integers(0, w)); ln = int(w * r.uniform(0.02, 0.25)); x1 = min(w, x0 + ln); th = max(1, int(S(ctx, r.integers(1, 3)))); v = int(r.integers(140, 256))
        out[y:y + th, x0:x1, :3] = (out[y:y + th, x0:x1, :3] * 0.3 + v * 0.7).astype(np.uint8)
    dark = (r.random((h, w)) < a * 0.01); out[dark, :3] = 0; return out
reg("tapenoise", V, "Tape noise", [F("amount", "Amount", 50, 0, 100), SEED()], fx_tapenoise, "Short white dashes and dark specks, like dropouts on magnetic tape.", "dropout dashes")


def fx_crt(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x / w - 0.5) * 2; ny = (y / h - 0.5) * 2; c = p["curve"] / 100.0 * 0.25; r2 = nx * nx + ny * ny; f = 1 + c * r2
    out = remap_clear(img, (nx * f / 1.0 / (1 + c * 0.5) * 0.5 + 0.5) * w, (ny * f / (1 + c * 0.5) * 0.5 + 0.5) * h)
    fl = f3(out); sp = S(ctx, 3); s = 1 - (p["lines"] / 100.0) * (0.5 + 0.5 * np.cos(2 * np.pi * y / sp)) * 0.6; fl = fl * s[..., None]
    tri = np.stack([(np.cos(2 * np.pi * (x / (sp)) + k * 2.094) * 0.5 + 0.5) for k in (0, 1, 2)], -1); fl = fl * (1 - p["mask"] / 100.0 * 0.5 + p["mask"] / 100.0 * 0.5 * tri * 1.6)
    if p["bloom"] > 0: fl = fl + glow_of(np.clip(fl - 0.6, 0, 1), 6 * ctx.k) * (p["bloom"] / 100.0) * 1.5
    v = 1 - np.clip(r2 - 0.5, 0, 1) * (p["vignette"] / 100.0) * 1.2; fl = fl * v[..., None] * (1 - 0.04 * (0.5 + 0.5 * np.sin(ctx.lt * 60)) * p["flicker"] / 100.0)
    return pack(np.clip(fl, 0, 1), out[..., 3])
reg("crt", V, "CRT emulator", [F("curve", "Screen curve", 50, 0, 100), F("lines", "Scanlines", 45, 0, 100), F("mask", "Color dots", 40, 0, 100), F("bloom", "Bloom", 35, 0, 100), F("vignette", "Dark corners", 50, 0, 100), F("flicker", "Flicker", 20, 0, 100)], fx_crt,
    "An old curved TV tube: curved glass, scanlines, red-green-blue dots, glow and dark corners.", "old tv monitor tube")


def fx_ghost(img, p, ctx):
    out = img; n = int(p["count"]); ang = np.deg2rad(p["angle"]); step = p["distance"] * ctx.k
    for i in range(n, 0, -1):
        M = np.float32([[1, 0, np.cos(ang) * step * i], [0, 1, np.sin(ang) * step * i]]); lay = affine(img, M)
        if p["tint"] != "#ffffff": t = bgr(p["tint"]); lay[..., :3] = np.clip(lay[..., :3].astype(np.float32) * t[None, None] + 0, 0, 255).astype(np.uint8)
        out = _under(out, lay, (p["fade"] / 100.0) ** i * 1.0 + 0.0)
    return out
reg("ghost", V, "Ghost", [I("count", "Copies", 3, 1, 8), F("distance", "Distance", 14, 1, 120), F("angle", "Angle", 0, -180, 180), F("fade", "Visibility", 70, 5, 100), C("tint", "Tint", "#ffffff")], fx_ghost, "Faint copies of the picture trailing behind it (turn on Spill outside the media to see them past the edges).", "echo trail double")


def fx_vcr(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 15); sh = np.zeros(h, np.float32); y0 = int(h * (0.78 + 0.18 * r.random())); sh[y0:] = r.normal(0, w * 0.05 * a, h - y0)
    for _ in range(int(a * 4)): yy = int(r.integers(0, h)); sh[yy:yy + int(r.integers(2, 10))] += r.normal(0, w * 0.1 * a)
    out = shift_rows(img, sh); out[..., 0] = np.roll(out[..., 0], int(-3 * ctx.k * a), axis=1); out[..., 2] = np.roll(out[..., 2], int(3 * ctx.k * a), axis=1)
    nz = (r.random((h - y0, w, 1)) * 255 * a * 0.7).astype(np.uint8); out[y0:, :, :3] = np.clip(out[y0:, :, :3].astype(np.int16) * 0.5 + nz, 0, 255).astype(np.uint8); return out
reg("vcr", V, "VCR glitch", [F("amount", "Amount", 55, 0, 100), SEED()], fx_vcr, "A tracking error at the bottom of the picture with torn lines and colored edges.", "tracking error tape")


def fx_noiseover(img, p, ctx):
    h, w = img.shape[:2]; r = rng(ctx, p["seed"], p["rate"]); s = S(ctx, p["size"]); gh, gw = int(np.ceil(h / s)), int(np.ceil(w / s)); n = r.random((gh, gw, 1 if p["mono"] else 3)).astype(np.float32)
    n = cv2.resize(n, (int(gw * s) + 1, int(gh * s) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]; n = n[..., None] if n.ndim == 2 else n; n = np.broadcast_to(n, (h, w, 3))
    return blend(img, np.ascontiguousarray(n), None, p["mode"], p["amount"] / 100.0)
reg("noiseover", V, "Noise overlay", [F("amount", "Amount", 30, 0, 100), F("size", "Grain size", 2, 1, 20), F("rate", "Changes / s", 24, 0, 60), B("mono", "Gray noise", True), MODE("overlay"), SEED()], fx_noiseover, "A layer of animated noise on top, like analog video grain.", "grain static")


def fx_filmdot(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 12); cv = np.zeros((h, w), np.float32); dk = np.zeros((h, w), np.float32)
    for _ in range(int(5 + a * 120)):
        x, y = int(r.integers(0, w)), int(r.integers(0, h)); rad = max(1, int(S(ctx, r.uniform(0.6, 2.6) * p["size"]))); cv2.circle(cv if r.random() < 0.7 else dk, (x, y), rad, 1.0, -1, cv2.LINE_AA)
    for _ in range(int(a * 4 * p["scratch"] / 50.0)):
        x = int(r.integers(0, w)); cv2.line(cv, (x, int(r.integers(0, h // 2))), (x + int(r.normal(0, 3)), int(r.integers(h // 2, h))), 0.7, 1, cv2.LINE_AA)
    for _ in range(int(a * 6)):
        pts = np.cumsum(r.normal(0, 3, (6, 2)), axis=0) + [r.integers(0, w), r.integers(0, h)]; cv2.polylines(dk, [pts.astype(np.int32)], False, 0.8, 1, cv2.LINE_AA)
    f = f3(img); f = f * (1 - dk[..., None] * 0.85) + cv[..., None] * 0.9; return pack(np.clip(f, 0, 1), like=img)
reg("filmdot", V, "Film dot", [F("amount", "Amount", 50, 0, 100), F("size", "Dot size", 1.0, 0.3, 4), F("scratch", "Scratches", 50, 0, 100), SEED()], fx_filmdot, "Dust specks, hairs and scratches that flash on old film.", "dust scratches film")

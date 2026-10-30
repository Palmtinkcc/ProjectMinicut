"""Color and Opacity effects."""
from .kit import *

C1 = "Color"; C2 = "Opacity"


def fx_bgcopy(img, p, ctx):
    h, w = img.shape[:2]; bg = affine(img, xform(h, w, sc=p["scale"] / 100.0)); bg = blur_bgra(bg, p["blur"] * ctx.k * 0.6)
    return blend(img, f3(bg) * (1 - p["dim"] / 100.0), bg[..., 3].astype(np.float32) / 255.0, "behind", 1.0)
reg("bgcopy", C1, "Copy background", [F("scale", "Size of the copy", 130, 100, 400), F("blur", "Blur", 35, 0, 100), F("dim", "Darken", 35, 0, 100)], fx_bgcopy,
    "Fills the empty space around the media (turn on Spill outside the media) with a bigger, blurred copy of itself.", "blur background fill")


def fx_solid(img, p, ctx):
    return blend(img, np.broadcast_to(bgr(p["color"]), img.shape[:2] + (3,)), None, p["mode"], p["opacity"] / 100.0)
reg("solid", C1, "Solid color", [C("color", "Color", "#ff3b6b"), MODE("behind"), OPAC(100)], fx_solid, "Covers the picture, or the empty space behind it, with one color.", "fill flat")


def fx_rays(img, p, ctx):
    h, w = img.shape[:2]; f = f3(img); g = lum(f); t = p["threshold"] / 100.0; m = (np.clip((g - t) / max(1e-3, 1 - t), 0, 1)[..., None] * f * (img[..., 3:4] * (1 / 255))).astype(np.float32)
    n = 8 if ctx.fast else 16; acc = np.zeros_like(m); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; ln = p["length"] / 100.0
    for i in range(n):
        s = 1 + ln * i / n; M = xform(h, w, sc=s, cx=cx, cy=cy); acc += cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT) * (0.93 ** i)
    rays = acc / n * (p["amount"] / 25.0) * bgr(p["color"]); return blend(img, np.clip(rays, 0, 1), None, "screen", 1.0)
reg("rays", C1, "Rays", [F("amount", "Amount", 60, 0, 100), F("length", "Length", 60, 5, 150), F("threshold", "Bright from", 55, 0, 95), F("cx", "Center X", 50, 0, 100), F("cy", "Center Y", 30, 0, 100), C("color", "Color", "#fff1c9")], fx_rays,
    "Light rays that stream out from the bright parts of the picture.", "god rays light shafts")


def fx_hueshift(img, p, ctx):
    hu = p["hue"] + p["cycle"] * ctx.lt
    if abs(hu % 360) < 0.01 and p["saturation"] == 0: return img
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + hu / 2.0) % 180; hsv[..., 1] = np.clip(hsv[..., 1] * (1 + p["saturation"] / 100.0), 0, 255)
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR); return out
reg("hueshift", C1, "Hue shift", [F("hue", "Hue shift", 90, -180, 180), F("cycle", "Cycle (deg / s)", 0, -360, 360), F("saturation", "Saturation", 0, -100, 100)], fx_hueshift, "Turns all the colors around the color wheel; it can also keep turning by itself.", "rainbow rotate cycle")


def fx_gradmap(img, p, ctx):
    f = f3(img); g = lum(f); m = ramp(g, [(0.0, p["shadow"]), (0.5, p["mid"]), (1.0, p["high"])]); a = p["amount"] / 100.0
    return pack(f * (1 - a) + m * a, like=img)
reg("gradmap", C1, "Gradient map", [C("shadow", "Shadows", "#1b0b3a"), C("mid", "Midtones", "#d6336c"), C("high", "Highlights", "#ffe66d"), F("amount", "Amount", 100, 0, 100)], fx_gradmap, "Paints dark, middle and bright parts with three colors you choose.", "duotone tritone")


def fx_darkglow(img, p, ctx):
    f = f3(img); d = np.clip((1 - lum(f) - p["threshold"] / 100.0) / max(1e-3, 1 - p["threshold"] / 100.0), 0, 1); g = np.clip(glow_of(d, p["radius"] * ctx.k) * 3, 0, 1)[..., None] * (p["amount"] / 100.0)
    col = bgr(p["color"]); return pack(f * (1 - g) + col * g, like=img)
reg("darkglow", C1, "Dark glow", [F("amount", "Amount", 70, 0, 100), F("radius", "Radius", 25, 1, 100), F("threshold", "Dark from", 55, 0, 95), C("color", "Color", "#000000")], fx_darkglow, "A glow of darkness around the dark parts (the opposite of Glow).", "shadow halo")


def fx_exposure(img, p, ctx):
    f = f3(img); f = np.power(np.clip(f * (2.0 ** p["exposure"]) + p["offset"] / 100.0, 0, 8), 1.0 / max(0.05, p["gamma"])); return pack(np.clip(f, 0, 1), like=img)
reg("exposure", C1, "Exposure / Gamma", [F("exposure", "Exposure (stops)", 0, -4, 4), F("gamma", "Gamma", 1.0, 0.2, 3), F("offset", "Offset", 0, -50, 50)], fx_exposure, "Exposure makes everything brighter or darker; gamma changes the middle tones only.", "brightness levels")


_BANDS = [("red", "Red", 0.0), ("yellow", "Yellow", 1 / 6), ("green", "Green", 2 / 6), ("cyan", "Cyan", 3 / 6), ("blue", "Blue", 4 / 6), ("magenta", "Magenta", 5 / 6)]


def fx_hslmix(img, p, ctx):
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV_FULL).astype(np.float32); hh = hsv[..., 0] / 255.0
    dh = np.zeros_like(hh); ds = np.zeros_like(hh); dv = np.zeros_like(hh)
    for k, _, c in _BANDS:
        d = np.abs(((hh - c + 0.5) % 1.0) - 0.5); wgt = np.clip(1 - d * 6, 0, 1)
        dh += wgt * p[k + "_h"] / 360.0; ds += wgt * p[k + "_s"] / 100.0; dv += wgt * p[k + "_l"] / 100.0
    hsv[..., 0] = ((hh + dh) % 1.0) * 255.0; hsv[..., 1] = np.clip(hsv[..., 1] * (1 + ds), 0, 255); hsv[..., 2] = np.clip(hsv[..., 2] * (1 + dv), 0, 255)
    out = img.copy(); out[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR_FULL); return out
reg("hslmix", C1, "HSL Mixer", sum([[F(k + "_h", n + " hue", 0, -60, 60), F(k + "_s", n + " saturation", 0, -100, 100), F(k + "_l", n + " lightness", 0, -100, 100)] for k, n, _ in _BANDS], []), fx_hslmix,
    "Change the hue, saturation and lightness of each color family separately (all the reds, all the blues ...).", "color mixer hsl")


# ------------------------------------------------------------------ opacity
def _alpha_mul(img, m):
    out = img.copy(); out[..., 3] = np.clip(img[..., 3].astype(np.float32) * m, 0, 255).astype(np.uint8); return out


def fx_blockdissolve(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); b = S(ctx, p["block"]); gh, gw = int(np.ceil(h / b)), int(np.ceil(w / b))
    r = np.random.default_rng(int(p["seed"]) + 11).random((gh, gw)).astype(np.float32); r = cv2.resize(r, (int(gw * b) + 1, int(gh * b) + 1), interpolation=cv2.INTER_NEAREST)[:h, :w]
    return _alpha_mul(img, (r >= pr).astype(np.float32))
reg("blockdissolve", C2, "Block dissolve", WIPE(50) + [F("block", "Block size", 28, 4, 200), SEED()], fx_blockdissolve, "Random squares of the picture disappear. Progress 100 = everything gone.", "pixel dissolve squares")


def fx_dissolve(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = fbm(h, w, S(ctx, p["scale"]), int(p["seed"]), 0, 4); soft = p["soft"] / 100.0 * 0.3 + 0.002; t = pr * (1 + soft) - soft * 0.5
    m = np.clip((n - t) / soft, 0, 1); out = _alpha_mul(img, m)
    if p["edge"] > 0:
        e = np.clip(1 - np.abs(n - t) / (p["edge"] / 100.0 * 0.12 + 1e-3), 0, 1) * (pr > 0) * (img[..., 3] * (1 / 255)); out = blend(out, np.broadcast_to(bgr(p["color"]), (h, w, 3)), e * (m > 0.01), "add", 1.0)
    return out
reg("dissolve", C2, "Dissolve", WIPE(50) + [F("scale", "Noise size", 60, 6, 400), F("soft", "Softness", 30, 0, 100), F("edge", "Glowing edge", 40, 0, 100), C("color", "Edge color", "#ffb347"), SEED()], fx_dissolve, "The picture dissolves like smoke or paper, with a glowing edge.", "burn noise fade")


def fx_feather(img, p, ctx):
    h, w = img.shape[:2]; size = p["size"] / 100.0; x, y = coords(h, w)
    if p["shape"] == "ellipse": r = np.sqrt(((x / w - 0.5) * 2) ** 2 + ((y / h - 0.5) * 2) ** 2); m = np.clip((1 - r) / max(size * 2, 1e-3), 0, 1)
    else: d = np.minimum(np.minimum(x, w - 1 - x) / w, np.minimum(y, h - 1 - y) / h) * 2; m = np.clip(d / max(size, 1e-3), 0, 1)
    return _alpha_mul(img, m ** p["curve"])
reg("feather", C2, "Feather", [F("size", "Size", 25, 0, 100), CH("shape", "Shape", "rect", [("rect", "Rectangle"), ("ellipse", "Ellipse")]), F("curve", "Curve", 1.0, 0.3, 4)], fx_feather, "Fades the edges of the media into see-through.", "soft edge fade vignette alpha")

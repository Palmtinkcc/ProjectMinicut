"""Distortion & warp, Lens, Water & glass, and more blurs."""
from .kit import *
from ..effects import _premul, _unpremul, blur_bgra

DW = "Distortion & warp"; LN = "Lens"; WG = "Water & glass"; BL = "Blur"
def sm(x, a, b): t = np.clip((x - a) / max(b - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)
def CEN(): return [F("cx", "Center X", 50, -50, 150), F("cy", "Center Y", 50, -50, 150)]
def polar(h, w, p):
    """px, py (picture pixels relative to the center), r, angle, and the center."""
    x, y = coords(h, w); cx, cy = w * p.get("cx", 50) / 100.0, h * p.get("cy", 50) / 100.0; dx, dy = x - cx, y - cy; return dx, dy, np.sqrt(dx * dx + dy * dy), np.arctan2(dy, dx), cx, cy
def sample_polar(img, cx, cy, rs, ang, border=cv2.BORDER_REFLECT): return remap(img, cx + rs * np.cos(ang), cy + rs * np.sin(ang), border)


# ------------------------------------------------------------------ distortion & warp
def fx_mirror(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w * p["cx"] / 100.0, h * p["cy"] / 100.0; m = p["mode"]
    if m == "kaleido":
        dx, dy, r, a, _, _ = polar(h, w, p); seg = 2 * np.pi / int(p["segments"]); a2 = np.abs(((a + np.deg2rad(p["rot"] + ctx.lt * p["spin"])) % seg) - seg / 2); return sample_polar(img, cx, cy, r, a2 - np.deg2rad(p["rot"]) , cv2.BORDER_REFLECT)
    sx, sy = x.copy(), y.copy()
    if m in ("lr", "quad"): sx = np.where(x > cx, 2 * cx - x, x)
    if m in ("rl",): sx = np.where(x < cx, 2 * cx - x, x)
    if m in ("tb", "quad"): sy = np.where(y > cy, 2 * cy - y, y)
    if m in ("bt",): sy = np.where(y < cy, 2 * cy - y, y)
    return remap(img, sx, sy, cv2.BORDER_REFLECT)
reg("mirror", DW, "Mirror", [CH("mode", "Mirror", "lr", [("lr", "Left onto right"), ("rl", "Right onto left"), ("tb", "Top onto bottom"), ("bt", "Bottom onto top"), ("quad", "All four"), ("kaleido", "Kaleidoscope")]), I("segments", "Segments (kaleidoscope)", 6, 2, 24), F("rot", "Rotate", 0, -180, 180), F("spin", "Spin (deg / s)", 0, -180, 180)] + CEN(), fx_mirror, "Mirrors one half of the picture onto the other, or makes a kaleidoscope.", "symmetry kaleidoscope flip")


def fx_polar(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w)
    if p["dir"] == "to_polar": dx, dy, r, a, cx, cy = polar(h, w, p); return remap(img, ((a / (2 * np.pi) + 0.5) * w) % w, np.clip(r / (np.hypot(w, h) / 2) * h, 0, h - 1), cv2.BORDER_REFLECT)
    cx, cy = w * p["cx"] / 100.0, h * p["cy"] / 100.0; ang = x / w * 2 * np.pi - np.pi; rs = y / h * (np.hypot(w, h) / 2); return remap(img, cx + rs * np.cos(ang) * 0 + (cx + rs * np.cos(ang)) * 0 + (cx + rs * np.cos(ang)) - cx * 0, cy + rs * np.sin(ang), cv2.BORDER_REFLECT)
reg("polar", DW, "Polar coordinates", [CH("dir", "Convert", "to_polar", [("to_polar", "Picture to circle"), ("from_polar", "Circle to picture")])] + CEN(), fx_polar, "Wraps the picture into a circle (a tiny planet), or unwraps it.", "tiny planet circle")


def fx_dispmap(img, p, ctx):
    h, w = img.shape[:2]
    if p["source"] == "self": m = lum8(img)
    else: m = fbm(h, w, S(ctx, p["scale"]), int(p["seed"]), ctx.lt * p["speed"], 3)
    if p["smooth"] > 0: m = cv2.GaussianBlur(m, (0, 0), p["smooth"] * ctx.k * 0.5)
    a = np.deg2rad(p["angle"]); d = (m - 0.5) * p["strength"] * ctx.k; return displace(img, np.cos(a) * d, np.sin(a) * d)
reg("dispmap", DW, "Displacement map", [CH("source", "Map made from", "noise", [("noise", "Noise"), ("self", "The picture's brightness")]), F("strength", "Strength", 40, -300, 300), F("angle", "Direction", 45, -180, 180), F("scale", "Noise size", 40, 3, 300), F("smooth", "Smooth the map", 2, 0, 40), F("speed", "Speed", 0.5, 0, 8), SEED()], fx_dispmap, "Pushes the pixels around following a map: noise, or the brightness of the picture itself.", "displace")


def fx_squeeze(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; k = p["amount"] / 100.0
    if p["axis"] == "x": f = 1 + k * (1 - np.abs(y - cy) / cy) ** 2; return remap(img, cx + (x - cx) * f, y, cv2.BORDER_CONSTANT)
    f = 1 + k * (1 - np.abs(x - cx) / cx) ** 2; return remap(img, x, cy + (y - cy) * f, cv2.BORDER_CONSTANT)
reg("squeeze", DW, "Squeeze", [F("amount", "Amount", 60, -90, 300), CH("axis", "Squeeze the", "x", [("x", "Width (waist)"), ("y", "Height")])], fx_squeeze, "Squeezes the middle of the picture like a waist or an hourglass.", "pinch waist narrow")


def fx_pinch(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["radius"] / 100.0 * 0.5 * 2; t = np.clip(r / R, 0, 1); k = p["amount"] / 100.0
    rs = np.where(r < R, r * (1 - k * (1 - t * t)), r); return sample_polar(img, cx, cy, rs, a)
reg("pinch", DW, "Pinch / Bulge", [F("amount", "Bulge (+) / Pinch (-)", 60, -95, 95), F("radius", "Size", 60, 5, 200)] + CEN(), fx_pinch, "Swells a round part of the picture like a bubble, or sucks it in.", "bulge magnify")


def fx_tiles(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); x, y = coords(h, w)
    if p["shape"] == "square":
        cx = (np.floor(x / s) + 0.5) * s; cy = (np.floor(y / s) + 0.5) * s; d = np.maximum(np.abs(x - cx), np.abs(y - cy)) * 2 / s
    else:
        q = (np.sqrt(3) / 3 * x - 1.0 / 3 * y) / (s * 0.58); r_ = (2.0 / 3 * y) / (s * 0.58); X = q; Z = r_; Y = -X - Z; rx, ry, rz = np.round(X), np.round(Y), np.round(Z); dxx, dyy, dzz = np.abs(rx - X), np.abs(ry - Y), np.abs(rz - Z)
        fx_ = (dxx > dyy) & (dxx > dzz); fy_ = (~fx_) & (dyy > dzz); rx = np.where(fx_, -ry - rz, rx); rz = np.where(~fx_ & ~fy_, -rx - ry, rz); cx = s * 0.58 * np.sqrt(3) * (rx + rz / 2); cy = s * 0.58 * 1.5 * rz; d = np.hypot(x - cx, y - cy) / (s * 0.58 * 0.9)
    out = remap(img, np.clip(cx, 0, w - 1), np.clip(cy, 0, h - 1), cv2.BORDER_REPLICATE); gap = np.clip((1 - d - (1 - p["gap"] / 100.0 * 0.0)) * 0, 0, 1)
    if p["gap"] > 0: edge = sm(d, 1 - p["gap"] / 100.0 * 0.4, 1.0); out[..., :3] = (out[..., :3] * (1 - edge[..., None] * 0.8)).astype(np.uint8)
    return out
reg("tiles", DW, "Tiles", [CH("shape", "Tile", "hex", [("square", "Square"), ("hex", "Hexagon")]), F("size", "Tile size", 22, 4, 150), F("gap", "Grout", 40, 0, 100)], fx_tiles, "The picture is cut into square or hexagon tiles, each one a single color.", "mosaic hexagon honeycomb")


def fx_wavewarp(img, p, ctx):
    t = ctx.lt * p["speed"] * 2 * np.pi; h, w = img.shape[:2]; x, y = coords(h, w); L = S(ctx, p["length"]); return remap(img, x + np.sin(y / L * 2 * np.pi + t) * p["ax"] * ctx.k, y + np.sin(x / L * 2 * np.pi * 0.9 - t) * p["ay"] * ctx.k)
reg("wavewarp", DW, "Wave warp", [F("ax", "Sideways", 12, 0, 200), F("ay", "Up and down", 0, 0, 200), F("length", "Wave length", 80, 5, 600), F("speed", "Speed", 0.5, -5, 5)], fx_wavewarp, "The picture ripples like a flag in the wind.", "wobble flag sine")


def fx_turbdisp(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; dx = (fbm(h, w, s, int(p["seed"]), t, int(p["detail"])) - 0.5) * 2; dy = (fbm(h, w, s, int(p["seed"]) + 9, t, int(p["detail"])) - 0.5) * 2; return displace(img, dx * p["amount"] * ctx.k, dy * p["amount"] * ctx.k)
reg("turbdisp", DW, "Turbulent displace", [F("amount", "Amount", 40, 0, 300), F("size", "Size", 120, 5, 600), I("detail", "Detail", 3, 1, 6), F("speed", "Evolution speed", 0.6, 0, 8), SEED()], fx_turbdisp, "Pushes the pixels with swirling noise, like heat haze.", "turbulence heat haze")


def fx_ripple(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); L = S(ctx, p["length"]); t = ctx.lt * p["speed"]; env = np.exp(-r / (min(w, h) * p["reach"] / 100.0 * 2)) if p["reach"] < 200 else 1.0
    return sample_polar(img, cx, cy, np.maximum(0, r + np.sin(r / L * 2 * np.pi - t * 2 * np.pi) * p["amount"] * ctx.k * env), a)
reg("ripple", DW, "Circular ripple", [F("amount", "Height", 12, 0, 100), F("length", "Wave length", 40, 5, 300), F("speed", "Speed", 1.0, -5, 5), F("reach", "Reach", 100, 10, 200)] + CEN(), fx_ripple, "Rings spread from a point like a stone dropped in water.", "concentric shockwave")


def fx_fractalwarp(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; px, py = x.copy(), y.copy(); amp = p["amount"] * ctx.k; sd = int(p["seed"])
    for i in range(int(p["iterations"])):
        nx = remap(fbm(h, w, s / (1 + i * 0.7), sd + i * 3, t + i, 3), px, py, cv2.BORDER_REFLECT) if False else fbm(h, w, s / (1 + i * 0.7), sd + i * 3, t + i, 3); ny = fbm(h, w, s / (1 + i * 0.7), sd + i * 3 + 1, t + i, 3)
        px = px + (nx - 0.5) * amp / (1 + i * 0.5); py = py + (ny - 0.5) * amp / (1 + i * 0.5)
    return remap(img, px, py)
reg("fractalwarp", DW, "Fractal warp", [F("amount", "Amount", 80, 0, 400), F("size", "Size", 160, 10, 600), I("iterations", "Layers", 3, 1, 6), F("speed", "Speed", 0.4, 0, 6), SEED()], fx_fractalwarp, "Layers of noise bend the picture again and again into organic shapes.", "organic liquid marble")


# ------------------------------------------------------------------ lens
def fx_blackhole(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["size"] / 100.0 * 0.5; k = p["strength"] / 100.0; sw = k * (R / np.maximum(r, 1.0)) * 1.2 * np.sign(p["spin"] if p["spin"] else 1)
    rs = r * (1 + k * 1.2 * (R / np.maximum(r, R * 0.2)) ** 2); out = sample_polar(img, cx, cy, rs, a + sw * (1 + 0.5 * np.sin(ctx.lt * abs(p["spin"]) * 0.2)), cv2.BORDER_REFLECT)
    f = f3(out); hole = sm(r, R * 0.28, R * 0.32); ring_r = R * 0.5; ring = np.exp(-((r - ring_r) / (R * 0.07)) ** 2) * (0.6 + 0.4 * np.sin(a * 2 + ctx.lt * 3)) * p["glow"] / 100.0; col = ramp(ring, [(0, "#000000"), (0.4, "#ff5a00"), (1, "#fff0c0")])
    return pack(np.clip(f * hole[..., None] + col * (1 - 0.0) * (ring[..., None] > 0.02) * np.clip(ring[..., None] * 1.5, 0, 1), 0, 1), like=out)
reg("blackhole", LN, "Black hole", [F("size", "Size", 55, 10, 150), F("strength", "Pull", 60, 0, 150), F("spin", "Swirl", 40, -100, 100), F("glow", "Glowing ring", 80, 0, 100)] + CEN(), fx_blackhole, "Space bends around a black hole with a glowing ring.", "gravity lens space interstellar")


def fx_chroma(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; k = p["amount"] / 1000.0; out = img.copy(); a = np.deg2rad(p["angle"]); ox, oy = np.cos(a) * p["shift"] * ctx.k, np.sin(a) * p["shift"] * ctx.k
    for c, s_ in ((2, 1 - k), (0, 1 + k)):
        sx = cx + (x - cx) * s_ + (ox if c == 2 else -ox); sy = cy + (y - cy) * s_ + (oy if c == 2 else -oy); out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out
reg("chromab", LN, "Chromatic aberration", [F("amount", "Edge split", 25, 0, 100), F("shift", "Straight shift", 0, 0, 40), F("angle", "Shift direction", 0, -180, 180)], fx_chroma, "Red and blue fringes at the edges, like a cheap lens.", "color fringe rgb split lens")


def fx_dirskew(img, p, ctx):
    h, w = img.shape[:2]; a = np.deg2rad(p["angle"]); k = np.tan(np.deg2rad(p["amount"])); x, y = coords(h, w); ux, uy = np.cos(a), np.sin(a); d = (x - w / 2) * (-uy) + (y - h / 2) * ux; return remap(img, x - ux * k * d, y - uy * k * d, cv2.BORDER_CONSTANT)
reg("dirskew", LN, "Directional skew", [F("amount", "Skew", 15, -60, 60), F("angle", "Direction", 0, -180, 180)], fx_dirskew, "Slants the picture in any direction.", "shear slant")


def _barrel(img, p, ctx, k, scale=1.0, cx=0.5, cy=0.5, chan=None):
    h, w = img.shape[:2]; x, y = coords(h, w); nx = (x - w * cx) / (h / 2); ny = (y - h * cy) / (h / 2); r2 = nx * nx + ny * ny; f = (1 + k * r2 + p.get("k2", 0) / 100.0 * r2 * r2) * scale
    return (nx * f * (h / 2) + w * cx), (ny * f * (h / 2) + h * cy)


def fx_fisheye(img, p, ctx):
    sx, sy = _barrel(img, p, ctx, p["amount"] / 100.0 * 1.2, 1.0 / (1 + p["amount"] / 100.0 * 0.6) if p["fit"] else 1.0); return remap_clear(img, sx, sy)
reg("fisheye", LN, "Fisheye", [F("amount", "Amount", 60, 0, 150), B("fit", "Zoom in to fill", True)], fx_fisheye, "A wide-angle bubble look.", "wide angle barrel gopro")


def fx_antifisheye(img, p, ctx):
    sx, sy = _barrel(img, p, ctx, -p["amount"] / 100.0 * 0.6, 1.0 / max(0.4, 1 - p["amount"] / 100.0 * 0.3) if p["fit"] else 1.0); return remap_clear(img, sx, sy)
reg("antifisheye", LN, "Anti fisheye", [F("amount", "Amount", 30, 0, 150), B("fit", "Zoom in to fill", True)], fx_antifisheye, "The opposite of fisheye: straightens a bent picture (or pinches the corners).", "pincushion undistort")


def fx_distortrgb(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; out = img.copy(); x, y = coords(h, w)
    for c, off in ((2, 0), (1, 5), (0, 11)):
        if p["kind"] == "wave": dx = np.sin(y / s * 2 * np.pi + t * 2 + off) * p["amount"] * ctx.k; dy = np.sin(x / s * 2 * np.pi + t * 2 + off * 0.7) * p["amount"] * ctx.k * 0.5
        else: dx = (fbm(h, w, s, int(p["seed"]) + off, t, 3) - 0.5) * 2 * p["amount"] * ctx.k; dy = (fbm(h, w, s, int(p["seed"]) + off + 1, t, 3) - 0.5) * 2 * p["amount"] * ctx.k
        out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), (x + dx).astype(np.float32), (y + dy).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out
reg("distortrgb", LN, "Distort RGB", [F("amount", "Amount", 14, 0, 100), F("size", "Size", 90, 10, 500), CH("kind", "Pattern", "noise", [("noise", "Noise"), ("wave", "Waves")]), F("speed", "Speed", 0.6, 0, 8), SEED()], fx_distortrgb, "The red, green and blue parts of the picture are bent differently, so colors split apart.", "rgb wobble separation")


def fx_fbmfade(img, p, ctx):
    h, w = img.shape[:2]; per = max(0.2, p["period"]); env = 0.5 - 0.5 * np.cos(2 * np.pi * ctx.lt / per); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; dx = (fbm(h, w, s, int(p["seed"]), t, 4) - 0.5) * 2; dy = (fbm(h, w, s, int(p["seed"]) + 4, t, 4) - 0.5) * 2
    return displace(img, dx * p["amount"] * ctx.k * env, dy * p["amount"] * ctx.k * env)
reg("fbmfade", LN, "FBM time displace fade", [F("amount", "Amount", 70, 0, 300), F("size", "Size", 130, 10, 600), F("period", "Fade in and out every (s)", 4, 0.5, 30), F("speed", "Speed", 0.5, 0, 6), SEED()], fx_fbmfade, "A swirling distortion that fades in and out over time.", "noise warp pulse")


def fx_fluidcurl(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); psi = fbm(h, w, s, int(p["seed"]), ctx.lt * p["speed"], 4); gy, gx = np.gradient(psi); n = max(1e-4, float(np.abs(gx).max() + np.abs(gy).max()) / 2); vx, vy = gy / n, -gx / n
    return displace(img, vx * p["amount"] * ctx.k, vy * p["amount"] * ctx.k)
reg("fluidcurl", LN, "Fluid distortion (curl noise)", [F("amount", "Amount", 22, 0, 300), F("size", "Size", 150, 10, 600), F("speed", "Speed", 0.5, 0, 6), SEED()], fx_fluidcurl, "Flows like a liquid, using swirls that never bunch up or stretch the picture too much.", "smoke flow")


def fx_lensdist(img, p, ctx):
    sx, sy = _barrel(img, {"k2": p["k2"]}, ctx, p["k1"] / 100.0, 1.0 / (1 + max(0, p["k1"]) / 100.0 * 0.5) if p["fit"] else 1.0); return remap_clear(img, sx, sy)
reg("lensdist", LN, "Lens distortion", [F("k1", "Barrel (+) / Pincushion (-)", 40, -100, 100), F("k2", "Edge correction", 0, -100, 100), B("fit", "Zoom in to fill", True)], fx_lensdist, "Bends the picture like a wide or telephoto lens.", "barrel pincushion")


def fx_lensdistrgb(img, p, ctx):
    out = img.copy(); h, w = img.shape[:2]
    for c, d in ((2, -1), (1, 0), (0, 1)):
        sx, sy = _barrel(img, {"k2": p["k2"]}, ctx, (p["k1"] + d * p["split"]) / 100.0, 1.0 / (1 + max(0, p["k1"]) / 100.0 * 0.5) if p["fit"] else 1.0); out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return out
reg("lensdistrgb", LN, "Lens distortion RGB", [F("k1", "Barrel (+) / Pincushion (-)", 30, -100, 100), F("split", "Color split", 6, 0, 30), F("k2", "Edge correction", 0, -100, 100), B("fit", "Zoom in to fill", True)], fx_lensdistrgb, "Lens distortion where each color is bent a little differently.", "barrel chromatic")


def fx_fluidwarp(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; px, py = x.copy(), y.copy(); fa = (fbm(h, w, s, int(p["seed"]), t, 3) - 0.5) * 2 * np.pi * 2; vx, vy = np.cos(fa), np.sin(fa); st = p["amount"] * ctx.k / int(p["steps"])
    for _ in range(int(p["steps"])): ux = cv2.remap(vx.astype(np.float32), px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); uy = cv2.remap(vy.astype(np.float32), px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); px = px + ux * st; py = py + uy * st
    return remap(img, px, py)
reg("fluidwarp", LN, "Fluid warp", [F("amount", "Amount", 45, 0, 600), F("size", "Size", 160, 20, 600), I("steps", "Smoothness", 6, 2, 14), F("speed", "Speed", 0.4, 0, 6), SEED()], fx_fluidwarp, "The picture is dragged along swirling currents, like paint stirred in water.", "marbling stir")


def fx_lensorb(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["size"] / 100.0 * 0.5; ins = r < R; t = np.clip(r / R, 0, 1); z = np.sqrt(np.clip(1 - t * t, 0, 1)); rs = np.where(ins, r * (1 - p["power"] / 100.0 * z * 0.9) * 0.55 + 0 * r, r)
    out = sample_polar(img, cx, cy, np.where(ins, R * t ** (1 + p["power"] / 100.0) * 0.8, r), a); f = f3(out); rim = np.clip(1 - np.abs(r - R) / (S(ctx, 2.5)), 0, 1); spec = np.exp(-(((dx + R * 0.35) ** 2 + (dy + R * 0.4) ** 2) / (R * 0.18) ** 2)) * ins * p["shine"] / 100.0
    shade = 1 - (t ** 3) * 0.35 * ins; res = f * np.where(ins, shade, 1)[..., None] + (rim + spec)[..., None] * 0.7; return pack(np.clip(res, 0, 1), like=out)
reg("lensorb", LN, "Lens orb", [F("size", "Size", 55, 10, 140), F("power", "Magnify", 60, 0, 100), F("shine", "Shine", 60, 0, 100)] + CEN(), fx_lensorb, "A glass ball over the picture that magnifies what is behind it.", "magnifier sphere bubble")


def fx_sway(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; f = (1 - y / h) if p["anchor"] == "bottom" else (y / h); return remap(img, x - np.sin(t + y / h * p["bend"]) * (f ** 1.5) * p["amount"] * ctx.k, y, cv2.BORDER_REFLECT)
reg("sway", LN, "Sway", [F("amount", "Amount", 40, 0, 300), F("speed", "Sways / s", 0.5, 0.05, 5), F("bend", "Bend", 2.0, 0, 8), CH("anchor", "Fixed at the", "bottom", [("bottom", "Bottom"), ("top", "Top")])], fx_sway, "The picture sways like a tree or a curtain, still at one edge.", "wind curtain")


def fx_swirl(img, p, ctx):
    h, w = img.shape[:2]; dx, dy, r, a, cx, cy = polar(h, w, p); R = min(w, h) * p["radius"] / 100.0; t = np.clip(1 - r / R, 0, 1); ang = np.deg2rad(p["angle"] + ctx.lt * p["spin"]) * t * t * (3 - 2 * t); return sample_polar(img, cx, cy, r, a - ang)
reg("swirl", LN, "Swirl", [F("angle", "Twist", 160, -720, 720), F("radius", "Size", 60, 5, 200), F("spin", "Spin (deg / s)", 0, -360, 360)] + CEN(), fx_swirl, "Twists a round area of the picture like a whirlpool.", "whirl vortex")


def fx_twist(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); cx, cy = w / 2, h / 2; ang = np.deg2rad(p["angle"]) * ((y - cy) / h) + np.deg2rad(ctx.lt * p["spin"]); dx, dy = x - cx, y - cy; return remap(img, cx + dx * np.cos(ang) + dy * np.sin(ang) * 0 + 0 * dy, cy + dy + dx * np.sin(ang) * 0 + (dx * 0), cv2.BORDER_REFLECT) if False else remap(img, cx + dx * np.cos(ang) - dy * 0 + (x * 0), y + dx * np.sin(ang) * p["lift"] / 100.0 * 0.5, cv2.BORDER_REFLECT)
reg("twist", LN, "Twist", [F("angle", "Twist", 160, -720, 720), F("lift", "Lift", 40, 0, 100), F("spin", "Spin (deg / s)", 0, -360, 360)], fx_twist, "The picture is twisted like a ribbon around its vertical axis.", "ribbon screw")


def fx_bend(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); k = p["amount"] / 100.0 * h * 0.6; u = (x - w / 2) / (w / 2); return remap(img, x, y + (u * u - 0.5) * k * (1 if p["dir"] == "arch" else -1), cv2.BORDER_CONSTANT)
reg("bend", LN, "Warp (bend)", [F("amount", "Bend", 50, -100, 100), CH("dir", "Bends", "arch", [("arch", "Like an arch"), ("bowl", "Like a bowl")])], fx_bend, "Bends the whole picture into an arch or a bowl.", "curve banner arc")


def fx_opticcomp(img, p, ctx):
    k = p["amount"] / 100.0 * (-0.8 if p["reverse"] else 0.8); sx, sy = _barrel(img, {"k2": 0}, ctx, k, 1.0 / (1 + max(0, k) * 0.5) if k > 0 else 1.0 / max(0.3, 1 + k * 0.5)); return remap_clear(img, sx, sy)
reg("opticcomp", LN, "Optic compensation", [F("amount", "Amount", 40, 0, 100), B("reverse", "Add distortion instead of removing it", False)], fx_opticcomp, "Straightens the curved lines made by a wide-angle lens (or adds the curve).", "lens correction wide angle")


def fx_dirsmear(img, p, ctx):
    h, w = img.shape[:2]; a = np.deg2rad(p["angle"]); n = int(max(1, p["length"] * ctx.k)); f = f3(img); L = lum(f); m = np.clip((L - p["threshold"] / 100.0) / max(0.01, 1 - p["threshold"] / 100.0), 0, 1)[..., None]; acc = (f * m).astype(np.float32) if p["only_bright"] else f.copy(); covered = 1; step = 1.0; d = np.array([np.cos(a), np.sin(a)])
    while covered < n:
        s = min(step, n - covered); Mt = np.float32([[1, 0, d[0] * s], [0, 1, d[1] * s]]); acc = np.maximum(acc, cv2.warpAffine(acc, Mt, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) * (p["decay"] / 100.0) ** (s / max(n, 1) * 3)); covered += s; step *= 2
    return pack(np.clip(np.maximum(f, acc) * (p["amount"] / 100.0) + f * (1 - p["amount"] / 100.0), 0, 1), like=img)
reg("dirsmear", LN, "Directional smear", [F("length", "Length", 80, 1, 500), F("angle", "Direction", 0, -180, 180), F("decay", "Fade along the smear", 85, 10, 100), F("threshold", "Bright from", 55, 0, 95), B("only_bright", "Smear only the bright parts", True), F("amount", "Amount", 100, 0, 100)], fx_dirsmear, "Bright parts are dragged into long streaks, like light trails.", "streak trails")


# ------------------------------------------------------------------ water & glass
def fx_water3d(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); hz = h * p["horizon"] / 100.0; t = ctx.lt * p["speed"] * 2 * np.pi; d = np.maximum(y - hz, 0.0) / max(1.0, h - hz); depth = 1.0 / (0.25 + d)
    wave = (np.sin(x / (S(ctx, p["length"]) * (0.4 + d * 0.9)) + t + d * 6) + 0.5 * np.sin(x / (S(ctx, p["length"]) * 0.6 * (0.4 + d)) - t * 1.3)) * p["ripple"] * ctx.k * (0.2 + d)
    sy = hz - (y - hz) * (0.6 + 0.8 * p["depth"] / 100.0) * 1.0 + wave * 0.6; sx = x + wave; refl = remap(img, sx, sy, cv2.BORDER_REFLECT); f = f3(refl); tint = bgr(p["color"]); res = f * (p["reflect"] / 100.0) * (1 - d[..., None] * 0.3) + tint * (1 - p["reflect"] / 100.0) * 0.5 + tint * 0.25 * d[..., None]
    sp = np.clip(np.sin(x / 40 + t * 2 + d * 10) * np.sin(d * 30 - t), 0, 1) ** 8 * 0.3 * d; res = res + sp[..., None]; below = (y > hz)[..., None]; out = np.where(below, res, f3(img)); return pack(np.clip(out, 0, 1), like=img)
reg("water3d", WG, "3D water", [F("horizon", "Water line", 55, 10, 95), F("ripple", "Waves", 10, 0, 60), F("length", "Wave length", 40, 5, 200), F("depth", "Depth", 60, 0, 100), F("reflect", "Reflection", 70, 0, 100), C("color", "Water color", "#0b4f6c"), F("speed", "Speed", 0.5, 0, 4)], fx_water3d, "The lower part becomes a lake with perspective waves that reflect the top part.", "lake sea reflection ocean")


def fx_glass(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); s = S(ctx, p["size"]); st = p["strength"] * ctx.k
    if p["kind"] == "reeded": ph = (x / s) % 1.0; dx = (ph - 0.5) * 2 * st * 1.5; dy = 0 * x; nrm = (ph - 0.5) * 2
    elif p["kind"] == "frosted": dx = (noise(h, w, 2, int(p["seed"]), 0) - 0.5) * 2 * st; dy = (noise(h, w, 2, int(p["seed"]) + 1, 0) - 0.5) * 2 * st; nrm = dx / max(st, 1e-3)
    else: n1 = fbm(h, w, s * 2, int(p["seed"]), ctx.lt * p["speed"], 3); gy, gx = np.gradient(cv2.GaussianBlur(n1, (0, 0), 1.5)); dx = gx * st * 40; dy = gy * st * 40; nrm = gx / (np.abs(gx).max() + 1e-6)
    out = displace(img, dx, dy)
    if p["frost"] > 0: out = blend(out, f3(blur_bgra(out, p["frost"] * ctx.k * 0.15)), None, "replace", 0.8)
    sh = np.clip(nrm, 0, 1) ** 2 * (p["shine"] / 100.0) * 0.6; f = f3(out) + sh[..., None]; return pack(np.clip(f, 0, 1), like=out)
reg("glass", WG, "Glass surface", [CH("kind", "Glass", "reeded", [("reeded", "Ribbed (reeded)"), ("frosted", "Frosted"), ("bumpy", "Bumpy")]), F("size", "Rib / bump size", 24, 4, 150), F("strength", "Refraction", 8, 0, 100), F("frost", "Frost blur", 8, 0, 100), F("shine", "Shine", 40, 0, 100), F("speed", "Speed", 0.2, 0, 4), SEED()], fx_glass, "The picture seen through ribbed, frosted or bumpy glass.", "reeded refraction shower window")


def fx_liquidwave(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; s = S(ctx, p["length"]); a = p["amount"] * ctx.k
    dx = (np.sin(y / s + t) + np.sin(x / (s * 1.7) - t * 0.8) * 0.6) * a; dy = (np.sin(x / s + t * 1.2) + np.sin(y / (s * 1.4) + t * 0.5) * 0.6) * a; return remap(img, x + dx, y + dy)
reg("liquidwave", WG, "Liquid wave", [F("amount", "Amount", 10, 0, 100), F("length", "Wave length", 50, 5, 400), F("speed", "Speed", 0.5, 0, 5)], fx_liquidwave, "A slow liquid wobble across the whole picture.", "jelly wobble")


def fx_melting(img, p, ctx):
    h, w = img.shape[:2]; rh, rw = ref_size(h, w); ox, oy = ref_origin()      # the media: the whole picture, unless the effect spills outside the media
    pr = prog(p, ctx); x, y = coords(h, w); s = S(ctx, p["width"]); xr, yr = x - ox, y - oy
    col = np.random.default_rng(int(p["seed"])).random(int(rw / s) + 3).astype(np.float32); col = cv2.resize(col[None, :], (rw, 1), interpolation=cv2.INTER_CUBIC)[0]
    col = col[np.clip(xr[0].astype(np.int32), 0, rw - 1)]
    drip = (0.3 + col * 0.7)[None, :] * pr * rh * 1.3 * (1 + 0.3 * np.sin(xr / (s * 3))); ysrc = y - drip * (0.4 + 0.6 * np.clip(yr / rh, 0, None)); return remap_clear(img, x, ysrc)       # what melts away leaves empty space at the top; nothing is mirrored back
reg("melting", WG, "Melting screen", WIPE(50) + [F("width", "Drip width", 30, 4, 200), SEED()], fx_melting, "The picture melts and drips down the screen.", "drip slime")


def fx_refraction(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); t = ctx.lt * p["speed"]; n = fbm(h, w, s, int(p["seed"]), t, 3); gy, gx = np.gradient(cv2.GaussianBlur(n, (0, 0), 1.2)); k = p["strength"] * ctx.k * 60; out = img.copy(); x, y = coords(h, w); sp = p["dispersion"] / 10.0
    for c, m in ((2, 1 + sp), (1, 1.0), (0, 1 - sp)): out[..., c] = cv2.remap(np.ascontiguousarray(img[..., c]), (x + gx * k * m).astype(np.float32), (y + gy * k * m).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out
reg("refraction", WG, "Refraction warp", [F("strength", "Strength", 10, 0, 100), F("size", "Size", 60, 5, 400), F("dispersion", "Color split", 20, 0, 100), F("speed", "Speed", 0.4, 0, 5), SEED()], fx_refraction, "Light bends through uneven glass or water, splitting the colors a little.", "caustics distortion lens")


def fx_waterwave(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); t = ctx.lt * p["speed"] * 2 * np.pi; s = S(ctx, p["length"]); wx = np.sin(y / s + t) * p["ax"] * ctx.k; wy = np.sin(x / s * 0.8 - t) * p["ay"] * ctx.k; out = remap(img, x + wx, y + wy); sh = np.cos(y / s + t) * p["shade"] / 100.0 * 0.15; f = f3(out) * (1 + sh[..., None]); return pack(np.clip(f, 0, 1), like=out)
reg("waterwave", WG, "Water wave", [F("ax", "Sideways", 8, 0, 100), F("ay", "Up and down", 6, 0, 100), F("length", "Wave length", 45, 5, 300), F("shade", "Light and dark", 40, 0, 100), F("speed", "Speed", 0.6, 0, 5)], fx_waterwave, "Looking at the picture through gently moving water.", "underwater")


def fx_ripplewater(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); dxs = np.zeros((h, w), np.float32); dys = np.zeros((h, w), np.float32); shade = np.zeros((h, w), np.float32); L = S(ctx, p["length"])
    for i in range(int(p["drops"])):
        r = np.random.default_rng(int(p["seed"]) * 37 + i); per = r.uniform(1.5, 3.0) / max(p["speed"], 0.05); ph = (ctx.lt + r.random() * per) % per; px, py = r.random() * w, r.random() * h; d = np.hypot(x - px, y - py); rad = ph * min(w, h) * 0.35 * p["speed"]
        env = np.exp(-((d - rad) / (L * 1.3)) ** 2) * np.exp(-ph / per * 2.5) * np.sin((d - rad) / L * 2 * np.pi); dxs += env * (x - px) / np.maximum(d, 1) * p["amount"] * ctx.k; dys += env * (y - py) / np.maximum(d, 1) * p["amount"] * ctx.k; shade += env
    out = remap(img, x + dxs, y + dys); f = f3(out) * (1 + shade[..., None] * 0.35 * p["shade"] / 100.0); return pack(np.clip(f, 0, 1), like=out)
reg("ripplewater", WG, "Ripple water", [I("drops", "Drops", 5, 1, 12), F("amount", "Strength", 10, 0, 60), F("length", "Ring width", 18, 4, 100), F("shade", "Light and dark", 60, 0, 100), F("speed", "Speed", 1.0, 0.2, 4), SEED()], fx_ripplewater, "Drops hit the water and rings spread out and fade.", "drops pond rings")


def fx_raindrop(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"])); out = img.copy(); t = ctx.lt * p["speed"]
    for i in range(int(p["count"])):
        rad = S(ctx, p["size"]) * r.uniform(0.5, 1.3); px = r.random() * w; py0 = r.random() * h; slide = (t * r.uniform(0.0, 14) * ctx.k) % (h + rad * 4); py = (py0 + slide) % (h + 2 * rad) - rad
        x0, x1, y0, y1 = int(max(0, px - rad * 1.6)), int(min(w, px + rad * 1.6)), int(max(0, py - rad * 2.2)), int(min(h, py + rad * 1.8))
        if x1 <= x0 or y1 <= y0: continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32); nx = (xx - px) / rad; ny = (yy - py) / (rad * 1.25); r2 = nx * nx + ny * ny; ins = r2 < 1; z = np.sqrt(np.clip(1 - r2, 0, 1))
        sx = px - nx * rad * (0.4 + 0.6 * p["refract"] / 100.0) * 1.4 * 1; sy = py - ny * rad * 1.25 * (0.4 + 0.6 * p["refract"] / 100.0) * 1.4
        win = cv2.remap(np.ascontiguousarray(img), sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT); a = np.clip((1 - np.sqrt(r2)) * rad / 1.2, 0, 1)[..., None]
        hi = np.exp(-(((nx + 0.35) ** 2 + (ny + 0.4) ** 2) / 0.04)) * 0.7; win = win.astype(np.float32); win[..., :3] = win[..., :3] * (0.75 + 0.25 * z[..., None]) + hi[..., None] * 255
        out[y0:y1, x0:x1] = (win * a + out[y0:y1, x0:x1].astype(np.float32) * (1 - a)).astype(np.uint8)
    return out
reg("raindrop", WG, "Rain drop", [I("count", "Drops", 30, 1, 150), F("size", "Drop size", 12, 3, 60), F("refract", "Upside-down lens", 70, 0, 100), F("speed", "Slide speed", 1.0, 0, 8), SEED()], fx_raindrop, "Drops on a window, each one showing a tiny upside-down copy of the world.", "rain window glass droplets")


def fx_puddle(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); n = fbm(h, w, S(ctx, p["size"]) * 3, int(p["seed"]), 0, 3); base = h * p["level"] / 100.0; mask = sm(n * 0.7 + (y / h) * 0.6, 0.62 - p["spread"] / 400.0, 0.7 - p["spread"] / 400.0 + 0.06) * (y > base)
    t = ctx.lt * p["speed"] * 2 * np.pi; rip = (np.sin(x / S(ctx, 14) + t + y / S(ctx, 20)) * p["ripple"] * ctx.k * (0.3 + (y - base) / h)); refl = remap(img, x + rip, 2 * base - y + rip * 0.5, cv2.BORDER_REFLECT)
    if p["blur"] > 0: refl = blur_bgra(refl, p["blur"] * ctx.k * 0.2)
    f = f3(img); r = f3(refl) * 0.75 + bgr("#2a3540") * 0.15; out = f * (1 - mask[..., None]) + r * mask[..., None]; edge = np.clip(1 - np.abs(mask - 0.5) * 2, 0, 1) * 0.15; return pack(np.clip(out + edge[..., None], 0, 1), like=img)
reg("puddle", WG, "Puddle", [F("level", "Ground line", 60, 20, 95), F("spread", "Puddle size", 60, 0, 100), F("size", "Puddle shape", 40, 5, 200), F("ripple", "Ripples", 5, 0, 40), F("blur", "Soft reflection", 15, 0, 100), F("speed", "Speed", 0.6, 0, 4), SEED()], fx_puddle, "Puddles on the ground that reflect the picture above them.", "reflection wet floor")


# ------------------------------------------------------------------ blur (more)
def _avg(img, mats, w, h):
    acc = np.zeros(img.shape, np.float32); pm = pm4(img)
    for M in mats: acc += cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return unpm4(acc / len(mats))


def fx_zoomblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; return _avg(img, [xform(h, w, 0, 0, 0, 1 + p["amount"] / 100.0 * (i / (n - 1) - 0.5 * (0 if p["onesided"] else 1)), cx, cy) for i in range(n)], w, h)
reg("zoomblur", BL, "Zoom blur", [F("amount", "Amount", 18, 0, 100), I("steps", "Quality", 16, 4, 40), B("onesided", "One direction", False)] + CEN(), fx_zoomblur, "Streaks that rush toward or away from a center point.", "radial speed")


def fx_dirblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); a = np.deg2rad(p["angle"]); L = p["length"] * ctx.k
    return _avg(img, [np.float32([[1, 0, np.cos(a) * L * (i / (n - 1) - (0 if p["onesided"] else 0.5))], [0, 1, np.sin(a) * L * (i / (n - 1) - (0 if p["onesided"] else 0.5))]]) for i in range(n)], w, h)
reg("dirblur", BL, "Directional blur", [F("length", "Length", 40, 0, 300), F("angle", "Direction", 0, -180, 180), I("steps", "Quality", 16, 4, 40), B("onesided", "Comet (one direction)", False)], fx_dirblur, "Blurs in one direction, both ways or like a comet tail.", "motion line")


def fx_boxblur(img, p, ctx):
    k = int(max(1, p["size"] * ctx.k)) * 2 + 1; pm = pm4(img)
    for _ in range(int(p["passes"])): pm = cv2.blur(pm, (k, k), borderType=cv2.BORDER_REPLICATE)
    return unpm4(pm)
reg("boxblur", BL, "Box blur", [F("size", "Size", 6, 0, 100), I("passes", "Passes", 1, 1, 4)], fx_boxblur, "A plain, fast, even blur (more passes make it smoother).", "average")


def fx_innerblur(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); d = np.minimum(np.minimum(x, w - 1 - x) / w, np.minimum(y, h - 1 - y) / h) * 2; edge = sm(d, p["border"] / 100.0 * 0.5, p["border"] / 100.0 * 0.5 + p["feather"] / 100.0 * 0.5 + 1e-3); bl = blur_bgra(img, p["amount"] * ctx.k * 0.5)
    return blend(img, f3(bl), edge * (bl[..., 3].astype(np.float32) / 255.0 * 0 + 1), "replace", 1.0)
reg("innerblur", BL, "Inner blur", [F("amount", "Blur", 40, 0, 150), F("border", "Sharp border", 25, 0, 100), F("feather", "Soft transition", 50, 0, 100)], fx_innerblur, "Blurs the inside of the picture and keeps the edges sharp (the opposite of a vignette blur).", "tilt shift focus edge sharp")


def fx_spinblur(img, p, ctx):
    h, w = img.shape[:2]; n = int(p["steps"]) if not ctx.fast else max(6, int(p["steps"]) // 2); cx, cy = p["cx"] / 100.0, p["cy"] / 100.0; return _avg(img, [xform(h, w, 0, 0, p["angle"] * (i / (n - 1) - 0.5), 1.0, cx, cy) for i in range(n)], w, h)
reg("spinblur", BL, "Spin blur", [F("angle", "Angle", 12, 0, 90), I("steps", "Quality", 16, 4, 40)] + CEN(), fx_spinblur, "A blur that turns around a center, like a spinning wheel.", "rotational radial")


def fx_streakstrips(img, p, ctx):
    h, w = img.shape[:2]; r = np.random.default_rng(int(p["seed"]) + int(ctx.lt * p["rate"])); n = int(p["strips"]); cuts = np.linspace(0, h, n + 1).astype(int); out = img.copy()
    for i in range(n):
        y0, y1 = cuts[i], cuts[i + 1]; L = int(max(0, r.uniform(0.2, 1.0) * p["length"] * ctx.k))
        if L > 1 and r.random() < p["density"] / 100.0: out[y0:y1] = unpm4(cv2.blur(pm4(img[y0:y1]), (L, 1), borderType=cv2.BORDER_REPLICATE))
    return out
reg("streakstrips", BL, "Streak strips", [I("strips", "Strips", 18, 3, 80), F("length", "Streak length", 90, 2, 500), F("density", "How many are blurred", 70, 0, 100), F("rate", "Changes / s", 6, 0, 30), SEED()], fx_streakstrips, "Horizontal strips, each blurred by a different amount, like speed lines.", "speed lines horizontal")


def fx_moveblur(img, p, ctx):
    h, w = img.shape[:2]; k = 0.5 - 0.5 * np.cos(2 * np.pi * ctx.lt / max(0.2, p["period"])); L = p["length"] * k * ctx.k; a = np.deg2rad(p["angle"] + ctx.lt * p["turn"]); n = 14 if ctx.fast else 20
    if L < 0.5: return img
    return _avg(img, [np.float32([[1, 0, np.cos(a) * L * (i / (n - 1) - 0.5)], [0, 1, np.sin(a) * L * (i / (n - 1) - 0.5)]]) for i in range(n)], w, h)
reg("moveblur", BL, "Pulsing directional blur (old move blur)", [F("length", "Most blur", 60, 0, 300), F("angle", "Direction", 0, -180, 180), F("period", "Blur comes and goes every (s)", 1.5, 0.3, 20), F("turn", "Direction turns (deg / s)", 0, -360, 360)], fx_moveblur, "A motion blur that swells and fades by itself, like a camera whip.", "whip pan camera move")

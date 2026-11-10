"""ledgrid: LED grid. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_ledgrid(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); gw, gh = max(1, int(w / s)), max(1, int(h / s)); small = cv2.resize(img, (gw, gh), interpolation=cv2.INTER_AREA); x, y = coords(h, w); lx = (x / s) % 1.0 - 0.5; ly = (y / s) % 1.0 - 0.5
    d = np.maximum(np.abs(lx), np.abs(ly)) if p["shape"] == "square" else np.sqrt(lx * lx + ly * ly); r = p["fill"] / 100.0 * 0.5; m = np.clip((r - d) * s / max(1.0, ctx.k) + 0.5, 0, 1); cell = small[np.clip((y / s).astype(int), 0, gh - 1), np.clip((x / s).astype(int), 0, gw - 1)]
    f = f3(cell) * (1 + p["bright"] / 100.0); out = f * m[..., None]
    if p["glow"] > 0: out = out + glow_of(out, s * 0.6) * (p["glow"] / 100.0)
    return pack(np.clip(out + bgr(p["gap"]) * (1 - m[..., None]), 0, 1), like=img)

reg("ledgrid", IK, "LED grid", [F("size", "LED size", 10, 3, 60), F("fill", "LED fill", 85, 20, 100), CH("shape", "Shape", "round", [("round", "Round"), ("square", "Square")]), F("bright", "Brightness", 20, -50, 100), F("glow", "Glow", 40, 0, 100), C("gap", "Between LEDs", "#050505")], fx_ledgrid, "The picture shown on a wall of little LED lights.", "led screen pixel matrix")

ID = "ledgrid"

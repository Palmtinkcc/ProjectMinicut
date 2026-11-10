"""bioscanner: Bioscanner 3D. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_bioscanner(img, p, ctx):
    h, w = img.shape[:2]; f = f3(img); L = lum(f); col = bgr(p["color"]); pos = (ctx.lt * p["speed"] * 0.25) % 1.0
    # beam, grid lines and the wire rows depend on the row (or the column) only: they are worked out as one column / one row and broadcast (same numbers)
    y_ = np.arange(h, dtype=np.float32)[:, None]; x_ = np.arange(w, dtype=np.float32)[None, :]; y = y_ / h; d = np.abs(y - pos); beam = np.clip(1 - d / (p["width"] / 100.0 * 0.3 + 1e-3), 0, 1) ** 2
    gs = S(ctx, p["grid"]); grid = ((np.abs((x_ % gs) - gs / 2) < 0.6) | (np.abs((y_ % gs) - gs / 2) < 0.6)).astype(np.float32)
    wire = np.clip(1 - np.abs((y_ % gs) - gs / 2) / 1.2, 0, 1) * np.clip(L * 1.5, 0, 1)
    body = f * (0.55 + 0.45 * (1 - beam[..., None])) * 0.8; inside = beam[..., None]; out = body * (1 - inside) + (np.stack([wire] * 3, -1) * col * 1.3 + grid[..., None] * col * 0.4 + f * 0.25) * inside
    out = out + col * 0.06 + (beam[..., None] > 0.9) * col * 0.4; return pack(np.clip(out, 0, 1), like=img)

reg("bioscanner", G, "Bioscanner 3D", [C("color", "Color", "#3dff9a"), F("speed", "Scan speed", 2.0, 0, 10), F("width", "Beam width", 45, 5, 100), F("grid", "Grid size", 10, 4, 60)], fx_bioscanner,
    "A scanning beam sweeps down the picture and shows it as a glowing wireframe grid.", "scan wireframe medical")

ID = "bioscanner"

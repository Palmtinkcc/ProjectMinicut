"""fractal: Fractal texture. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

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

ID = "fractal"

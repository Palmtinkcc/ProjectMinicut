"""gradflow: Gradient flow. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_gradflow(h, w, p, ctx, t):
    x, y = norm_coords(h, w); a = np.deg2rad(p["angle"]); k = 3.0 / max(0.2, p["scale"] / 30.0); wp = (fbm(h, w, sc(ctx, p) * 4, int(p["seed"]), t * 0.4, 3) - 0.5) * p["warp"] / 20.0
    v = 0.5 + 0.5 * np.sin((x * np.cos(a) + y * np.sin(a)) * k + wp * 6 + t); return pal3(p, v), None

reg("gradflow", BG, "Gradient flow", BGP([F("angle", "Angle", 35, -180, 180), F("warp", "Flow", 60, 0, 100)] + CP3), bgfx(g_gradflow), "Smooth colors that flow and swirl like silk.", "mesh gradient silk")

ID = "gradflow"

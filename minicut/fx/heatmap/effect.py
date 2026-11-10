"""heatmap: Heat map. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_heat(h, w, p, ctx, t): f = fbm(h, w, sc(ctx, p), int(p["seed"]), t); f = np.clip((f - 0.5) * (1 + p["contrast"] / 50.0) + 0.5, 0, 1); return ramp(f, _PAL[p["palette"]]), None

reg("heatmap", BG, "Heat map", BGP([CH("palette", "Colors", "thermal", [("thermal", "Thermal"), ("viridis", "Viridis"), ("cool", "Cool")]), F("contrast", "Contrast", 30, 0, 100)]), bgfx(g_heat), "A thermal-camera map of moving hot and cold areas.", "thermal infrared")

ID = "heatmap"

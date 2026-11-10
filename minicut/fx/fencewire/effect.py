"""fencewire: Fencing wire. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_wire(h, w, p, ctx, t):
    x, y = coords(h, w); s = sc(ctx, p) * 0.5; u = (x + y) / s + t * 0.3; v = (x - y) / s; d = np.minimum(np.abs(np.sin(np.pi * u)), np.abs(np.sin(np.pi * v))); wire = 1 - sm(d, 0.03, 0.03 + p["thick"] / 100.0 * 0.4)
    shade = 0.6 + 0.4 * np.cos(np.pi * u) * np.cos(np.pi * v); return bgr(p["c1"]) * (1 - wire[..., None]) + bgr(p["c2"]) * (wire * shade)[..., None], None

reg("fencewire", BG, "Fencing wire", BGP([F("thick", "Wire thickness", 25, 3, 100), C("c1", "Background", "#10131a"), C("c2", "Wire", "#c9d2e0")]), bgfx(g_wire), "A chain-link fence of crossing diagonal wires.", "chainlink mesh diamond")

ID = "fencewire"

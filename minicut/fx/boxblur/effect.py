"""Box blur: separable, replicated border, 16-bit intermediate targets. A see-through picture is premultiplied first and un-premultiplied after (like the CPU)."""
import math

from ..pool.gl import Pass, Built, shaders

ID = "boxblur"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    r = int(max(1, p["size"] * c.k)); n = int(p["passes"])
    if r > 100 or n < 1: return None if r > 100 else Built([])
    ps = []; cur = "in"
    if not opaque:                                                   # see-through edges need premultiplied pixels: premultiply, blur four channels, undo
        from ...render.glfx_lib import _PREM, _UNPREM
        ps.append(Pass(_PREM, {}, {"u_in": "in"}, "bxpm", dt="f2")); cur = "bxpm"
    for i in range(n):
        ps.append(Pass(SH["box"], {"u_dir": (1, 0), "u_r": r}, {"u_in": cur}, "bx%da" % i, dt="f2")); cur = "bx%da" % i
        ps.append(Pass(SH["box"], {"u_dir": (0, 1), "u_r": r}, {"u_in": cur}, "bx%db" % i, dt="f2" if (i < n - 1 or not opaque) else "f1")); cur = "bx%db" % i
    if not opaque:
        ps.append(Pass(_UNPREM, {}, {"u_in": cur}, "main")); return Built(ps, alpha=True)
    ps[-1].out = "main"
    return Built(ps)

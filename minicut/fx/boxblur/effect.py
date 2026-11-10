"""Box blur: separable, replicated border, 16-bit intermediate targets. Pictures with see-through pixels are left to the CPU (it blurs premultiplied)."""
from ..pool.cpu_warp import *

def fx_boxblur(img, p, ctx):
    k = int(max(1, p["size"] * ctx.k)) * 2 + 1; pm = pm4(img)
    for _ in range(int(p["passes"])): pm = cv2.blur(pm, (k, k), borderType=cv2.BORDER_REPLICATE)
    return unpm4(pm)

reg("boxblur", BL, "Box blur", [F("size", "Size", 6, 0, 100), I("passes", "Passes", 1, 1, 4)], fx_boxblur, "A plain, fast, even blur (more passes make it smoother).", "average")


# ------------------------------------------------------------------ GPU version
import math

from ..pool.gl import Pass, Built, shaders

ID = "boxblur"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    if not opaque: return None                                       # see-through edges need premultiplied pixels: the CPU function does that
    r = int(max(1, p["size"] * c.k)); n = int(p["passes"])
    if r > 100 or n < 1: return None if r > 100 else Built([])
    ps = []; cur = "in"
    for i in range(n):
        ps.append(Pass(SH["box"], {"u_dir": (1, 0), "u_r": r}, {"u_in": cur}, "bx%da" % i, dt="f2")); cur = "bx%da" % i
        ps.append(Pass(SH["box"], {"u_dir": (0, 1), "u_r": r}, {"u_in": cur}, "bx%db" % i, dt="f2" if i < n - 1 else "f1")); cur = "bx%db" % i
    ps[-1].out = "main"
    return Built(ps)

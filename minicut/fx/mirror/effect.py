"""Mirror left/right, right/left, top/bottom, bottom/top or four ways around a centre. The kaleidoscope mode is left to the CPU (build returns None)."""
from ...shared.deps import *
from ...render.effects import register

def fx_mirror(img, p, ctx):
    axis = p.get("axis", "horizontal")   # horizontal | vertical | both
    cx   = p.get("cx", 50.0) / 100.0
    cy   = p.get("cy", 50.0) / 100.0
    h, w = img.shape[:2]
    out = img.copy()
    if axis in ("horizontal", "both"):
        split_x = int(w * cx)
        left = out[:, :split_x]
        flipped = cv2.flip(left, 1)
        right_w = w - split_x
        flipped_cropped = flipped[:, max(0, flipped.shape[1] - right_w):]
        fw = min(right_w, flipped_cropped.shape[1])
        out[:, split_x:split_x + fw] = flipped_cropped[:, :fw]
    if axis in ("vertical", "both"):
        split_y = int(h * cy)
        top = out[:split_y, :]
        flipped = cv2.flip(top, 0)
        bot_h = h - split_y
        flipped_cropped = flipped[max(0, flipped.shape[0] - bot_h):, :]
        fh = min(bot_h, flipped_cropped.shape[0])
        out[split_y:split_y + fh, :] = flipped_cropped[:fh, :]
    return out

register("mirror", "Distort", "Mirror",
         [("axis", "Axis", "choice", "horizontal",
           [("horizontal", "Horizontal"), ("vertical", "Vertical"), ("both", "Both")], None),
          ("cx", "Center X", "float", 50.0, 0.0, 100.0),
          ("cy", "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_mirror,
         help="Mirror the layer along a horizontal, vertical, or both axes.")


# ------------------------------------------------------------------ GPU version
from ..pool.cpu_warp import *

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


# ------------------------------------------------------------------ GPU version
import math

from ..pool.gl import Pass, Built, shaders

ID = "mirror"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def build(p, c, w, h, opaque):
    m = {"lr": 0, "rl": 1, "tb": 2, "bt": 3, "quad": 4}.get(p["mode"])
    if m is None: return None                                        # kaleidoscope: the CPU does it
    return Built([Pass(SH["main"], {"u_mode": m, "u_c": (w * float(p["cx"]) / 100.0, h * float(p["cy"]) / 100.0)})])

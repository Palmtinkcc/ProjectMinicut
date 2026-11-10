"""bend: Warp (bend). CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_bend(img, p, ctx):
    h, w = img.shape[:2]; x, y = coords(h, w); k = p["amount"] / 100.0 * h * 0.6; u = (x - w / 2) / (w / 2); return remap(img, x, y + (u * u - 0.5) * k * (1 if p["dir"] == "arch" else -1), cv2.BORDER_CONSTANT)

reg("bend", LN, "Warp (bend)", [F("amount", "Bend", 50, -100, 100), CH("dir", "Bends", "arch", [("arch", "Like an arch"), ("bowl", "Like a bowl")])], fx_bend, "Bends the whole picture into an arch or a bowl.", "curve banner arc")

ID = "bend"

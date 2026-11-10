"""rgb_split: RGB Split. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import fx_rgb_split, register

register("rgb_split", "Distort", "RGB Split",
         [("amount", "Distance", "float",  8.0,  0.0, 80.0),
          ("angle",  "Angle",    "float",  0.0, -180.0, 180.0),
          ("mode",   "Mode",     "choice", "directional",
           [("directional", "Directional"), ("zoom", "Zoom"), ("radial", "Radial")], None),
          ("cx", "Center X", "float", 50.0, 0.0, 100.0),
          ("cy", "Center Y", "float", 50.0, 0.0, 100.0)],
         fx_rgb_split,
         help="Chromatic aberration with Directional, Zoom, and Radial modes.")

ID = "rgb_split"

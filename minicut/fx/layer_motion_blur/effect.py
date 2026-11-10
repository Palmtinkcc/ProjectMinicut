"""layer_motion_blur: Motion Blur. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_motion import *

def fx_layer_motion_blur(img, p, ctx): return img          # the renderer does the work when the clip is placed

reg("layer_motion_blur", BL, "Motion Blur",
    [F("tune", "Tune (shutter, 100 = one frame)", 100, 0, 400), F("position", "Position", 100, 0, 100), F("scale", "Scale", 100, 0, 100), F("angle", "Angle", 100, 0, 100)],
    fx_layer_motion_blur, "Blurs the clip along its own movement: the position, size and turn you keyframed. Still clips are not blurred.", "movement keyframe shutter camera")

ID = "layer_motion_blur"

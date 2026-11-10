"""Motion blur, the way a camera makes it.

* Motion Blur ("layer_motion_blur"): blurs a clip along the way it MOVES (Position, Scale and Rotation keyframes, also moves made by the node graph).
  This effect itself changes no pixel; the renderer (Renderer._attach_mb / _draw_mb) draws the clip several times at moments inside the shutter time
  around the frame and averages them. A clip that stands still costs nothing.
* Video Motion Blur ("video_motion_blur"): blurs the parts of a VIDEO that move inside the picture. The frames before and after give the motion of every
  pixel (optical flow); the picture is blurred along that motion. Needs a video clip (nothing happens on an image).
The old "Motion Blur" (a plain blur in one direction) is now called Directional Blur (old Motion Blur); "Directional blur" in this pack does the same job."""
from .cpu_kit import *
from ...render import effects as _E
from ...render import fastfx as _FF

BL = "Blur"


_FF.LANE_BGR = _FF.LANE_BGR | {"layer_motion_blur"}          # it never touches the picture, so it must not push the clip off the fast 3-channel lane


_FLOW = OrderedDict(); _FLOCK = threading.Lock()


def _flow(prev, nxt, key, sw, sh):
    """Motion of every pixel between the frame before and the frame after (pixels of the small picture, over TWO frames). Kept for a few frames
    so moving a slider does not work it out again."""
    with _FLOCK:
        f = _FLOW.get(key)
        if f is not None: _FLOW.move_to_end(key); return f
    g0 = cv2.cvtColor(cv2.resize(prev, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(cv2.resize(nxt, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    f = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    with _FLOCK:
        _FLOW[key] = f
        while len(_FLOW) > 6: _FLOW.popitem(last=False)
    return f


__all__ = [n for n in list(globals()) if not (n.startswith("__") and n.endswith("__"))]    # the effect files import all of it, private helpers too

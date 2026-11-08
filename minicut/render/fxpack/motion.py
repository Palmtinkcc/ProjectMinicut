"""Motion blur, the way a camera makes it.

* Motion Blur ("layer_motion_blur"): blurs a clip along the way it MOVES (Position, Scale and Rotation keyframes, also moves made by the node graph).
  This effect itself changes no pixel; the renderer (Renderer._attach_mb / _draw_mb) draws the clip several times at moments inside the shutter time
  around the frame and averages them. A clip that stands still costs nothing.
* Video Motion Blur ("video_motion_blur"): blurs the parts of a VIDEO that move inside the picture. The frames before and after give the motion of every
  pixel (optical flow); the picture is blurred along that motion. Needs a video clip (nothing happens on an image).
The old "Motion Blur" (a plain blur in one direction) is now called Directional Blur (old Motion Blur); "Directional blur" in this pack does the same job."""
from .kit import *
from .. import effects as _E
from .. import fastfx as _FF

BL = "Blur"


def fx_layer_motion_blur(img, p, ctx): return img          # the renderer does the work when the clip is placed


reg("layer_motion_blur", BL, "Motion Blur",
    [F("tune", "Tune (shutter, 100 = one frame)", 100, 0, 400), F("position", "Position", 100, 0, 100), F("scale", "Scale", 100, 0, 100), F("angle", "Angle", 100, 0, 100)],
    fx_layer_motion_blur, "Blurs the clip along its own movement: the position, size and turn you keyframed. Still clips are not blurred.", "movement keyframe shutter camera")
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


def fx_video_motion_blur(img, p, ctx):
    ctx.lt                                               # the picture depends on the time (the renderer must not keep it from another frame)
    nb = getattr(_E._NB, "fn", None)
    if nb is None: return img
    h, w = img.shape[:2]; s = p["strength"] / 100.0
    if s <= 0.01: return img
    step = getattr(_E._NB, "step", 1.0 / 30)
    try: a = nb(-step); b = nb(step)
    except Exception: return img
    if a is None or b is None or a.shape[:2] != (h, w) or b.shape[:2] != (h, w): return img        # no neighbours (still image, padded picture ...)
    sc = min(1.0, 320.0 / max(h, w)); sw, sh = max(8, int(w * sc)), max(8, int(h * sc))
    flow = _flow(a, b, (getattr(_E._NB, "key", None), sw, sh), sw, sh)
    if p["smooth"] > 0: flow = cv2.GaussianBlur(flow, (0, 0), p["smooth"] / 100.0 * 3.0 + 0.01)
    ws = min(1.0, 960.0 / max(h, w)); ww, wh = max(8, int(w * ws)), max(8, int(h * ws))          # the blur is worked out at most 960 wide, the sharp parts stay full size
    F2 = cv2.resize(flow, (ww, wh), interpolation=cv2.INTER_LINEAR); fx = F2[..., 0] * (w / sw) * 0.5 * ws; fy = F2[..., 1] * (h / sh) * 0.5 * ws      # pixels per frame, in the work picture
    mag = np.hypot(fx, fy) * s; mx_ = float(mag.max())
    if mx_ < 0.4: return img
    n = int(min(max(3, p["quality"]), max(3, math.ceil(mx_) + 1)))
    if ctx.fast: n = min(n, 5)
    work = cv2.resize(img, (ww, wh), interpolation=cv2.INTER_AREA) if ws < 1 else img
    gx, gy = coords(wh, ww); acc = np.zeros(work.shape, np.float32)
    for k in range(n):
        o = (k / (n - 1) - 0.5) * s; r = cv2.remap(np.ascontiguousarray(work), gx + fx * o, gy + fy * o, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE); cv2.accumulate(r, acc)
    blurred = cv2.convertScaleAbs(acc, alpha=1.0 / n)
    up = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_LINEAR) if ws < 1 else blurred
    wt = np.clip(cv2.resize(mag, (w, h), interpolation=cv2.INTER_LINEAR) / 0.6, 0, 1); w8 = (wt * 255 + .5).astype(np.uint8)       # where nothing moves the picture stays exactly as it was
    ch = img.shape[2]; w3 = cv2.merge([w8] * ch); iw3 = cv2.merge([255 - w8] * ch)
    return cv2.add(cv2.multiply(np.ascontiguousarray(img), iw3, scale=1 / 255.0), cv2.multiply(up, w3, scale=1 / 255.0))


reg("video_motion_blur", BL, "Video Motion Blur",
    [F("strength", "Strength (shutter, 100 = one frame)", 100, 0, 400), I("quality", "Quality", 8, 3, 24), F("smooth", "Smooth motion", 30, 0, 100)],
    fx_video_motion_blur, "Blurs what moves inside a video, along its own motion found from the frames before and after. Parts that stand still stay sharp.", "optical flow shutter camera video movement")

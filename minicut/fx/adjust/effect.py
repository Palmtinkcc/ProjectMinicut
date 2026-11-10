"""adjust: Adjust. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, gpu_adjust, register

def fx_adjust(img, p, ctx):
    br = p["brightness"]; co = p["contrast"]; sa = p["saturation"]; hu = p["hue"]
    temp = p.get("temperature", 0.0)
    vib  = p.get("vibrance", 0.0)
    hi   = p.get("highlights", 0.0)
    sh   = p.get("shadows", 0.0)
    if br == 0 and co == 0 and sa == 0 and hu == 0 and temp == 0 and vib == 0 and hi == 0 and sh == 0:
        return img
    # GPU fast path: handles brightness/contrast/saturation/hue in one pass
    # Falls back to CPU for temperature/vibrance/highlights/shadows (rare controls)
    if _GPU_FX and temp == 0 and vib == 0 and hi == 0 and sh == 0:
        try:
            return gpu_adjust(img, br=br, co=co, sa=sa, hu=hu)
        except (GpuFxUnavailable, Exception):
            pass
    f = img[..., :3].astype(np.float32) * (1 / 255)
    # brightness + contrast (lifted shadows approach like AM)
    f = (f - .5) * (1 + co / 100) + .5 + br / 200
    # temperature: shift R and B in opposite directions (warm = more R, less B)
    if temp != 0:
        t = temp / 100.0
        f[..., 2] = np.clip(f[..., 2] + t * 0.15, 0, 1)   # R up when warm
        f[..., 0] = np.clip(f[..., 0] - t * 0.15, 0, 1)   # B down when warm
    # highlights / shadows lift
    if hi != 0 or sh != 0:
        lum = (f[..., 0] * 0.114 + f[..., 1] * 0.587 + f[..., 2] * 0.299)  # luminance
        hi_mask = np.clip((lum - 0.5) * 2, 0, 1)[..., None]   # 0 at mid, 1 at white
        sh_mask = np.clip((0.5 - lum) * 2, 0, 1)[..., None]   # 0 at mid, 1 at black
        f = np.clip(f + hi_mask * (hi / 200.0) + sh_mask * (sh / 200.0), 0, 1)
    if sa != 0 or hu != 0 or vib != 0:
        f8 = np.clip(f * 255, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(f8, cv2.COLOR_BGR2HSV).astype(np.float32)
        if hu != 0: hsv[..., 0] = (hsv[..., 0] + hu / 2.0) % 180
        if sa != 0: hsv[..., 1] = np.clip(hsv[..., 1] * (1 + sa / 100), 0, 255)
        if vib != 0:
            # vibrance: boost low-saturation pixels more (Lightroom-style)
            sat_norm = hsv[..., 1] / 255.0
            vib_boost = (1.0 - sat_norm) * (vib / 100.0)
            hsv[..., 1] = np.clip(hsv[..., 1] + vib_boost * 255, 0, 255)
        f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) * (1 / 255)
    out = img.copy(); out[..., :3] = np.clip(f * 255 + .5, 0, 255).astype(np.uint8); return out

register("adjust", "Color", "Adjust",
         [("brightness",  "Brightness",  "float",  0.0, -100.0, 100.0),
          ("contrast",    "Contrast",    "float",  0.0, -100.0, 100.0),
          ("saturation",  "Saturation",  "float",  0.0, -100.0, 100.0),
          ("hue",         "Hue shift",   "float",  0.0, -180.0, 180.0),
          ("temperature", "Temperature", "float",  0.0, -100.0, 100.0),
          ("vibrance",    "Vibrance",    "float",  0.0, -100.0, 100.0),
          ("highlights",  "Highlights",  "float",  0.0, -100.0, 100.0),
          ("shadows",     "Shadows",     "float",  0.0, -100.0, 100.0)],
         fx_adjust,
         help="Full-featured color adjustment: brightness, contrast, saturation, hue, temperature, vibrance, highlights and shadows.")

ID = "adjust"

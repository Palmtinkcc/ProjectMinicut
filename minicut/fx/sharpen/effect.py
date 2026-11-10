"""sharpen: Sharpen. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, gpu_gaussian_blur, gpu_sharpen, register

def fx_sharpen(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    radius    = max(0.4, p.get("radius", 1.0) * ctx.k)
    threshold = p.get("threshold", 0.0) / 255.0
    if _GPU_FX:
        try:
            blurred_bgra = gpu_gaussian_blur(img, radius)
            return gpu_sharpen(img, blurred_bgra, a, threshold)
        except (GpuFxUnavailable, Exception):
            pass
    rgb = img[..., :3].astype(np.float32)
    blurred = cv2.GaussianBlur(np.ascontiguousarray(img[..., :3]), (0, 0), radius).astype(np.float32)
    diff = rgb - blurred
    if threshold > 0:
        edge = np.abs(diff).max(axis=2) / 255.0
        thr_mask = np.clip((edge - threshold) / max(1e-4, threshold), 0, 1)[..., None]
        sharpened = rgb + diff * a * thr_mask
    else:
        sharpened = rgb + diff * a
    out = img.copy(); out[..., :3] = np.clip(sharpened + .5, 0, 255).astype(np.uint8); return out

register("sharpen", "Stylize", "Sharpen",
         [("amount",    "Amount",    "float", 60.0, 0.0, 300.0),
          ("radius",    "Radius",    "float", 1.0,  0.1, 10.0),
          ("threshold", "Threshold", "float", 0.0,  0.0, 50.0)],
         fx_sharpen,
         help="Unsharp mask sharpening with radius and threshold controls.")

ID = "sharpen"

"""bw: Black & white. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, gpu_bw, register

def fx_bw(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    if _GPU_FX:
        try: return gpu_bw(img, a)
        except (GpuFxUnavailable, Exception): pass
    f = img[..., :3].astype(np.float32); g = (f @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
    out = img.copy(); out[..., :3] = np.clip(f + (g - f) * a + .5, 0, 255).astype(np.uint8); return out

register("bw", "Color", "Black & white",
         [("amount", "Amount", "float", 100.0, 0.0, 100.0)],
         fx_bw)

ID = "bw"

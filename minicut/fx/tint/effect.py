"""tint: Tint. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import GpuFxUnavailable, _GPU_FX, gpu_tint, register

def fx_tint(img, p, ctx):
    a = p["amount"] / 100
    if a <= 0: return img
    col = QColor(p["color"])
    if _GPU_FX:
        try:
            return gpu_tint(img, (col.blueF(), col.greenF(), col.redF()), a)
        except (GpuFxUnavailable, Exception):
            pass
    tc = np.array([col.blueF(), col.greenF(), col.redF()], np.float32)
    f = img[..., :3].astype(np.float32) * (1 / 255); g = (f @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
    tinted = np.where(g < 0.5, 2 * g * tc, 1 - 2 * (1 - g) * (1 - tc)); out = img.copy()
    out[..., :3] = np.clip((f + (tinted - f) * a) * 255, 0, 255).astype(np.uint8); return out

register("tint", "Color", "Tint",
         [("color", "Color", "color", "#2f7bff", None, None),
          ("amount", "Amount", "float", 50.0, 0.0, 100.0)],
         fx_tint)

ID = "tint"

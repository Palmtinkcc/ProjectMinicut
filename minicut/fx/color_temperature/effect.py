"""color_temperature: Color Temperature. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_color_temperature(img, p, ctx):
    """Warm (positive) = more orange, Cool (negative) = more blue. Matches AM's Color Temperature."""
    temp = p["temperature"] / 100.0
    tint = p.get("tint", 0.0) / 100.0   # green (pos) / magenta (neg) axis
    if temp == 0 and tint == 0: return img
    f = img[..., :3].astype(np.float32)
    # Temperature: warm shifts R up and B down along a curve that feels perceptually linear
    f[..., 2] = np.clip(f[..., 2] + temp * 30, 0, 255)   # R
    f[..., 0] = np.clip(f[..., 0] - temp * 30, 0, 255)   # B
    # Tint: green/magenta
    f[..., 1] = np.clip(f[..., 1] + tint * 20, 0, 255)   # G
    f[..., 0] = np.clip(f[..., 0] - tint * 20, 0, 255)   # B (opposed)
    out = img.copy(); out[..., :3] = np.clip(f + .5, 0, 255).astype(np.uint8); return out

register("color_temperature", "Color", "Color Temperature",
         [("temperature", "Temperature", "float", 0.0, -100.0, 100.0),
          ("tint",        "Tint",        "float", 0.0, -100.0, 100.0)],
         fx_color_temperature,
         help="Warm/Cool color temperature and Green/Magenta tint correction — like a camera WB dial.")

ID = "color_temperature"

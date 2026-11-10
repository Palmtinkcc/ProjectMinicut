"""cartoon: Cartoon outline. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_strokes import *

def fx_cartoon(img, p, ctx):
    f = img[..., :3]; sm_ = cv2.bilateralFilter(np.ascontiguousarray(f), 7, 40, 7) if not ctx.fast else cv2.GaussianBlur(f, (0, 0), 1.5); lv = int(p["levels"]); q = (np.floor(sm_.astype(np.float32) / 255 * lv) + 0.5) / lv; hsv = cv2.cvtColor(np.clip(q * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32); hsv[..., 1] = np.clip(hsv[..., 1] * (1 + p["boost"] / 100.0), 0, 255)
    base = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) / 255; e = edges(img, ctx, 1.0); line = sm(e, 0.12 + (1 - p["detail"] / 100.0) * 0.5, 0.2 + (1 - p["detail"] / 100.0) * 0.5)
    if p["width"] > 1: line = cv2.dilate(line, np.ones((int(S(ctx, p["width"]) // 2) * 2 + 1,) * 2, np.uint8))
    return pack(base * (1 - line[..., None]) + bgr(p["color"]) * line[..., None], like=img)

reg("cartoon", SS, "Cartoon outline", [I("levels", "Color steps", 5, 2, 12), F("boost", "Color boost", 25, 0, 100), F("detail", "Outline detail", 55, 0, 100), F("width", "Outline width", 1.5, 1, 8), C("color", "Outline color", "#101018")], fx_cartoon, "Flat colors with black outlines, like a comic.", "comic toon ink lines")

ID = "cartoon"

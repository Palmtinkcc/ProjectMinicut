"""copy_background: Copy Background. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_copy_background(img, p, ctx):
    """Replace the layer with the composited background beneath it, masked by the layer's alpha.
    Effects applied AFTER this see the background pixels under the layer's shape — like an adjustment layer.
    fill=0  → pure adjustment layer (original layer content invisible, only bg copy shows through its mask).
    fill=100 → show 100% of the original layer on top of the bg copy (same as not using the effect).
    """
    h, w = img.shape[:2]
    bg = getattr(ctx, "bg", None)
    if bg is None:
        # No background provided (e.g. bottom layer); fall back to a black canvas
        bg = np.zeros((h, w, 3), np.uint8)

    # Resize the bg snapshot to match this layer's pixel dimensions if needed
    bh, bw = bg.shape[:2]
    if bh != h or bw != w:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)

    # bg is BGR; we need BGRA
    bg_bgra = cv2.cvtColor(bg, cv2.COLOR_BGR2BGRA)
    bg_bgra[..., 3] = 255

    fill = p["fill"] / 100.0   # 0..1

    if fill <= 0.0:
        # Pure adjustment layer: layer alpha becomes the copy mask, content replaced by bg
        out = bg_bgra.copy()
        out[..., 3] = img[..., 3]   # keep original layer's alpha as the mask
    else:
        # Blend original content over bg according to fill
        a = img[..., 3:4].astype(np.float32) / 255.0
        orig = img[..., :3].astype(np.float32)
        bg3  = bg_bgra[..., :3].astype(np.float32)
        merged = bg3 + (orig - bg3) * fill
        out = np.empty_like(img)
        out[..., :3] = np.clip(merged, 0, 255).astype(np.uint8)
        out[..., 3]  = img[..., 3]

    return out

register("copy_background", "Compositing", "Copy Background",
         [("fill", "Fill (original layer)", "float", 0.0, 0.0, 100.0)],
         fx_copy_background,
         help="Copies the composited background into the layer so that effects applied afterwards act on the background pixels within the layer's shape — turning the layer into an adjustment layer.",
         kw="adjustment layer backdrop composite")

ID = "copy_background"

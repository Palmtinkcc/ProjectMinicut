"""tiles: Tiles. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_tiles(img, p, ctx):
    h, w = img.shape[:2]; s = S(ctx, p["size"]); x, y = coords(h, w)
    if p["shape"] == "square":
        cx = (np.floor(x / s) + 0.5) * s; cy = (np.floor(y / s) + 0.5) * s; d = np.maximum(np.abs(x - cx), np.abs(y - cy)) * 2 / s
    else:
        q = (np.sqrt(3) / 3 * x - 1.0 / 3 * y) / (s * 0.58); r_ = (2.0 / 3 * y) / (s * 0.58); X = q; Z = r_; Y = -X - Z; rx, ry, rz = np.round(X), np.round(Y), np.round(Z); dxx, dyy, dzz = np.abs(rx - X), np.abs(ry - Y), np.abs(rz - Z)
        fx_ = (dxx > dyy) & (dxx > dzz); fy_ = (~fx_) & (dyy > dzz); rx = np.where(fx_, -ry - rz, rx); rz = np.where(~fx_ & ~fy_, -rx - ry, rz); cx = s * 0.58 * np.sqrt(3) * (rx + rz / 2); cy = s * 0.58 * 1.5 * rz; d = np.hypot(x - cx, y - cy) / (s * 0.58 * 0.9)
    out = remap(img, np.clip(cx, 0, w - 1), np.clip(cy, 0, h - 1), cv2.BORDER_REPLICATE); gap = np.clip((1 - d - (1 - p["gap"] / 100.0 * 0.0)) * 0, 0, 1)
    if p["gap"] > 0: edge = sm(d, 1 - p["gap"] / 100.0 * 0.4, 1.0); out[..., :3] = (out[..., :3] * (1 - edge[..., None] * 0.8)).astype(np.uint8)
    return out

reg("tiles", DW, "Tiles", [CH("shape", "Tile", "hex", [("square", "Square"), ("hex", "Hexagon")]), F("size", "Tile size", 22, 4, 150), F("gap", "Grout", 40, 0, 100)], fx_tiles, "The picture is cut into square or hexagon tiles, each one a single color.", "mosaic hexagon honeycomb")

ID = "tiles"

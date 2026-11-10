"""deadgpu: Dead GPU glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_deadgpu(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); t = int(S(ctx, p["tile"])); out = img.copy(); gh, gw = h // t + 1, w // t + 1
    for ty in range(gh):
        for tx in range(gw):
            if r.random() > a * 0.35: continue
            y0, x0 = ty * t, tx * t; tile = out[y0:y0 + t, x0:x0 + t]
            if tile.size == 0: continue
            k = int(r.integers(0, 5))
            if k == 0: sy, sx = int(r.integers(0, max(1, h - t))), int(r.integers(0, max(1, w - t))); tile[:] = img[sy:sy + tile.shape[0], sx:sx + tile.shape[1]]
            elif k == 1: tile[..., :3] = tile[..., [1, 2, 0]]
            elif k == 2: tile[..., :3] = r.integers(0, 256, 3, dtype=np.uint8)
            elif k == 3: tile[:, ::2, :3] = 255 - tile[:, ::2, :3]
            else: tile[:] = np.tile(tile[:2], (max(1, tile.shape[0] // 2), 1, 1))[:tile.shape[0]]
    if a > 0.3:
        for _ in range(int(a * 6)): x = int(r.integers(0, w)); ww = int(r.integers(1, max(2, w // 40))); out[:, x:x + ww] = out[:, x:x + 1]
    return out

reg("deadgpu", G, "Dead GPU glitch", GP([F("tile", "Tile size", 16, 4, 64)]), fx_deadgpu, "The look of a failing graphics card: tiles of wrong colors, repeated rows and stretched columns.", "artifact corrupted gpu")

ID = "deadgpu"

"""repgrid: Grid repeat. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_repgrid(img, p, ctx):
    h, w = img.shape[:2]; nx, ny = int(p["cols"]), int(p["rows"]); gap = p["gap"] / 100.0; small = _small(img, 1.0 / nx if nx >= ny else 1.0 / ny); small = cv2.resize(img, (max(1, int(w / nx * (1 - gap))), max(1, int(h / ny * (1 - gap)))), interpolation=cv2.INTER_AREA)
    out = np.zeros_like(img); cw, ch = w / nx, h / ny
    for j in range(ny):
        for i in range(nx):
            tile = small
            if p["mirror"]: tile = small[:, ::-1] if i % 2 else small; tile = tile[::-1] if j % 2 else tile
            x0 = int(i * cw + (cw - tile.shape[1]) / 2); y0 = int(j * ch + (ch - tile.shape[0]) / 2); out[y0:y0 + tile.shape[0], x0:x0 + tile.shape[1]] = tile
    return out

reg("repgrid", RP, "Grid repeat", [I("cols", "Columns", 3, 1, 12), I("rows", "Rows", 3, 1, 12), F("gap", "Gap", 6, 0, 60), B("mirror", "Mirror every other one", False)], fx_repgrid, "The picture is repeated in a grid of small copies.", "tile mosaic copies")

ID = "repgrid"

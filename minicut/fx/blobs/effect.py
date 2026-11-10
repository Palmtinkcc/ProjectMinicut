"""blobs: Color blobs. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_background import *

def g_blobs(h, w, p, ctx, t):
    # Soft field: worked out on a grid with half as many points each way (4x less work) and enlarged (the points are centres of 2x2 blocks of the real pixels)
    hh, ww = (h + 1) // 2, (w + 1) // 2; x = (np.arange(ww, dtype=np.float32) * 2 + 0.5)[None, :]; y = (np.arange(hh, dtype=np.float32) * 2 + 0.5)[:, None]
    r = np.random.default_rng(int(p["seed"])); n = int(p["count"]); fld = np.zeros((hh, ww), np.float32); col = np.zeros((hh, ww, 3), np.float32); cs = [bgr(p["c1"]), bgr(p["c2"]), bgr(p["c3"])]; R = sc(ctx, p)
    for i in range(n):
        ph = r.random(4) * 6.28; sp = r.uniform(0.4, 1.2); cx = w * (0.5 + 0.38 * np.sin(t * sp + ph[0])); cy = h * (0.5 + 0.38 * np.sin(t * sp * 0.8 + ph[1])); rad = R * r.uniform(0.7, 1.3)
        wgt = rad * rad / ((x - cx) ** 2 + (y - cy) ** 2 + 4.0); fld += wgt; col += wgt[..., None] * cs[i % 3]
    col = col / np.maximum(fld[..., None], 1e-4); big = lambda a: cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)
    return big(col), sm(big(fld), 0.7, 1.1)

reg("blobs", BG, "Color blobs", BGP([I("count", "Blobs", 7, 2, 20)] + CP3), bgfx(g_blobs), "Soft colored blobs that float around and melt into each other.", "metaballs lava lamp")

ID = "blobs"

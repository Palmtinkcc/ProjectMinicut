"""shatter: Shatter. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_wipes import *

def fx_shatter(img, p, ctx):
    h, w = img.shape[:2]; pr = prog(p, ctx); n = int(p["pieces"]); r = np.random.default_rng(int(p["seed"])); sites = np.stack([r.random(n) * w, r.random(n) * h], 1); x, y = coords(h, w)
    lab = np.zeros((h, w), np.int32); best = np.full((h, w), 1e18, np.float32)
    for b0 in range(0, h, 48):          # nearest site, band by band (same numbers as one pass, without the big temporaries)
        b1 = min(h, b0 + 48); xb, yb = x[b0:b1], y[b0:b1]; bb = best[b0:b1]; lb = lab[b0:b1]
        for i, (sx, sy) in enumerate(sites): d = (xb - sx) ** 2 + (yb - sy) ** 2; upd = d < bb; bb = np.where(upd, d.astype(np.float32), bb); lb = np.where(upd, np.int32(i), lb)
        best[b0:b1] = bb; lab[b0:b1] = lb
    cx0, cy0 = w * p["x"] / 100.0, h * p["y"] / 100.0; canvas = np.zeros_like(img); items = []
    for i in range(n):
        m = lab == i; cr = m.sum(1)
        if not cr.any(): continue
        cc = m.sum(0); n_ = int(cr.sum()); rows = np.flatnonzero(cr); cols = np.flatnonzero(cc)         # centre and box from the row / column counts (no index lists of every pixel)
        cx, cy = (cc * np.arange(w)).sum() / n_, (cr * np.arange(h)).sum() / n_; dd = np.hypot(cx - cx0, cy - cy0) / np.hypot(w, h); lp = np.clip((pr * 1.6 - dd * 0.9 - r.random() * 0.2) / 0.7, 0, 1)
        items.append((lp, i, m, cx, cy, (rows[0], rows[-1] + 1, cols[0], cols[-1] + 1)))
    for lp, i, m, cx, cy, bb_ in sorted(items, key=lambda o: -o[0]):
        y0_, y1_, x0_, x1_ = bb_; crop = _am(img[y0_:y1_, x0_:x1_], m[y0_:y1_, x0_:x1_].astype(np.float32))
        if lp <= 0: canvas[y0_:y1_, x0_:x1_] = _over(canvas[y0_:y1_, x0_:x1_], crop); continue
        if lp >= 1: continue
        ang = np.arctan2(cy - cy0, cx - cx0); M = cv2.getRotationMatrix2D((cx, cy), r.normal(0, 90) * lp, 1 - lp * 0.5); M[0, 2] += np.cos(ang) * lp * w * p["power"] / 100.0 * 0.5; M[1, 2] += np.sin(ang) * lp * h * p["power"] / 100.0 * 0.5 + lp * lp * h * p["fall"] / 100.0
        canvas = _paste(canvas, _am(crop, 1 - lp), x0_, y0_, M)
    return canvas

reg("shatter", WP, "Shatter", WIPE(35) + [I("pieces", "Pieces", 24, 4, 60), F("power", "Blast", 60, 0, 200), F("fall", "Fall", 40, 0, 200), F("x", "Hit X", 50, 0, 100), F("y", "Hit Y", 50, 0, 100), SEED()], fx_shatter, "The picture shatters like glass into pieces that fly away from the point of impact.", "glass break fragments")

ID = "shatter"

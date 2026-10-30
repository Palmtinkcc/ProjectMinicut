"""Frame renderer: compositing, masks, text, compound clips and the background preview worker."""
from ..shared.deps import *
from ..shared.core import *
from .nodegraph import *
from .effects import apply_effects


_text_cache = OrderedDict()


def render_text(c, q):
    q = max(0.05, q)
    key = (c["text"], c["font"], c["fsize"], c["tcolor"], c["stroke"], c["scolor"], c["bold"], round(q, 3))
    if key in _text_cache: _text_cache.move_to_end(key); return _text_cache[key]
    font = QFont(c["font"]); font.setPixelSize(max(1, int(c["fsize"] * q))); font.setBold(bool(c["bold"]))
    fm = QFontMetrics(font); lines = (c["text"] or " ").split("\n")
    sw = int(c["stroke"] * q); pad = sw + 4
    w = max(1, max(fm.horizontalAdvance(l) for l in lines)) + 2 * pad; h = fm.height() * len(lines) + 2 * pad
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied); img.fill(0)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); path = QPainterPath()
    for i, l in enumerate(lines):
        path.addText(pad + (w - 2 * pad - fm.horizontalAdvance(l)) / 2, pad + fm.ascent() + i * fm.height(), font, l)
    if sw > 0: p.strokePath(path, QPen(QColor(c["scolor"]), sw * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.fillPath(path, QColor(c["tcolor"])); p.end()
    img = img.convertToFormat(QImage.Format_ARGB32)
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine())[:, :w * 4]
    arr = arr.reshape(h, w, 4).copy()   # memory order = B,G,R,A
    _text_cache[key] = arr
    while len(_text_cache) > 64: _text_cache.popitem(last=False)
    return arr


MASKS = ["None", "Split", "Filmstrip", "Circle", "Rect", "Heart", "Star", "Custom"]


CUSTOM_MASKS = set(MASKS) - {"None"}


MASK_DEFAULT = {"cx": .5, "cy": .5, "w": .6, "h": .6, "rot": 0.0, "round": 0.0, "invert": False, "pts": []}


def _mask_shape(c):
    d = c.get("mask_shape")
    if not isinstance(d, dict): d = {}; c["mask_shape"] = d
    for k, v in MASK_DEFAULT.items(): d.setdefault(k, copy.deepcopy(v))
    return d


def mask_polygon(shape, ms, iw, ih):
    cx, cy = ms["cx"] * iw, ms["cy"] * ih
    a, b = max(1.0, ms["w"] * iw / 2), max(1.0, ms["h"] * ih / 2)
    if shape == "Custom":
        pts = ms.get("pts") or []
        return np.array([[x * iw, y * ih] for x, y in pts], np.float32) if len(pts) >= 3 else None
    if shape == "Circle":
        t = np.linspace(0, 2 * np.pi, 96, endpoint=False); P = np.stack([np.cos(t) * a, np.sin(t) * b], 1)
    elif shape == "Rect":
        rr = min(a, b) * float(ms.get("round", 0))
        if rr < 1: P = np.array([[-a, -b], [a, -b], [a, b], [-a, b]], np.float32)
        else:
            P = []
            for sx, sy, st in ((1, -1, -90), (1, 1, 0), (-1, 1, 90), (-1, -1, 180)):
                ccx, ccy = sx * (a - rr), sy * (b - rr)
                for k in range(9):
                    ang = math.radians(st + k * 90 / 8); P.append([ccx + rr * math.cos(ang), ccy + rr * math.sin(ang)])
            P = np.array(P, np.float32)
    elif shape == "Heart":
        t = np.linspace(0, 2 * np.pi, 120, endpoint=False)
        x = 16 * np.sin(t) ** 3; y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        P = np.stack([x / 16 * a, (y - 2.6) / 14.4 * b], 1)
    elif shape == "Star":
        k = np.arange(10); ang = -np.pi / 2 + k * np.pi / 5; r = np.where(k % 2 == 0, 1.0, 0.42)
        P = np.stack([np.cos(ang) * r * a, np.sin(ang) * r * b], 1)
    else: return None
    th = math.radians(ms.get("rot", 0)); R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]], np.float32)
    return np.asarray(P, np.float32) @ R.T + np.array([cx, cy], np.float32)


def mask_alpha(shape, ms, iw, ih, feather):
    if shape in ("Split", "Filmstrip"):
        cx, cy = ms["cx"] * iw, ms["cy"] * ih; th = math.radians(ms.get("rot", 0))
        nx, ny = -math.sin(th), math.cos(th)
        yy = np.arange(ih, dtype=np.float32)[:, None]; xx = np.arange(iw, dtype=np.float32)[None, :]
        d = (xx - cx) * nx + (yy - cy) * ny
        m = ((d >= 0) if shape == "Split" else (np.abs(d) <= ms["h"] * ih / 2)).astype(np.uint8) * 255
    else:
        poly = mask_polygon(shape, ms, iw, ih)
        if poly is None: return None
        m = np.zeros((ih, iw), np.uint8)
        cv2.fillPoly(m, [np.round(poly * 16).astype(np.int32)], 255, cv2.LINE_AA, shift=4)
    f = float(feather or 0)
    if f > 0: m = cv2.GaussianBlur(m, (0, 0), max(.5, f / 100 * .12 * min(iw, ih)))
    if ms.get("invert"): m = 255 - m
    return m


def _blend(mode, b, t):
    if mode == "add": return np.minimum(b + t, 1)
    if mode == "multiply": return b * t
    if mode == "screen": return 1 - (1 - b) * (1 - t)
    if mode == "overlay": return np.where(b < .5, 2 * b * t, 1 - 2 * (1 - b) * (1 - t))
    if mode == "soft light": return (1 - 2 * t) * b * b + 2 * t * b
    if mode == "darken": return np.minimum(b, t)
    if mode == "lighten": return np.maximum(b, t)
    if mode == "difference": return np.abs(b - t)
    if mode == "subtract": return np.maximum(b - t, 0)
    return t


class Renderer:
    def __init__(self, pool):
        self.pool = pool; self.lut_cache = {}
        # Preview cache keeps repeated scrubbing from decoding / compositing the same frame again (bounded for RAM).
        self.preview_cache = OrderedDict(); self.preview_cache_limit = 24
        self._src_lock = threading.RLock(); self._cache_lock = threading.RLock(); self._mask_cache = OrderedDict()
        pool.make_compound = lambda c: CompoundSource(c, self)      # lets the pool build compound-clip sources
    def clear_preview_cache(self):
        with self._cache_lock: self.preview_cache.clear()
    def render_cached(self, proj, t, q, fast=False):
        fps = max(1, proj.fps); frame = int(round(max(0.0, t) * fps))
        try: sig = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", None)], sort_keys=True, default=str))
        except Exception: sig = id(proj)
        key = (sig, frame, round(float(q), 3), bool(fast))
        with self._cache_lock:
            hit = self.preview_cache.get(key)
            if hit is not None: self.preview_cache.move_to_end(key); return hit.copy()
        img = self.render(proj, frame / fps, q, fast)
        with self._cache_lock:
            self.preview_cache[key] = img.copy()
            while len(self.preview_cache) > self.preview_cache_limit: self.preview_cache.popitem(last=False)
        return img
    def base_size(self, proj, c):
        if c["kind"] == "text":
            img = render_text(c, 1.0); return img.shape[1], img.shape[0]
        src = self.pool.get(c)
        if not src or not src.w: return None
        f = min(proj.w / src.w, proj.h / src.h); return src.w * f, src.h * f
    def geometry(self, proj, c, t):
        c = node_apply(proj, c, t, ui=True)
        bs = self.base_size(proj, c)
        if not bs: return None
        lt = t - c["start"]; x, y, sx, sy, rot = (prop_at(c, k, lt) for k in ("x", "y", "sx", "sy", "rot"))
        hw, hh = bs[0] * sx / 200, bs[1] * sy / 200; th = math.radians(rot); cs, sn = math.cos(th), math.sin(th)
        cx, cy = proj.w / 2 + x, proj.h / 2 + y
        return [(cx + lx * cs - ly * sn, cy + lx * sn + ly * cs) for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
    def render(self, proj, t, q, fast=False):
        W, H = max(2, int(round(proj.w * q))), max(2, int(round(proj.h * q)))
        bg = QColor(proj.bg); canvas = np.empty((H, W, 3), np.float32)
        canvas[:] = (bg.blueF(), bg.greenF(), bg.redF())
        for tr in reversed([tr for tr in proj.tracks if tr["kind"] == "video"]):
            if tr["hidden"]: continue
            for c in proj.clips:
                if c["track"] == tr["id"] and c["start"] <= t < c["start"] + c["dur"]:
                    try: self.composite(canvas, proj, node_apply(proj, c, t), t, q, fast)
                    except Exception as ex: print("composite error:", ex)
        return (np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8)
    def composite(self, canvas, proj, c, t, q, fast):
        lt = t - c["start"]; op = prop_at(c, "opacity", lt) / 100
        sx, sy = prop_at(c, "sx", lt), prop_at(c, "sy", lt)
        if op <= 0.001 or abs(sx) < .01 or abs(sy) < .01: return
        bs = self.base_size(proj, c)
        if not bs: return
        bw, bh = bs; ms = max(abs(sx), abs(sy)) / 100
        if c["kind"] == "text":
            img = render_text(c, min(4.0, max(0.1, math.ceil(q * ms * 4) / 4)))
        else:
            src = self.pool.get(c)
            if not src: return
            ds = min(1.0, max(0.125, math.ceil(bw * q * ms / src.w * 4) / 4))
            img = src.frame(c["inp"] + lt if c["kind"] != "image" else 0, ds)
        # effect layers (colour, blur, key ...) and the clip mask act on the source image before it is transformed
        img = self.apply_color(c, img, k=img.shape[1] / max(1.0, float(bw)), lt=lt, fast=fast)
        ih, iw = img.shape[:2]; H, W = canvas.shape[:2]
        kx, ky = bw * q * sx / 100 / iw, bh * q * sy / 100 / ih
        th = math.radians(prop_at(c, "rot", lt)); cs, sn = math.cos(th), math.sin(th)
        cx, cy = (proj.w / 2 + prop_at(c, "x", lt)) * q, (proj.h / 2 + prop_at(c, "y", lt)) * q
        a00, a01, a10, a11 = cs * kx, -sn * ky, sn * kx, cs * ky
        M = np.array([[a00, a01, cx - a00 * iw / 2 - a01 * ih / 2], [a10, a11, cy - a10 * iw / 2 - a11 * ih / 2]], np.float32)
        corn = M @ np.array([[0, iw, iw, 0], [0, 0, ih, ih], [1, 1, 1, 1]], np.float32)
        x0, x1 = max(0, int(math.floor(corn[0].min()))), min(W, int(math.ceil(corn[0].max())))
        y0, y1 = max(0, int(math.floor(corn[1].min()))), min(H, int(math.ceil(corn[1].max())))
        if x1 <= x0 or y1 <= y0: return
        M[0, 2] -= x0; M[1, 2] -= y0
        layer = cv2.warpAffine(img, M, (x1 - x0, y1 - y0), flags=cv2.INTER_NEAREST if fast else cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        top = layer[..., :3].astype(np.float32) * (1 / 255); a = layer[..., 3:4].astype(np.float32) * (op / 255)
        base = canvas[y0:y1, x0:x1]
        res = top if c["blend"] == "normal" else _blend(c["blend"], base, top)
        base += (res - base) * a
    def apply_color(self, c, img, k=1.0, lt=0.0, fast=False):
        img = apply_effects(c, img, k, lt, fast)
        sh = c.get("mask", "None")
        if sh not in CUSTOM_MASKS or img is None or img.ndim != 3 or img.shape[2] != 4: return img
        ms = dict(MASK_DEFAULT, **(c.get("mask_shape") or {})); ih, iw = img.shape[:2]; fe = c.get("mask_feather", 0)
        cache = self._mask_cache
        key = (sh, json.dumps(ms, sort_keys=True), iw, ih, fe); m = cache.get(key)
        if m is None:
            m = mask_alpha(sh, ms, iw, ih, fe); cache[key] = m
            while len(cache) > 24: cache.popitem(last=False)
        if m is None: return img
        img = img.copy()
        if img.dtype == np.uint8: img[..., 3] = (img[..., 3].astype(np.uint16) * m // 255).astype(np.uint8)
        else: img[..., 3] *= (m.astype(img.dtype) / 255)
        return img


class CompoundSource:
    def __init__(self, c, renderer):
        self.c = c; self.r = renderer
        self.w = int(c.get("cw", 1920)); self.h = int(c.get("chh", 1080)); self.fps = c.get("cfps", 30); self.n = 10 ** 9
    def frame(self, t, ds=1.0):
        p = Project("compound", self.w, self.h, self.fps)
        p.clips = self.c.get("children", []); p.tracks = self.c.get("subtracks", []); p.bg = "#000000"
        return cv2.cvtColor(self.r.render(p, float(t), ds, False), cv2.COLOR_BGR2BGRA)


def _snapshot(proj):
    p = copy.copy(proj); p.clips = copy.deepcopy(proj.clips); p.tracks = copy.deepcopy(proj.tracks); return p


class RenderWorker(QThread):
    ready = Signal(object)
    def __init__(self, renderer):
        super().__init__(); self.r = renderer; self.cv = threading.Condition(); self.job = None; self.alive = True
    def submit(self, proj, t, q, fast):
        snap = _snapshot(proj)
        with self.cv: self.job = (snap, t, q, fast); self.cv.notify()
    def stop(self):
        with self.cv: self.alive = False; self.cv.notify()
        self.wait(2000)
    def run(self):
        while True:
            with self.cv:
                while self.job is None and self.alive: self.cv.wait()
                if not self.alive: return
                job, self.job = self.job, None
            snap, t, q, fast = job
            try:
                with self.r._src_lock: fr = self.r.render_cached(snap, t, q, fast)
                self.ready.emit(np_to_qimage(fr))
            except Exception as ex: print("preview render error:", ex)

"""Frame renderer: compositing, masks, text, compound clips and the background preview worker."""
from ..shared.deps import *
from ..shared.core import *
from .nodegraph import *
from .effects import apply_effects, spill_margin
from .fastcomp import blend_into, blend_mode, visible_rect, resize_part, covers_canvas, to_cv_matrix
from .gpu import GPU
from .perf import lower_thread_priority


_text_cache = OrderedDict()


def _mc37_composite_path(path, reason=None):
    """Log only path transitions, so diagnostics reveal the actual compositor without flooding the log."""
    try:
        prev = getattr(_TLS, "_mc37_composite_path", None)
        key = (path, reason)
        if prev != key:
            from .debug_trace import trace_event
            trace_event("compositor_path", path=path, reason=reason,
                        selected_mode=getattr(GPU, "mode", "unknown"),
                        gpu_status=getattr(GPU, "status", "unknown"))
            _TLS._mc37_composite_path = key
    except Exception:
        pass


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


MASKS = ["None", "Split", "Filmstrip", "Circle", "Rect", "Heart", "Star", "Custom", "Image"]


CUSTOM_MASKS = set(MASKS) - {"None"}


MASK_DEFAULT = {"cx": .5, "cy": .5, "w": .6, "h": .6, "rot": 0.0, "round": 0.0, "invert": False, "pts": [], "img": "", "channel": "alpha"}


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


IMG_MASK_CACHE = OrderedDict()


def _image_mask(path, iw, ih, channel="alpha"):
    """Mask from an image of the project: its alpha (transparency) or its brightness, resized to the clip frame."""
    if not path or not os.path.isfile(path): return None
    key = (path, os.path.getmtime(path))
    img = IMG_MASK_CACHE.get(key)
    if img is None:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None: return None
        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        if img.dtype != np.uint8: img = (img / 256).astype(np.uint8)
        IMG_MASK_CACHE[key] = img
        while len(IMG_MASK_CACHE) > 6: IMG_MASK_CACHE.popitem(last=False)
    src = img[..., 3] if channel == "alpha" else cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY)
    return cv2.resize(src, (max(1, int(iw)), max(1, int(ih))), interpolation=cv2.INTER_LINEAR)


def layer_list(c):
    """The base mask of the clip followed by its extra mask layers (each: mode add / subtract / intersect)."""
    base = {"mode": "add", "mask": c.get("mask", "None"), "mask_shape": c.get("mask_shape") or {}, "mask_feather": c.get("mask_feather", 0)}
    return [base] + [L for L in (c.get("mask_layers") or []) if isinstance(L, dict)]


def clip_has_mask(c):
    return any(L.get("mask", "None") in CUSTOM_MASKS for L in layer_list(c))


def combined_mask(c, iw, ih):
    """All layers combined into one 0..255 mask (None when there is nothing to show)."""
    acc = None
    for L in layer_list(c):
        if L.get("mask", "None") not in CUSTOM_MASKS: continue
        ms = dict(MASK_DEFAULT, **(L.get("mask_shape") or {}))
        m = mask_alpha(L["mask"], ms, iw, ih, L.get("mask_feather", 0))
        if m is None: continue
        f = m.astype(np.float32) * (1.0 / 255); mode = L.get("mode", "add")
        if acc is None:
            if mode != "add": continue          # nothing to subtract from yet
            acc = f
        elif mode == "subtract": acc = acc * (1.0 - f)
        elif mode == "intersect": acc = acc * f
        else: acc = acc + f - acc * f
    if acc is None: return None
    return np.clip(acc * 255 + .5, 0, 255).astype(np.uint8)


def mask_alpha(shape, ms, iw, ih, feather):
    if shape == "Image":
        m = _image_mask(ms.get("img", ""), iw, ih, ms.get("channel", "alpha"))
        if m is None: return None
    elif shape in ("Split", "Filmstrip"):
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


_TLS = threading.local()      # .preview = True on the preview thread (only that thread may use the GPU); .depth = render() nesting


class Renderer:
    def __init__(self, pool):
        self.pool = pool; self.lut_cache = {}; self.version = 0   # bumped on every project change (see clear_preview_cache)
        # Rendered frames are kept for repeated scrubbing; the limit is in bytes (Settings -> Preview RAM cache).
        self.preview_cache = OrderedDict(); self.preview_cache_bytes = 300e6; self._pc_bytes = 0
        self._fx_cache = OrderedDict(); self._fx_bytes = 0; self._fx_lock = threading.Lock()
        self._src_lock = threading.RLock(); self._cache_lock = threading.RLock(); self._mask_cache = OrderedDict()
        pool.make_compound = lambda c: CompoundSource(c, self)      # lets the pool build compound-clip sources
    def clear_preview_cache(self):
        self.version += 1   # every edit calls this, so the version tells the preview when the project changed
        with self._cache_lock:
            self.preview_cache.clear()
            self._pc_bytes = 0
        # Effect outputs have their own cache separate from preview frames. Clear it too
        # on edits so changing/adding/removing effect keyframes cannot leave an old
        # processed frame visible during scrubbing or playback.
        fx_lock = getattr(self, "_fx_lock", None)
        if fx_lock is not None:
            with fx_lock:
                self._fx_cache.clear()
                self._fx_bytes = 0
        # Mask shapes are cached separately; clear them too so edits to mask
        # controls (position, feather, invert, etc.) appear in the preview at once.
        self._mask_cache.clear()
    def render_cached(self, proj, t, q, fast=False, ver=None, fp=None):
        fps = max(1, proj.fps); frame = int(round(max(0.0, t) * fps))
        # The frame key is the project content (a fingerprint of everything that is drawn) plus the version.
        if fp is None:
            try: fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", None)], sort_keys=True, default=str))
            except Exception: fp = id(proj)
        sig = (fp, self.version if ver is None else ver)
        key = (sig, frame, round(float(q), 3), bool(fast))
        with self._cache_lock:
            hit = self.preview_cache.get(key)
            if hit is not None: self.preview_cache.move_to_end(key); return hit
        img = self.render(proj, frame / fps, q, fast)
        with self._cache_lock:
            self.preview_cache[key] = img; self._pc_bytes += img.nbytes
            while self._pc_bytes > self.preview_cache_bytes and len(self.preview_cache) > 1:
                self._pc_bytes -= self.preview_cache.popitem(last=False)[1].nbytes
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

    # ---------------------------------------------------------------- planning (cheap: no decoding)
    def _plan(self, proj, c, t, q):
        """Where and how a clip is drawn at time t: size, place, rotation, opacity. None when nothing is drawn."""
        lt = t - c["start"]; op = prop_at(c, "opacity", lt) / 100
        sx, sy = prop_at(c, "sx", lt), prop_at(c, "sy", lt)
        if op <= 0.001 or abs(sx) < .01 or abs(sy) < .01: return None
        bs = self.base_size(proj, c)
        if not bs: return None
        bw, bh = bs
        return {"c": c, "lt": lt, "op": op, "sx": sx, "sy": sy, "bw": bw, "bh": bh, "ms": max(abs(sx), abs(sy)) / 100,
                "rot": prop_at(c, "rot", lt), "cx": (proj.w / 2 + prop_at(c, "x", lt)) * q, "cy": (proj.h / 2 + prop_at(c, "y", lt)) * q,
                "dw": bw * q * abs(sx) / 100, "dh": bh * q * abs(sy) / 100, "W": max(2, int(round(proj.w * q))), "H": max(2, int(round(proj.h * q)))}
    @staticmethod
    def _hides_everything_below(p, W, H):
        """True when this layer is opaque and covers the whole picture, so the layers under it never need to be decoded."""
        c = p["c"]
        if c["kind"] != "video" or p["op"] < 0.999 or c.get("blend", "normal") != "normal": return False      # a compound clip may have transparent parts
        if c.get("effects") or clip_has_mask(c): return False
        return covers_canvas(p["cx"], p["cy"], p["dw"], p["dh"], W, H, p["rot"])
    def _plans(self, proj, t, q, W, H):
        plans = []
        # Build a per-track index of clips that are active at time t so we do
        # one pass over proj.clips instead of one pass per visible track.
        by_track = {}
        for c in proj.clips:
            if c["start"] <= t < c["start"] + c["dur"]:
                by_track.setdefault(c["track"], []).append(c)
        for tr in reversed([tr for tr in proj.tracks if tr["kind"] == "video"]):
            if tr["hidden"]: continue
            for c in by_track.get(tr["id"], ()):
                try:
                    p = self._plan(proj, node_apply(proj, c, t), t, q)
                    if p: plans.append(p)
                except Exception as ex: print("composite error:", ex)
        for i in range(len(plans) - 1, -1, -1):
            if self._hides_everything_below(plans[i], W, H): return plans[i:]
        return plans

    # ---------------------------------------------------------------- the clip's picture
    def _layer_image(self, p, q, fast, gpu=False):
        """(picture, opaque). The picture is BGR when it is fully opaque, otherwise BGRA. Video without effects is used as it
        comes from the decoder (no resize, no copy); the one resize happens when the layer is placed."""
        c = p["c"]; kind = c["kind"]; lt = p["lt"]; has_fx = bool(c.get("effects")) or clip_has_mask(c)
        if kind == "text":
            img = render_text(c, min(4.0, max(0.1, math.ceil(q * p["ms"] * 4) / 4)))
        else:
            src = self.pool.get(c)
            if not src: return None, False
            if kind == "video" and not has_fx and not gpu: return src.raw_frame(src_time(c, lt)), True
            ds = min(1.0, max(0.125, math.ceil(p["bw"] * q * p["ms"] / src.w * 4) / 4))
            ts = src_time(c, lt) if kind != "image" else 0
            if not has_fx and not gpu:
                if kind == "compound": return src.frame_auto(ts, ds)
                if kind == "image" and getattr(src, "opaque", False): return src.frame_bgr(ds), True
            if has_fx and kind != "compound" and self.live_play and getattr(_TLS, "preview", False) and CFG.get("fx_adapt", True):
                s = self._fx_scale(c)
                if s < 0.999: ds = max(0.125, math.floor(ds * s * 8) / 8.0)       # Patch 40: the effect runs on fewer pixels, the placement scales it up
            img = src.frame(ts, ds)
        if has_fx:
            m = spill_margin(c)
            if m:       # an effect may spill outside the media: the picture gets an empty border that the effects can fill
                ih, iw = img.shape[:2]; mx, my = self._spill_fractions(p, m); px, py = int(round(iw * mx)), int(round(ih * my)); big = np.zeros((ih + 2 * py, iw + 2 * px, 4), np.uint8)
                if img.ndim == 3 and img.shape[2] == 3: big[py:py + ih, px:px + iw, :3] = img; big[py:py + ih, px:px + iw, 3] = 255
                else: big[py:py + ih, px:px + iw] = img
                bw0 = p.setdefault("bw0", p["bw"]); bh0 = p.setdefault("bh0", p["bh"]); p["bw"] = bw0 * big.shape[1] / iw; p["bh"] = bh0 * big.shape[0] / ih
                return self._effects_cached(c, big, p, fast, (px, py, px + iw, py + ih)), False
            if "bw0" in p: p["bw"], p["bh"] = p["bw0"], p["bh0"]
            img = self._effects_cached(c, img, p, fast)
        return img, False
    live_play = False         # True while the preview plays or a slider moves (set by the app); the export renderer never sets it
    @staticmethod
    def _spill_fractions(p, m):
        """How far a spilling effect may draw on each side, as a part of the media size: at least `m`, and as far as the edge of the
        picture frame (it is not visible beyond), within a pixel budget so a small media does not make a huge layer."""
        W, H, dw, dh = p.get("W"), p.get("H"), p.get("dw", 0), p.get("dh", 0)
        if not W or dw < 1 or dh < 1: return m, m
        cx, cy = p["cx"], p["cy"]
        if abs(p.get("rot", 0)) > 0.01: far = math.hypot(max(cx, W - cx), max(cy, H - cy)); hx = hy = far
        else: hx, hy = max(cx, W - cx), max(cy, H - cy)
        fx, fy = max(m, (hx - dw / 2) / dw), max(m, (hy - dh / 2) / dh)
        cap = max(1.3 * W * H / (dw * dh), (1 + 2 * m) ** 2); s = 1.0      # Patch 46: about the size of the picture frame at most
        for _ in range(12):
            mx, my = m + (fx - m) * s, m + (fy - m) * s
            if (1 + 2 * mx) * (1 + 2 * my) <= cap: break
            s *= 0.8
        return mx, my
    def _fx_scale(self, c):
        st = self.__dict__.setdefault("_fx_s", {}).get(c["id"]); return st["s"] if st else 1.0
    def _fx_note(self, cid, ms):
        """Adaptive effect resolution: a clip whose effects are slower than the budget gets fewer pixels while playing (down to 1/16),
        and gets them back when they are fast enough. Standing still, everything is drawn in full."""
        d = self.__dict__.setdefault("_fx_s", {}); st = d.get(cid) or {"s": 1.0, "ema": None}
        e = ms if st["ema"] is None else st["ema"] * 0.6 + ms * 0.4; st["ema"] = e; tgt = float(CFG.get("fx_budget_ms", 8.0))
        if e > tgt * 1.3 and st["s"] > 0.25: st["s"] = max(0.25, st["s"] * max(0.5, min(0.9, (tgt / e) ** 0.5))); st["ema"] = None      # pixels ~ s^2: aim at the budget at once
        elif e < tgt * 0.45 and st["s"] < 1.0: st["s"] = min(1.0, st["s"] * 1.2); st["ema"] = None
        d[cid] = st
    def _effects_cached(self, c, img, p, fast, inner=None):
        """Effects and masks act on the picture before it is placed. The result is kept for the same clip, effects and time,
        so moving or fading a clip that has effects does not compute the effects again."""
        lt = p["lt"]; k = img.shape[1] / max(1.0, float(p["bw"]))
        if c["kind"] in ("compound",): return self.apply_color(c, img, k=k, lt=lt, fast=fast)
        # Build a cache key.  json.dumps is accurate but slow for clips with many
        # effects; use the renderer version (bumped on every edit) as an extra
        # discriminator so we can skip re-serialising when nothing changed.
        sig = json.dumps([c.get("effects"), c.get("mask"), c.get("mask_shape"), c.get("mask_feather"), c.get("mask_layers"),
                          (c.get("text"), c.get("font"), c.get("fsize"), c.get("tcolor"), c.get("stroke"), c.get("scolor"), c.get("bold")) if c["kind"] == "text" else None],
                         sort_keys=True, default=str)
        key = (c["id"], c.get("path"), round(src_time(c, lt), 4), round(lt, 4), sig, img.shape, bool(fast), inner)
        with self._fx_lock:
            hit = self._fx_cache.get(key)
            if hit is not None: self._fx_cache.move_to_end(key); return hit
        t0 = time.perf_counter(); out = self.apply_color(c, img, k=k, lt=lt, fast=fast, inner=inner)
        if self.live_play and getattr(_TLS, "preview", False): self._fx_note(c["id"], (time.perf_counter() - t0) * 1000.0)
        if out is not None:
            with self._fx_lock:
                self._fx_cache[key] = out; self._fx_bytes += out.nbytes
                while (len(self._fx_cache) > 32 or self._fx_bytes > 200e6) and len(self._fx_cache) > 1:
                    self._fx_bytes -= self._fx_cache.popitem(last=False)[1].nbytes
        return out
    @staticmethod
    def _matrix(p, q, iw, ih):
        kx, ky = p["bw"] * q * p["sx"] / 100 / iw, p["bh"] * q * p["sy"] / 100 / ih
        th = math.radians(p["rot"]); cs, sn = math.cos(th), math.sin(th)
        a00, a01, a10, a11 = cs * kx, -sn * ky, sn * kx, cs * ky
        return np.array([[a00, a01, p["cx"] - a00 * iw / 2 - a01 * ih / 2], [a10, a11, p["cy"] - a10 * iw / 2 - a11 * ih / 2]], np.float32)

    # ---------------------------------------------------------------- drawing on the CPU
    @staticmethod
    def _blend_roi(roi, bgr, alpha, op, blend):
        if blend == "normal": blend_into(roi, bgr, alpha, op); return
        # All non-normal modes now use the fast uint8/uint16 path in fastcomp.blend_mode
        # (2-3x faster than the old float32 conversion for most modes).
        blend_mode(roi, bgr, alpha, op, blend)
    def _draw_cpu(self, canvas, p, q, fast, precise):
        img, opaque = self._layer_image(p, q, fast)
        if img is None: return
        H, W = canvas.shape[:2]; c = p["c"]; ih, iw = img.shape[:2]
        if abs(p["rot"]) <= 0.01 and not precise:
            # No rotation: resize only the visible part, once, straight to its final size.
            r = visible_rect(p["cx"], p["cy"], p["dw"], p["dh"], W, H)
            if r is None: return
            x0, y0, x1, y1, u0, v0, u1, v1 = r
            if p["sx"] < 0: u0, u1 = 1 - u1, 1 - u0
            if p["sy"] < 0: v0, v1 = 1 - v1, 1 - v0
            part = resize_part(img, u0, v0, u1, v1, x1 - x0, y1 - y0, fast)
            if p["sx"] < 0 and p["sy"] < 0: part = cv2.flip(part, -1)
            elif p["sx"] < 0: part = cv2.flip(part, 1)
            elif p["sy"] < 0: part = cv2.flip(part, 0)
        else:
            M = to_cv_matrix(self._matrix(p, q, iw, ih))
            corn = M @ np.array([[0, iw, iw, 0], [0, 0, ih, ih], [1, 1, 1, 1]], np.float32)
            x0, x1 = max(0, int(math.floor(corn[0].min()))), min(W, int(math.ceil(corn[0].max())))
            y0, y1 = max(0, int(math.floor(corn[1].min()))), min(H, int(math.ceil(corn[1].max())))
            if x1 <= x0 or y1 <= y0: return
            M[0, 2] -= x0; M[1, 2] -= y0
            src = img if img.shape[2] == 4 else cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            part = cv2.warpAffine(src, M, (x1 - x0, y1 - y0), flags=cv2.INTER_NEAREST if fast else cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        alpha = None
        if part.shape[2] == 4:
            a = cv2.extractChannel(part, 3)
            if cv2.countNonZero(cv2.compare(a, 255, cv2.CMP_LT)): alpha = a
            part = cv2.cvtColor(part, cv2.COLOR_BGRA2BGR)
        self._blend_roi(canvas[y0:y1, x0:x1], part, alpha, p["op"], c.get("blend", "normal"))

    # ---------------------------------------------------------------- one frame
    def render(self, proj, t, q, fast=False):
        depth = getattr(_TLS, "depth", 0); _TLS.depth = depth + 1
        try: return self._render(proj, t, q, fast, depth)
        finally: _TLS.depth = depth
    def _render(self, proj, t, q, fast, depth):
        W, H = max(2, int(round(proj.w * q))), max(2, int(round(proj.h * q)))
        bg = QColor(proj.bg); bgr = (bg.blue(), bg.green(), bg.red())
        plans = self._plans(proj, t, q, W, H)
        gpu = GPU if (depth == 0 and getattr(_TLS, "preview", False) and plans) else None
        if gpu is not None and all(p["c"].get("blend", "normal") == "normal" for p in plans):
            try:
                if gpu.usable():
                    layers = []
                    for p in plans:
                        try:
                            img, _ = self._layer_image(p, q, fast, gpu=True)
                            if img is not None: layers.append((img, self._matrix(p, q, img.shape[1], img.shape[0]), p["op"]))
                        except Exception as ex: print("composite error:", ex)
                    out = gpu.draw(layers, W, H, bgr)
                    _mc37_composite_path("gpu", "OpenGL compositing active")
                    return out
                _mc37_composite_path("cpu", gpu.status or "GPU unavailable")
            except Exception as ex:
                gpu.fail("drawing failed: %s" % (ex,))        # the CPU draws this frame and every later one
                _mc37_composite_path("cpu", "GPU draw failed; CPU fallback")
        elif gpu is not None:
            _mc37_composite_path("cpu", "blend mode unsupported by GPU compositor")
        canvas = np.empty((H, W, 3), np.uint8); canvas[:] = bgr
        precise = q >= 0.999 and not fast                      # export and full-quality stills: exact (sub-pixel) placement
        for p in plans:
            try: self._draw_cpu(canvas, p, q, fast, precise)
            except Exception as ex: print("composite error:", ex)
        return canvas
    def apply_color(self, c, img, k=1.0, lt=0.0, fast=False, inner=None):
        img = apply_effects(c, img, k, lt, fast, inner)
        if img is None or img.ndim != 3 or img.shape[2] != 4 or not clip_has_mask(c): return img
        ih, iw = img.shape[:2]; cache = self._mask_cache
        if inner is not None: x0, y0, x1, y1 = inner; iw, ih = x1 - x0, y1 - y0       # the mask belongs to the media, not to the empty border
        key = (json.dumps(layer_list(c), sort_keys=True, default=str), iw, ih); m = cache.get(key)
        if m is None:
            m = combined_mask(c, iw, ih)
            if m is None: return img
            cache[key] = m
            while len(cache) > 48: cache.popitem(last=False)
        img = img.copy()
        if inner is not None: a = img[y0:y1, x0:x1, 3]; a[...] = (a.astype(np.uint16) * m // 255).astype(np.uint8); return img
        if img.dtype == np.uint8: img[..., 3] = (img[..., 3].astype(np.uint16) * m // 255).astype(np.uint8)
        else: img[..., 3] *= (m.astype(img.dtype) / 255)
        return img


class CompoundSource:
    def __init__(self, c, renderer):
        self.c = c; self.r = renderer
        self.w = int(c.get("cw", 1920)); self.h = int(c.get("chh", 1080)); self.fps = c.get("cfps", 30); self.n = 10 ** 9
    def _over(self, t, ds, bg):
        p = Project("compound", self.w, self.h, self.fps)
        p.clips = self.c.get("children", []); p.tracks = self.c.get("subtracks", []); p.bg = bg
        return self.r.render(p, float(t), ds, False)
    def frame_auto(self, t, ds=1.0):
        """(picture, opaque). The compound clip keeps its transparency (Patch 40): it is drawn once over black and once over white;
        where the two differ nothing is drawn there, and the difference tells how transparent it is (exact for normal compositing)."""
        key = (round(float(t), 4), ds); cache = self.__dict__.setdefault("_ac", OrderedDict()); hit = cache.get(key)
        if hit is not None: cache.move_to_end(key); return hit
        a = self._over(t, ds, "#000000"); pd = max(0.125, min(0.25, ds * 0.25))
        tb = self._over(t, pd, "#000000"); tw = self._over(t, pd, "#ffffff")       # Patch 46: a tiny test first; the second full render only if something is transparent
        if float((255.0 - (tw.astype(np.int16) - tb.astype(np.int16)).mean(axis=2)).min()) >= 250.0: res = (a, True)
        else:
            b = self._over(t, ds, "#ffffff"); alpha = np.clip(255.0 - (b.astype(np.int16) - a.astype(np.int16)).mean(axis=2), 0, 255)
            af = np.maximum(alpha / 255.0, 1e-3)[..., None]
            res = (np.dstack([np.clip(a.astype(np.float32) / af, 0, 255).astype(np.uint8), alpha.astype(np.uint8)]), False)
        cache[key] = res
        while len(cache) > 6: cache.popitem(last=False)
        return res
    def frame_bgr(self, t, ds=1.0):
        img, opaque = self.frame_auto(t, ds); return img if opaque else np.ascontiguousarray(img[..., :3])
    def frame(self, t, ds=1.0):
        img, opaque = self.frame_auto(t, ds); return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if opaque else img


def _snapshot(proj):
    p = copy.copy(proj); p.clips = copy.deepcopy(proj.clips); p.tracks = copy.deepcopy(proj.tracks); return p


def frame_to_qimage(fr):
    """The frame as a QImage without copying it (the array is kept alive by the image)."""
    try:
        h, w = fr.shape[:2]
        img = QImage(fr.data, w, h, fr.strides[0], QImage.Format_BGR888)
        img._keep = fr
        return img
    except Exception:
        return np_to_qimage(fr)


class RenderWorker(QThread):
    ready = Signal(object)
    def __init__(self, renderer):
        super().__init__(); self.r = renderer; self.cv = threading.Condition(); self.job = None; self.alive = True; self.last_ms = 0.0; self.done_t = None
    def submit(self, proj, t, q, fast):
        # Only hands the request over. The copy of the project is made by the render thread, never by the GUI thread.
        ver = self.r.version
        with self.cv: self.job = (proj, t, q, fast, ver); self.cv.notify()
    def _snapshot_for(self, live):
        """Reuse the render snapshot while the project's edit-version is unchanged.

        Previously every preview request JSON-serialized the entire project (often twice) just to
        discover that nothing changed. Timeline scrubbing can submit many requests per second, so
        this work caused avoidable CPU spikes. Project edits call clear_preview_cache(), which
        increments Renderer.version; use that existing dirty signal as the fast path. When the
        version changes, retain the content fingerprint check as a safety net and copy only if needed.
        """
        version = self.r.version
        if getattr(self, "_snap_version", None) == version and hasattr(self, "_snap"):
            return self._snap, self._fp
        for _ in range(4):
            try:
                version = self.r.version
                # One JSON round-trip to fingerprint the live project.  Only when
                # the version changed (an edit happened) do we need this check at all;
                # the fast path above already returned when version was unchanged.
                fp = hash(json.dumps([live.clips, live.tracks, live.bg, live.w, live.h, getattr(live, "graph", None)], sort_keys=True, default=str))
                if fp == getattr(self, "_fp", None) and hasattr(self, "_snap"):
                    self._snap_version = version
                    return self._snap, self._fp
                # Content changed: take a deep-copy snapshot.  Reuse the fingerprint
                # we already computed — a second json.dumps of snap would give the same
                # result (snap is a copy of live made right now) and costs extra time.
                snap = _snapshot(live)
                if self.r.version != version:
                    continue    # an edit landed while copying; the snapshot may be mixed
                self._snap, self._fp, self._snap_version = snap, fp, version
                return snap, fp
            except RuntimeError:
                continue                      # the GUI changed the project while it was read: read it again
        return getattr(self, "_snap", live), getattr(self, "_fp", None)
    def stop(self):
        with self.cv: self.alive = False; self.cv.notify()
        self.wait(2000)
    def run(self):
        _TLS.preview = True
        if CFG.get("low_priority", True): lower_thread_priority()
        while True:
            with self.cv:
                while self.job is None and self.alive: self.cv.wait()
                if not self.alive: return
                job, self.job = self.job, None
            live, t, q, fast, ver = job
            snap, fpv = self._snapshot_for(live)
            # Skip rendering when the last emitted frame is already current:
            # same content version, same time and quality.  This avoids a
            # redundant composite when the GUI re-requests the same frame
            # (e.g. after a UI repaint with no timeline change).
            last_key = getattr(self, "_last_key", None)
            cur_key = (ver, fpv, round(t, 4), round(q, 3), bool(fast))
            if cur_key == last_key:
                continue
            try:
                t0 = time.perf_counter()
                with self.r._src_lock: fr = self.r.render_cached(snap, t, q, fast, ver, fpv)
                self.last_ms = (time.perf_counter() - t0) * 1000.0; self.done_t = t
                self._last_key = cur_key
                self.ready.emit(frame_to_qimage(fr))
            except Exception as ex: print("preview render error:", ex)


# MINI CUT PATCH 36 RENDER DIAGNOSTICS
try:
    from .debug_trace import trace_event, trace_timing
    _mc36_orig_render_cached = Renderer.render_cached
    def _mc36_render_cached(self, proj, t, q, fast=False, ver=None, fp=None):
        _mc36_t0 = time.perf_counter()
        _mc36_frame = int(round(max(0.0, float(t)) * max(1, proj.fps)))
        _mc36_key = None
        try:
            _mc36_fp = fp
            if _mc36_fp is None:
                _mc36_fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", None)], sort_keys=True, default=str))
            _mc36_key = ((_mc36_fp, self.version if ver is None else ver), _mc36_frame, round(float(q), 3), bool(fast))
            with self._cache_lock:
                _mc36_hit = _mc36_key in self.preview_cache
        except Exception:
            _mc36_hit = None
        try:
            return _mc36_orig_render_cached(self, proj, t, q, fast, ver, fp)
        finally:
            trace_timing("preview_frame", (time.perf_counter() - _mc36_t0) * 1000.0,
                         cache_hit=_mc36_hit, t=round(float(t), 4), frame=_mc36_frame,
                         q=round(float(q), 3), fast=bool(fast), clips=len(getattr(proj, "clips", [])))
    Renderer.render_cached = _mc36_render_cached

    _mc36_orig_render = Renderer.render
    def _mc36_render(self, proj, t, q, fast=False):
        _mc36_t0 = time.perf_counter()
        try:
            return _mc36_orig_render(self, proj, t, q, fast)
        finally:
            trace_timing("composite_render", (time.perf_counter() - _mc36_t0) * 1000.0,
                         t=round(float(t), 4), q=round(float(q), 3), fast=bool(fast))
    Renderer.render = _mc36_render

    _mc36_orig_submit = RenderWorker.submit
    def _mc36_submit(self, proj, t, q, fast):
        try:
            with self.cv:
                _mc36_replaced = self.job is not None
            if _mc36_replaced:
                trace_event("preview_request_replaced", t=round(float(t), 4), q=round(float(q), 3))
        except Exception: pass
        return _mc36_orig_submit(self, proj, t, q, fast)
    RenderWorker.submit = _mc36_submit

    _mc36_orig_snapshot = RenderWorker._snapshot_for
    def _mc36_snapshot(self, live):
        _mc36_t0 = time.perf_counter()
        try:
            return _mc36_orig_snapshot(self, live)
        finally:
            trace_timing("project_snapshot", (time.perf_counter() - _mc36_t0) * 1000.0,
                         version=getattr(self.r, "version", None), clips=len(getattr(live, "clips", [])))
    RenderWorker._snapshot_for = _mc36_snapshot
except Exception as _mc36_hook_error:
    try: trace_event("instrumentation_error", error=repr(_mc36_hook_error))
    except Exception: pass
# END MINI CUT PATCH 36 RENDER DIAGNOSTICS


# MINI CUT PATCH 39 ADAPTIVE PROXY (baked preview segments). Off by default (Settings); any failure means normal live rendering.
try:
    from . import bake as _mc39_bake
    _mc39_bake.install(Renderer, RenderWorker, _snapshot, _TLS, lower_thread_priority)
except Exception as _mc39_ex:
    print("[bake] not installed:", _mc39_ex)

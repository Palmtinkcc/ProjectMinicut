"""Effect Preview Cache (Patch 32 step 2).

The effect gallery shows every effect on one fixed test card (bright and dark areas, sharp edges, a gradient, colour patches)
instead of on the frame of the timeline.  The finished pictures are kept on disk, so they are shared by all projects and
the gallery opens at once.  A picture is reused only when everything that made it is the same: the effect and its default
parameters, the test card, the size, and the effect source code.  If any of these changes the picture is made again, and
only when its tile is shown.  A missing or damaged file is simply made again; nothing here can stop the program.
"""
import os, json, time, hashlib
import numpy as np
import cv2

CACHE_VER = 1                 # raise it when the way previews are made changes
CARD_W = 200
BASE_W = 1920.0               # the width the effect parameters are meant for (preview k = CARD_W / BASE_W)
MAX_BYTES = 150 * 1024 * 1024
MAX_AGE_DAYS = 60

_STATE = {"dir": None, "code": None, "card": None, "pruned": False}


def cache_dir():
    if _STATE["dir"] is None:
        base = os.path.join(os.path.expanduser("~"), ".minicut")
        try:
            from ..shared.core import APP_DIR; base = APP_DIR
        except Exception: pass
        _STATE["dir"] = os.path.join(base, "fxcache")
    return _STATE["dir"]


def test_card(w=CARD_W):
    """Fixed BGRA test picture. The same bytes every time (no random numbers)."""
    if _STATE["card"] is not None and _STATE["card"].shape[1] == w: return _STATE["card"]
    h = int(round(w * 9 / 16)); img = np.zeros((h, w, 4), np.uint8); img[..., 3] = 255
    xs = np.linspace(0, 1, w, dtype=np.float32)[None, :]; ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    img[..., 0] = (255 * (1 - xs) * (0.4 + 0.6 * ys)).astype(np.uint8)                     # soft colour gradient (background)
    img[..., 1] = (255 * (0.25 + 0.75 * ys) * (0.5 + 0.5 * xs)).astype(np.uint8)
    img[..., 2] = (255 * xs * (1 - 0.5 * ys)).astype(np.uint8)
    s = w / 200.0; S = lambda v: int(round(v * s))
    cv2.rectangle(img, (0, 0), (S(66), h // 2), (235, 235, 235, 255), -1)                  # bright block
    cv2.rectangle(img, (0, h // 2), (S(66), h), (18, 18, 18, 255), -1)                     # dark block
    cv2.circle(img, (S(110), h // 2), max(4, h // 3), (250, 250, 250, 255), -1)            # sharp round edge
    cv2.circle(img, (S(110), h // 2), max(2, h // 6), (30, 30, 200, 255), -1)
    cv2.rectangle(img, (S(150), S(14)), (S(190), S(52)), (40, 200, 40, 255), -1)           # colour patches
    cv2.rectangle(img, (S(158), S(24)), (S(198), S(62)), (220, 120, 20, 255), 2)
    for i in range(6):                                                                     # fine lines (detail)
        x0 = S(8 + i * 9); cv2.line(img, (x0, S(10)), (x0, S(40)), (20, 20, 20, 255) if i % 2 else (240, 240, 240, 255), 1)
    cv2.line(img, (0, h - 1), (w - 1, S(60)), (255, 255, 255, 255), 1, cv2.LINE_AA)
    _STATE["card"] = np.ascontiguousarray(img); return _STATE["card"]


def _code_hash():
    """Hash of the effect source files: when they change, old pictures are not reused."""
    if _STATE["code"] is None:
        here = os.path.dirname(os.path.abspath(__file__)); files = [os.path.join(here, "effects.py")]
        pack = os.path.join(here, "fxpack")
        try: files += [os.path.join(pack, n) for n in sorted(os.listdir(pack)) if n.endswith(".py")]
        except OSError: pass
        try:                                                        # Patch 36: the effects live in minicut/fx/ now
            fxdir = os.path.join(os.path.dirname(here), "fx")
            for d, _, fs in sorted(os.walk(fxdir)):
                files += [os.path.join(d, n) for n in sorted(fs) if n.endswith((".py", ".frag", ".glsl", ".txt", ".json")) and "__pycache__" not in d]
        except OSError: pass
        h = hashlib.sha1()
        for f in files:
            try:
                with open(f, "rb") as fh: h.update(fh.read().replace(b"\r\n", b"\n"))
            except OSError: h.update(b"?")
        _STATE["code"] = h.hexdigest()
    return _STATE["code"]


def effect_sig(typ, spec, defaults):
    """Key of one preview: effect type + its default parameters + test card + size + code version."""
    try: p = json.dumps(defaults, sort_keys=True, default=str)
    except Exception: p = repr(defaults)
    card = hashlib.sha1(test_card().tobytes()).hexdigest()[:12]
    raw = "|".join([str(CACHE_VER), typ, str(spec.get("title", "")), p, card, str(CARD_W), _code_hash()])
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _path(sig): return os.path.join(cache_dir(), sig[:2], sig + ".png")


def load(sig):
    """BGRA picture from the disk cache, or None (missing or damaged file)."""
    p = _path(sig)
    try:
        data = np.fromfile(p, np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    except Exception: return None
    if img is None or img.ndim != 3 or img.shape[2] != 4 or img.shape[1] != CARD_W: return None
    try: os.utime(p)                                   # used now: pruned last
    except OSError: pass
    return img


def save(sig, img):
    """Write atomically (temp file, then rename) so a half-written file is never read."""
    try:
        ok, buf = cv2.imencode(".png", img)
        if not ok: return False
        p = _path(sig); os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp%d" % os.getpid()
        with open(tmp, "wb") as f: f.write(buf.tobytes())
        os.replace(tmp, p); return True
    except Exception: return False


def prune():
    """Once per run: delete old pictures, and the oldest ones when the folder is over its size limit."""
    if _STATE["pruned"]: return
    _STATE["pruned"] = True
    try:
        items = []; now = time.time()
        for d, _, names in os.walk(cache_dir()):
            for n in names:
                f = os.path.join(d, n)
                try: st = os.stat(f)
                except OSError: continue
                if ".tmp" in n and now - st.st_mtime > 3600: os.remove(f); continue
                items.append((st.st_mtime, st.st_size, f))
        items.sort(); total = sum(i[1] for i in items)
        for mt, sz, f in items:
            if total <= MAX_BYTES and now - mt <= MAX_AGE_DAYS * 86400: break
            try: os.remove(f); total -= sz
            except OSError: pass
    except Exception: pass


def render(typ):
    """Make the preview (BGRA) of one effect with its default parameters on the test card. None when it fails."""
    try:
        from .effects import FX, new_effect, apply_effects
        base = test_card()
        out = apply_effects({"effects": [new_effect(typ)], "kind": "video"}, base.copy(), k=base.shape[1] / BASE_W, lt=0.0, fast=True)
        if out is None or out.ndim != 3 or out.shape[1] != base.shape[1]: return None
        if out.shape[2] == 3: out = np.dstack([out, np.full(out.shape[:2], 255, np.uint8)])
        return np.ascontiguousarray(out)
    except Exception as ex:
        print("[fxcache]", typ, ex); return None


def get_preview(typ):
    """(BGRA picture, from_cache). Disk first; otherwise made now and stored. (None, False) if the effect fails."""
    try:
        from .effects import FX, fx_defaults
        sig = effect_sig(typ, FX[typ], fx_defaults(typ))
    except Exception: return render(typ), False
    img = load(sig)
    if img is not None: return img, True
    img = render(typ)
    if img is not None: save(sig, img)
    return img, False

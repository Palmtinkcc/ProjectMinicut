"""Bone2D: a small 2D puppet rig (pictures joined by bones) that is drawn by MiniCut as a media clip.

A rig lives in a ".bone2d" file (JSON, the pictures are inside it as base64 PNG, so one file is the whole character):

    {"format": "bone2d", "version": 1, "name", "w", "h",           # w x h = the picture size of the rig (px)
     "images": {id: {"name", "png"}},
     "parts":  [{"id", "name", "img", "bone", "x", "y", "rot", "sx", "sy", "z", "alpha", "visible"}],
     "bones":  [{"id", "name", "parent", "x", "y", "rot", "len"}],
     "anims":  [{"id", "name", "dur", "loop", "tracks": {bone_id: {"rot"|"x"|"y"|"sx"|"sy": [{"t", "v", "e"}]}},
                 "ptracks": {part_id: {"alpha": [{"t", "v", "e"}]}}}],
     "cfg": {...}}

Space: the origin is the middle of the rig picture, x to the right, y down, angles in degrees (clockwise on screen).
A bone is a joint (its head = the pivot that the parts turn around) with a length (only for drawing). Bone x / y / rot are
relative to the parent bone. An animation stores OFFSETS from the rest pose (x, y, rot) and a scale in % (sx, sy).
A part (picture) is glued to one bone: it keeps its rest place and follows the bone when the bone moves.

This module has no Qt: the export workers use it too."""
import os, re, json, math, copy, base64, threading, uuid
from collections import OrderedDict
import numpy as np
import cv2

from ..shared.core import bezier_ease, new_id, BLENDS as FX_BLENDS      # Patch 48: the blend modes of a picture are the same names as the timeline's
from ..shared import marks as MK

EXT = ".bone2d"
CHANNELS = ("rot", "x", "y", "sx", "sy")
CH_DEFAULT = {"rot": 0.0, "x": 0.0, "y": 0.0, "sx": 100.0, "sy": 100.0}
CH_LABEL = {"rot": "Rotate", "x": "Move X", "y": "Move Y", "sx": "Scale X", "sy": "Scale Y"}
LOOPS = [("Loop", "loop"), ("Play once", "once"), ("Ping-pong", "pingpong")]
CLIP_LOOPS = [("Use the animation's", "")] + LOOPS
DEFAULT_CFG = {"fps": 30, "smooth": True, "bg": "", "default_anim": "",
               "snap_deg": 0.0, "show_names": True, "bone_color": "#ff3b30", "bone_width": 1.0,
               "show_parts": True, "paper": "white", "mesh_density": 5.0, "gpu": True}
DEFAULT_CLIP = {"anim": "", "loop": "", "speed": 100.0, "offset": 0.0}


# ───────────────────────── model ─────────────────────────
def new_anim(name="Animation", dur=2.0, loop="loop"):
    return {"id": new_id(), "name": name, "dur": float(dur), "loop": loop, "tracks": {}, "ptracks": {}}


def new_rig(name="Rig", w=1024, h=1024):
    a = new_anim("Idle")
    cfg = dict(DEFAULT_CFG); cfg["default_anim"] = a["id"]
    return {"format": "bone2d", "version": 1, "name": name, "w": int(w), "h": int(h), "images": {}, "parts": [], "bones": [],
            "anims": [a], "cfg": cfg}


def fix_rig(r):
    """Fill in whatever an old / hand-made file lacks, so the rest of the code can rely on every key. Returns r."""
    r.setdefault("format", "bone2d"); r.setdefault("version", 1); r.setdefault("name", "Rig")
    r["w"] = max(8, int(r.get("w", 1024) or 1024)); r["h"] = max(8, int(r.get("h", 1024) or 1024))
    r.setdefault("images", {}); r.setdefault("parts", []); r.setdefault("bones", []); r.setdefault("anims", []); r.setdefault("groups", [])
    for g in r["groups"]:
        g.setdefault("id", new_id()); g.setdefault("name", "Folder"); g.setdefault("open", True); g.setdefault("hidden", False); g.setdefault("lock", False); g["alpha"] = float(g.get("alpha", 100.0))
    cfg = dict(DEFAULT_CFG); cfg.update(r.get("cfg") or {}); r["cfg"] = cfg
    for b in r["bones"]:
        b.setdefault("id", new_id()); b.setdefault("name", "Bone"); b.setdefault("parent", None); b.setdefault("owner", None); b.setdefault("hidden", False)
        if not isinstance(b.get("links"), list): b["links"] = []
        if not isinstance(b.get("lkids"), list): b["lkids"] = []          # Patch 48: Link has a direction: b["lkids"] = the bones that follow b (b is their mother)
        for k, v in (("x", 0.0), ("y", 0.0), ("rot", 0.0), ("len", 100.0)): b[k] = float(b.get(k, v))
    for p in r["parts"]:
        p.setdefault("id", new_id()); p.setdefault("name", "Part"); p.setdefault("img", ""); p.setdefault("bone", None)
        for k, v in (("x", 0.0), ("y", 0.0), ("rot", 0.0), ("sx", 100.0), ("sy", 100.0), ("alpha", 100.0)): p[k] = float(p.get(k, v))
        p["blend"] = p.get("blend") if p.get("blend") in FX_BLENDS else "normal"; p["clip"] = bool(p.get("clip", False)); p["mask_inv"] = bool(p.get("mask_inv", False)); p.setdefault("mask_part", None)          # Patch 48
        p["z"] = int(p.get("z", 0)); p["visible"] = bool(p.get("visible", True)); p["lock"] = bool(p.get("lock", False)); p.setdefault("color", "#ff3b30"); p.setdefault("group", None)
        m = p.get("mesh")
        if isinstance(m, dict) and m.get("v") and m.get("t") and len(m.get("uv", [])) == len(m["v"]):
            if len(m.get("w") or []) != len(m["v"]): m["w"] = [[] for _ in m["v"]]
        else: p.pop("mesh", None)
    ids = {b["id"] for b in r["bones"]}; pids = {p["id"] for p in r["parts"]}
    for p in r["parts"]:
        if p.get("mask_part") not in pids or p["mask_part"] == p["id"]: p["mask_part"] = None          # a layer mask must be another picture of this rig
    for b in r["bones"]:
        if b.get("owner") not in pids: b["owner"] = None
        b["links"] = [x for x in b["links"] if x in ids and x != b["id"]]
        b["lkids"] = [x for x in b["lkids"] if x in b["links"]]
    if not r["anims"]: r["anims"].append(new_anim("Idle"))
    for a in r["anims"]:
        a.setdefault("id", new_id()); a.setdefault("name", "Animation"); a["dur"] = max(0.05, float(a.get("dur", 2.0)))
        a.setdefault("loop", "loop"); a.setdefault("tracks", {}); a.setdefault("ptracks", {})
        a["markers"] = sorted(round(float(x), 3) for x in (a.get("markers") or []) if isinstance(x, (int, float)))                    # Patch 44: marks, beat grid, guide sound
        a["marker_names"] = {str(k): str(v) for k, v in (a.get("marker_names") or {}).items()}; a["marker_colors"] = {str(k): str(v) for k, v in (a.get("marker_colors") or {}).items()}
        a["beat_grid"] = MK.clean_grid(a.get("beat_grid"))
        if not (isinstance(a.get("audio"), dict) and a["audio"].get("file")): a.pop("audio", None)
        else: a["audio"].update(offset=float(a["audio"].get("offset", 0.0)), gain=float(a["audio"].get("gain", 100.0)), mute=bool(a["audio"].get("mute", False)), dur=float(a["audio"].get("dur", 0.0)))
    if not any(a["id"] == r["cfg"].get("default_anim") for a in r["anims"]): r["cfg"]["default_anim"] = r["anims"][0]["id"]
    return r


def get(lst, i): return next((x for x in lst if x["id"] == i), None)


def anim_of(r, aid):
    return get(r["anims"], aid) or get(r["anims"], r["cfg"].get("default_anim")) or r["anims"][0]


def bone_order(r):
    """Bones with every parent before its children (a broken loop in the file cannot hang this)."""
    by = {b["id"]: b for b in r["bones"]}; out = []; seen = set()
    def visit(b, depth=0):
        if b["id"] in seen or depth > 256: return
        seen.add(b["id"])
        if b.get("parent") in by: visit(by[b["parent"]], depth + 1)
        out.append(b)
    for b in r["bones"]: visit(b)
    return out


def children_of(r, bid): return [b for b in r["bones"] if b.get("parent") == bid]


def descendants(r, bid):
    out = []; stack = [bid]
    while stack:
        x = stack.pop()
        for c in children_of(r, x):
            if c["id"] not in out: out.append(c["id"]); stack.append(c["id"])
    return out


def part_image_size(r, p):
    im = r["images"].get(p.get("img"))
    if not im: return (0, 0)
    d = _decode(im)
    return (d.shape[1], d.shape[0]) if d is not None else (0, 0)


# ───────────────────────── matrices ─────────────────────────
def mat(tx=0.0, ty=0.0, rot=0.0, sx=1.0, sy=1.0):
    """3x3 matrix: scale, then turn (degrees), then move."""
    th = math.radians(rot); c, s = math.cos(th), math.sin(th)
    return np.array([[c * sx, -s * sy, tx], [s * sx, c * sy, ty], [0.0, 0.0, 1.0]], np.float64)


def inv(m): return np.linalg.inv(m)


def apply_pt(m, x, y):
    v = m @ np.array([x, y, 1.0]); return float(v[0]), float(v[1])


def mat_angle(m): return math.degrees(math.atan2(m[1, 0], m[0, 0]))


# ───────────────────────── animation ─────────────────────────
def track_value(keys, t, default):
    if not keys: return default
    if t <= keys[0]["t"]: return keys[0]["v"]
    if t >= keys[-1]["t"]: return keys[-1]["v"]
    for a, b in zip(keys, keys[1:]):
        if a["t"] <= t <= b["t"]:
            span = b["t"] - a["t"]; u = 0.0 if span <= 0 else (t - a["t"]) / span
            return a["v"] + (b["v"] - a["v"]) * bezier_ease(a.get("e", [0, 0, 1, 1]), u)
    return keys[-1]["v"]


def bone_channels(anim, bid, t):
    tr = anim["tracks"].get(bid) or {}
    return {k: track_value(tr.get(k), t, CH_DEFAULT[k]) for k in CHANNELS}


def anim_time(anim, t, loop="", speed=1.0, offset=0.0):
    """Clip time -> time inside the animation, with the loop mode (""= the animation's own) and the playback speed."""
    dur = max(1e-6, anim["dur"]); tt = t * speed + offset; mode = loop or anim.get("loop", "loop")
    if mode == "once": return min(max(tt, 0.0), dur)
    if mode == "pingpong":
        p = tt % (2 * dur); return p if p <= dur else 2 * dur - p
    return tt % dur


def rest_world(r):
    """{bone id: world matrix at rest}."""
    W = {}; by = {b["id"]: b for b in r["bones"]}
    for b in bone_order(r):
        loc = mat(b["x"], b["y"], b["rot"]); par = W.get(b.get("parent")) if b.get("parent") in by else None
        if par is not None: loc[0, 2] = (0.0 if b.get("pat") == "head" else by[b["parent"]]["len"]); loc[1, 2] = 0.0          # Parent: the head joins the tail of the mother
        W[b["id"]] = loc if par is None else par @ loc
    return W


def pose_world(r, anim, t, rest=None, extra=None):
    """{bone id: world matrix} of the pose at animation time t (anim None = the rest pose). extra: {bone id: degrees} added to the rotation (physics)."""
    W = {}; by = {b["id"]: b for b in r["bones"]}
    for b in bone_order(r):
        ch = bone_channels(anim, b["id"], t) if anim else CH_DEFAULT
        ex = extra.get(b["id"], 0.0) if extra else 0.0
        loc = mat(b["x"] + ch["x"], b["y"] + ch["y"], b["rot"] + ch["rot"] + ex, ch["sx"] / 100.0, ch["sy"] / 100.0)
        par = W.get(b.get("parent")) if b.get("parent") in by else None
        if par is not None: loc[0, 2] = (0.0 if b.get("pat") == "head" else by[b["parent"]]["len"]); loc[1, 2] = 0.0
        W[b["id"]] = loc if par is None else par @ loc
    return W


def part_matrix(p, pose, rest):
    """Where the picture of part p sits (rig space, centre of the picture): the bone's move on top of the rest place."""
    base = mat(p["x"], p["y"], p["rot"], p["sx"] / 100.0, p["sy"] / 100.0)
    b = p.get("bone")
    if b and b in pose and b in rest: return pose[b] @ inv(rest[b]) @ base
    return base


def sorted_parts(r): return sorted(r["parts"], key=lambda p: p.get("z", 0))


# ───────────────────────── images ─────────────────────────
_IMG_CACHE = OrderedDict(); _IMG_LOCK = threading.RLock(); _IMG_BYTES = [0]; IMG_BUDGET = 150 * 1024 * 1024      # Patch 45/46: was 700 MB


def _decode(im, cache=True):
    """Premultiplied BGRA uint8 of an image entry (kept in a small cache; cache=False: decoded for one use, not kept)."""
    key = im.get("_k") or im.setdefault("_k", uuid.uuid4().hex)
    with _IMG_LOCK:
        hit = _IMG_CACHE.get(key)
        if hit is not None: _IMG_CACHE.move_to_end(key); return hit
    try: raw = np.frombuffer(base64.b64decode(im["png"]), np.uint8); img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    except Exception: img = None
    if img is None: return None
    if img.dtype != np.uint8: img = (img / 256).astype(np.uint8)
    if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    a = img[..., 3:4].astype(np.uint16)
    img = np.concatenate([((img[..., :3].astype(np.uint16) * a + 127) // 255).astype(np.uint8), img[..., 3:4]], 2)
    if not cache: return img
    with _IMG_LOCK:
        _IMG_CACHE[key] = img; _IMG_BYTES[0] += img.nbytes
        while _IMG_CACHE and (_IMG_BYTES[0] > IMG_BUDGET or len(_IMG_CACHE) > 600) and len(_IMG_CACHE) > 1: _k, _v = _IMG_CACHE.popitem(last=False); _IMG_BYTES[0] -= _v.nbytes
    return img


_MIP = OrderedDict(); _MIP_BYTES = [0]; MIP_BUDGET = 96 * 1024 * 1024


def _mip(im, k):
    """The picture shrunk by 2^k (area average), so a part that is drawn small is not aliased."""
    img = _decode(im)
    if img is None or k <= 0: return img
    key = (im["_k"], k)
    with _IMG_LOCK:
        hit = _MIP.get(key)
        if hit is not None: _MIP.move_to_end(key); return hit
    f = 2 ** k; out = cv2.resize(img, (max(1, img.shape[1] // f), max(1, img.shape[0] // f)), interpolation=cv2.INTER_AREA)
    with _IMG_LOCK:
        _MIP[key] = out; _MIP_BYTES[0] += out.nbytes
        while _MIP and (_MIP_BYTES[0] > MIP_BUDGET or len(_MIP) > 200) and len(_MIP) > 1: _MIP_BYTES[0] -= _MIP.popitem(last=False)[1].nbytes
    return out


def image_entry_array(bgra):
    """A picture entry (PNG inside the rig) from a BGRA uint8 array (straight alpha)."""
    ok, buf = cv2.imencode(".png", bgra)
    return {"name": "layer", "png": base64.b64encode(buf.tobytes()).decode("ascii")}


def image_entry(path):
    """An "images" entry made from a picture file (PNG inside), plus its size. None when the file cannot be read."""
    try: data = np.fromfile(path, np.uint8); img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception: return None
    if img is None: return None
    if img.dtype != np.uint8: img = (img / 256).astype(np.uint8)
    if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    ok, buf = cv2.imencode(".png", img)
    if not ok: return None
    return {"name": os.path.basename(path), "png": base64.b64encode(buf.tobytes()).decode("ascii")}, (img.shape[1], img.shape[0])


# ───────────────────────── mesh & skin weights ─────────────────────────
def _alpha_mask(r, p, grow=0, pad=0):
    """Where the picture is not transparent, grown by `grow` px, on a canvas that is `pad` px larger on every side (so the mesh can reach past the edge)."""
    img = _decode(r["images"][p["img"]]); m = (img[..., 3] > 16).astype(np.uint8) * 255
    if pad > 0: m = cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    if grow > 0: m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    return m


def _triangulate(pts, mask):
    """Delaunay triangles of pts (image px) whose middle lies on the picture. Returns [[i, j, k]]."""
    ih, iw = mask.shape[:2]; sd = cv2.Subdiv2D((0, 0, iw + 2, ih + 2)); key = {}
    for i, (x, y) in enumerate(pts):
        x = float(min(max(x, 0.5), iw + 0.5)); y = float(min(max(y, 0.5), ih + 0.5))
        k = (round(float(np.float32(x)), 1), round(float(np.float32(y)), 1))
        if k in key: continue
        key[k] = i
        try: sd.insert((x, y))
        except cv2.error: pass
    out = []
    for t in sd.getTriangleList():
        idx = []
        for j in range(3):
            k = (round(float(t[2 * j]), 1), round(float(t[2 * j + 1]), 1)); idx.append(key.get(k))
        if None in idx or len(set(idx)) < 3: continue
        P = np.array([pts[i] for i in idx], np.float64); area = 0.5 * abs((P[1, 0] - P[0, 0]) * (P[2, 1] - P[0, 1]) - (P[2, 0] - P[0, 0]) * (P[1, 1] - P[0, 1]))
        if area < 0.5: continue
        cx, cy = int(P[:, 0].mean()), int(P[:, 1].mean())
        if 0 <= cx < iw and 0 <= cy < ih and mask[cy, cx] > 0: out.append(idx)
    return out


def build_mesh(r, p, density=5.0):
    """Auto mesh: points on the outline of the picture (a little outside it, corners kept) and inside it, joined into triangles. density 1..10.
    uv / v are in picture px measured from the centre (edge coordinates: the picture spans -w/2 .. w/2)."""
    img = _decode(r["images"][p["img"]]); ih, iw = img.shape[:2]
    step = max(8.0, max(iw, ih) / (3.0 + 2.2 * float(density)))
    for _ in range(8):
        margin = max(2, int(step * 0.22)); pad = margin + 3; m = _alpha_mask(r, p, margin, pad); pts = []; ph, pw = m.shape[:2]
        cnts, _h = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)       # CCOMP: the edges of holes inside the picture get points too (else a triangle spanning a hole is dropped together with the picture under it)
        for c in cnts:
            if cv2.contourArea(c) < step * step * 0.4: continue
            ap = cv2.approxPolyDP(c, max(1.0, step * 0.06), True)[:, 0, :].astype(np.float64)       # the corners are kept
            for k in range(len(ap)):
                a_, b_ = ap[k], ap[(k + 1) % len(ap)]; n = max(1, int(round(float(np.hypot(*(b_ - a_))) / step)))
                for j in range(n): pts.append(tuple(a_ + (b_ - a_) * (j / n)))
        dist = cv2.distanceTransform(m, cv2.DIST_L2, 3)
        for y in np.arange(pad + step * 0.5, ph - pad, step):
            for x in np.arange(pad + step * 0.5, pw - pad, step):
                if dist[int(y), int(x)] > step * 0.55: pts.append((float(x), float(y)))
        if len(pts) <= 700: break
        step *= 1.25
    if len(pts) < 3:
        pad = 0; m = np.full((ih, iw), 255, np.uint8); pts = [(0.5, 0.5), (iw - 0.5, 0.5), (iw - 0.5, ih - 0.5), (0.5, ih - 0.5)]
    tri = _triangulate(pts, m)
    if not tri:
        pad = 0; pts = [(0.0, 0.0), (iw, 0.0), (iw, ih), (0.0, ih)]; tri = [[0, 1, 2], [0, 2, 3]]
    uv = [[float(x - pad + 0.5 - iw / 2.0), float(y - pad + 0.5 - ih / 2.0)] for x, y in pts] if pad else [[float(x - iw / 2.0), float(y - ih / 2.0)] for x, y in pts]
    return {"uv": uv, "v": copy.deepcopy(uv), "t": tri, "w": [[] for _ in uv]}


def retriangulate(r, p):
    """Join the vertices of the mesh again (after one was added or removed). Weights of kept vertices are kept."""
    m = p["mesh"]; img = _decode(r["images"][p["img"]]); ih, iw = img.shape[:2]; grow = max(2, int(max(iw, ih) * 0.03)); pad = grow + 3
    pts = [(u + iw / 2.0 + pad - 0.5, v + ih / 2.0 + pad - 0.5) for u, v in m["uv"]]; tri = _triangulate(pts, _alpha_mask(r, p, grow, pad))
    if tri: m["t"] = tri


def mesh_add_vertex(r, p, lx, ly):
    """Add a vertex at (lx, ly) (centred picture px). Its weights are copied from the nearest vertex."""
    m = p["mesh"]; uv = np.array(m["uv"]); j = int(np.argmin(((uv - [lx, ly]) ** 2).sum(1)))
    m["uv"].append([lx, ly]); m["v"].append([lx, ly]); m["w"].append(copy.deepcopy(m["w"][j])); retriangulate(r, p)


def mesh_del_vertices(r, p, idx):
    m = p["mesh"]; keep = [i for i in range(len(m["uv"])) if i not in set(idx)]
    if len(keep) < 4: return
    for k in ("uv", "v", "w"): m[k] = [m[k][i] for i in keep]
    retriangulate(r, p)


def seg_dist(pts, a, b):
    """Distance from points (n,2) to the segment a-b."""
    a = np.asarray(a, float); b = np.asarray(b, float); d = b - a; L2 = float(d @ d)
    u = np.zeros(len(pts)) if L2 < 1e-9 else np.clip(((pts - a) @ d) / L2, 0, 1)
    q = a + u[:, None] * d; return np.hypot(*(pts - q).T)


def vertex_world_rest(p, m):
    base = mat(p["x"], p["y"], p["rot"], p["sx"] / 100.0, p["sy"] / 100.0); V = np.array(m["v"], np.float64)
    return (base[:2, :2] @ V.T).T + base[:2, 2]


def auto_weights(r, p, bone_ids=None, sharp=3.0, idx=None):
    """Give every vertex (or only idx) weights from its distance to the bones (the nearest three). sharp: 1 = very soft ... 8 = nearly rigid."""
    m = p["mesh"]; rest = rest_world(r); P = vertex_world_rest(p, m)
    bl = [b for b in r["bones"] if (bone_ids is None or b["id"] in bone_ids) and b.get("owner") in (None, p["id"])]
    if p.get("bone") and (bone_ids is not None) and not any(b["id"] == p["bone"] for b in bl):
        gb = get(r["bones"], p["bone"]); bl = bl + ([gb] if gb else [])
    if not bl: return
    D = np.stack([seg_dist(P, apply_pt(rest[b["id"]], 0, 0), apply_pt(rest[b["id"]], b["len"], 0)) for b in bl], 1)
    W = 1.0 / (D + 6.0) ** float(sharp)
    for i in (range(len(P)) if idx is None else idx):
        o = np.argsort(-W[i])[:3]; ws = W[i][o]; ws = ws / ws.sum()
        m["w"][i] = [[bl[int(k)]["id"], float(w)] for k, w in zip(o, ws) if w > 0.02]
        tot = sum(w for _, w in m["w"][i]); m["w"][i] = [[b, w / tot] for b, w in m["w"][i]]


def set_weight(m, idx, bone_id, value, normalize=False):
    """Give each listed vertex the weight `value` (0..1) for bone_id.
    Patch 49 (Blender style): weights are INDEPENDENT per bone - the other bones keep what they have, so several bones can cover the same place.
    The sum is only made 1 when the picture is drawn (see eff_weights). normalize=True = the old behaviour (the other bones give way, sum stays 1)."""
    for i in idx:
        if not normalize:
            rest_ = [[b, w] for b, w in m["w"][i] if b != bone_id]
            if value > 0.002: rest_.append([bone_id, float(min(1.0, value))])
            m["w"][i] = rest_; continue
        cur = {b: w for b, w in m["w"][i] if b != bone_id}; tot = sum(cur.values())
        if value >= 0.999 or tot < 1e-6: new = {bone_id: 1.0} if value > 0.001 else (cur or {})
        else:
            new = {b: w / tot * (1 - value) for b, w in cur.items()}
            if value > 0.001: new[bone_id] = value
        s_ = sum(new.values()) or 1.0; m["w"][i] = [[b, w / s_] for b, w in new.items() if w / s_ > 0.01]


def paint_weights(m, hits, bone_id, amount, normalize=False):
    """Weight paint: hits = [(vertex, falloff 0..1)]. amount > 0 gives bone_id more weight, < 0 takes it away.
    Patch 49: by default (normalize=False) only bone_id changes - the other bones keep their weights, like Blender with Auto Normalize off,
    so a bone that covers the whole picture does not stop another bone from being painted over it. normalize=True: the other bones give way (sum stays 1)."""
    for i, f in hits:
        w0 = next((w for b, w in m["w"][i] if b == bone_id), 0.0); w1 = max(0.0, min(1.0, w0 + amount * f))
        if abs(w1 - w0) <= 1e-6: continue
        if not normalize:
            keep = [[b, w] for b, w in m["w"][i] if b != bone_id]
            if w1 > 0.002: keep.append([bone_id, w1])
            m["w"][i] = keep; continue
        cur = {b: w for b, w in m["w"][i] if b != bone_id}; tot = sum(cur.values())
        if tot < 1e-6: new = {bone_id: w1}                       # nobody else on this vertex: the weight may go below 1 (the rest follows the picture's own bone), so it can be erased too
        else:
            new = {b: w / tot * (1.0 - w1) for b, w in cur.items()}; new[bone_id] = w1
        m["w"][i] = [[b, w] for b, w in new.items() if w > 0.002]      # 0.002, not 0.01: small brush steps (low strength / edge of the brush) must be able to add up


def normalize_weights(m, idx=None):
    """Make the weights of each vertex (or only idx) add up to 1 (the ratios stay). A vertex without weights is left as it is."""
    for i in (range(len(m["w"])) if idx is None else idx):
        tot = sum(w for _b, w in m["w"][i])
        if tot > 1e-6: m["w"][i] = [[b, w / tot] for b, w in m["w"][i]]


def eff_weights(ws, usable=None):
    """The weights that really deform a vertex: ([(bone, w)], rest). Weights are independent per bone (Blender style); when they add up to more than 1
    they are scaled down to 1 (a vertex weighted 1.0 to two bones follows both half and half). When they add up to less than 1, `rest` (1 - sum) is
    what still follows the picture's own bone. usable(b) -> False drops a bone (hidden / other picture's / missing)."""
    out = [(b, float(w)) for b, w in ws if w > 1e-6 and (usable is None or usable(b))]; tot = sum(w for _b, w in out)
    if tot > 1.0: out = [(b, w / tot) for b, w in out]; tot = 1.0
    return out, max(0.0, 1.0 - tot)


def smooth_weights(m, iters=1):
    """Blend each vertex's weights with its neighbours' (soft joints). Each bone is smoothed on its own (Patch 49: no longer forced to add up to 1)."""
    n = len(m["uv"]); nb = [set() for _ in range(n)]
    for a, b, c in m["t"]:
        nb[a] |= {b, c}; nb[b] |= {a, c}; nb[c] |= {a, b}
    for _ in range(iters):
        new = []
        for i in range(n):
            acc = {}; k_tot = 0.0
            for j in [i] + sorted(nb[i]):
                k = 2.0 if j == i else 1.0; k_tot += k
                for b, w in m["w"][j]: acc[b] = acc.get(b, 0.0) + w * k
            new.append([[b, w / k_tot] for b, w in acc.items() if w / k_tot > 0.002])
        m["w"] = new


def vertex_weight_of(m, i, bone_id): return next((w for b, w in m["w"][i] if b == bone_id), 0.0)


# ───────────────────────── physics ─────────────────────────
PHYS_DEFAULT = {"on": False, "stiff": 50.0, "damp": 40.0, "grav": 20.0}


def phys_bones(r): return [b for b in bone_order(r) if (b.get("phys") or {}).get("on")]


_PH_CACHE = OrderedDict(); _PH_LOCK = threading.RLock(); PH_H = 1.0 / 60.0; PH_CK = 15           # fixed 60 Hz steps from the start of the clip; a checkpoint every 15 steps (0.25 s)


def _phys_sig(r, anim, pb, tmap):
    """What the swing depends on (bones, tracks, the time map). The cache is used only while this stays the same."""
    bones = [(b["id"], b.get("parent"), b["x"], b["y"], b["rot"], b["len"], b.get("pat"), sorted((b.get("phys") or {}).items())) for b in bone_order(r)]
    probe = [round(float(tmap(x)), 6) for x in (0.37, 1.91, 4.73, 9.11)]
    return json.dumps([bones, anim.get("id"), anim.get("dur"), anim.get("loop"), anim.get("tracks"), probe], sort_keys=True, default=str)


def _phys_step(r, pb, anim, tt, st):
    """One 60 Hz step of the swing at clip time tt. st = [th, om, pp, pv] (angle, angular speed, last head position, last head speed), changed in place."""
    th, om, pp, pv = st[:4]; h = PH_H
    pose = pose_world(r, anim, st[4](tt), extra=th)
    for b in pb:
        W = pose[b["id"]]; hp = np.array([W[0, 2], W[1, 2]]); u = W[:2, 0]; nu = float(np.hypot(*u))
        if nu < 1e-9: continue
        u = u / nu; nrm = np.array([-u[1], u[0]]); acc = np.zeros(2); old = pp.get(b["id"])
        if old is not None:
            v = (hp - old) / h; ov = pv.get(b["id"])
            if ov is not None: acc = (v - ov) / h
            pv[b["id"]] = v
        pp[b["id"]] = hp; ph = b["phys"]; wn2 = 15.0 + float(ph.get("stiff", 50)) * 3.0; wn = math.sqrt(wn2); c = 2 * (0.08 + float(ph.get("damp", 40)) / 100.0 * 0.9) * wn
        F = -acc + np.array([0.0, float(ph.get("grav", 20)) / 100.0 * 900.0]); tq = float(F @ nrm) / max(b["len"], 30.0) * 57.2958 * 0.6
        tq = max(-3000.0, min(3000.0, tq)); o2 = om[b["id"]] + (-wn2 * th[b["id"]] - c * om[b["id"]] + tq) * h
        om[b["id"]] = o2; th[b["id"]] = max(-80.0, min(80.0, th[b["id"]] + o2 * h))


def physics_offsets(r, anim, tclip, tmap=None, pre=1.0, h=PH_H):
    """Swing of the bones that have physics: {bone id: degrees}. A spring around the animated pose that is pushed by how fast the
    bone's head is speeding up (it lags behind the body) and by gravity. It is simulated from the START of the clip (clip time 0, at rest)
    in fixed 60 Hz steps, so a swing goes on after the body has stopped moving (damping 0 = it never dies by itself). Checkpoints every
    0.25 s are kept, so playing forward only costs a few steps per frame; the result still depends only on the time, not on what was drawn before
    (preview, scrubbing and export agree). `pre` and `h` are kept only so old callers still work; they are not used any more."""
    pb = phys_bones(r)
    if not pb or anim is None: return None
    tmap = tmap or (lambda tt: anim_time(anim, tt)); T = max(0.0, float(tclip)); n = int(T / PH_H); frac = T / PH_H - n
    sig = _phys_sig(r, anim, pb, tmap)
    with _PH_LOCK:
        ent = _PH_CACHE.get(sig)
        if ent is None:
            ent = _PH_CACHE[sig] = {}
            while len(_PH_CACHE) > 8: _PH_CACHE.popitem(last=False)
        else: _PH_CACHE.move_to_end(sig)
        k = (n // PH_CK) * PH_CK
        while k > 0 and k not in ent: k -= PH_CK
        if k in ent: s0 = ent[k]; th = dict(s0[0]); om = dict(s0[1]); pp = {a: v.copy() for a, v in s0[2].items()}; pv = {a: v.copy() for a, v in s0[3].items()}; i0 = k + 1
        else: th = {b["id"]: 0.0 for b in pb}; om = dict(th); pp = {}; pv = {}; i0 = 0
        st = [th, om, pp, pv, tmap]; prev = dict(th)
        for i in range(i0, n + 2):
            if i == n + 1: prev = dict(th)                      # the angles after step n (the last whole step before tclip)
            _phys_step(r, pb, anim, i * PH_H, st)
            if i % PH_CK == 0 and i not in ent and i <= n: ent[i] = ([dict(th), dict(om), {a: v.copy() for a, v in pp.items()}, {a: v.copy() for a, v in pv.items()}])
        while len(ent) > 4000: ent.pop(next(iter(ent)))
        return {a: prev[a] + (th[a] - prev[a]) * frac for a in th}


# ───────────────────────── drawing ─────────────────────────
def _paint_over(canvas, patch, x0, y0, op):
    """Put a premultiplied picture (float32) on the premultiplied canvas."""
    H, W = canvas.shape[:2]; h, w = patch.shape[:2]
    sx0, sy0 = max(0, -x0), max(0, -y0); x1, y1 = min(W, x0 + w), min(H, y0 + h)
    if x1 <= max(0, x0) or y1 <= max(0, y0): return
    pt = patch[sy0:sy0 + (y1 - max(0, y0)), sx0:sx0 + (x1 - max(0, x0))]
    if op < 0.999: pt = pt * op
    roi = canvas[max(0, y0):y1, max(0, x0):x1]; roi *= (1.0 - pt[..., 3:4] / 255.0); roi += pt


def _skinned_points(r, p, pose, rest):
    m = p["mesh"]; base = mat(p["x"], p["y"], p["rot"], p["sx"] / 100.0, p["sy"] / 100.0); V = np.array(m["v"], np.float64)
    P = np.c_[V, np.ones(len(V))] @ base.T; n = len(V); acc = np.zeros((n, 3)); wsum = np.zeros(n)
    SM = {}
    def sm(b):
        if b not in SM: SM[b] = (pose[b] @ inv(rest[b])) if (b in pose and b in rest) else None
        return SM[b]
    byb = {}; own = {b["id"]: b.get("owner") for b in r["bones"]}; tot = np.zeros(n)
    for i, ws in enumerate(m["w"]):
        for b, w in ws:
            if own.get(b) in (None, p["id"]) and sm(b) is not None: byb.setdefault(b, []).append((i, w)); tot[i] += w
    scl = np.where(tot > 1.0, 1.0 / np.maximum(tot, 1e-9), 1.0)          # Patch 49: independent weights; only a sum above 1 is scaled down (see eff_weights)
    for b, lst in byb.items():
        M = sm(b)
        ii = np.array([i for i, _ in lst]); ww = np.array([w for _, w in lst]) * scl[ii]; acc[ii] += (P[ii] @ M.T) * ww[:, None]; wsum[ii] += ww
    gb = sm(p["bone"]) if p.get("bone") else None; G = (P @ gb.T) if gb is not None else P
    miss = wsum < 0.999
    out = np.where(miss[:, None], acc + G * (1 - wsum)[:, None], acc)
    return out[:, :2]


def _mesh_patch(r, p, pose, rest, S, T, img0, im, flag, W, H):
    """The skinned mesh of a part drawn into a small premultiplied picture: (patch, x0, y0) or None."""
    m = p["mesh"]; ih, iw = img0.shape[:2]; Pw = _skinned_points(r, p, pose, rest)
    Mx = S @ T; D = (Pw @ Mx[:2, :2].T) + Mx[:2, 2]
    x0 = max(0, int(math.floor(D[:, 0].min())) - 2); x1 = min(W, int(math.ceil(D[:, 0].max())) + 2); y0 = max(0, int(math.floor(D[:, 1].min())) - 2); y1 = min(H, int(math.ceil(D[:, 1].max())) + 2)
    if x1 <= x0 or y1 <= y0: return None
    sc = math.sqrt(abs(np.linalg.det((Mx @ mat(p["x"], p["y"], p["rot"], p["sx"] / 100.0, p["sy"] / 100.0))[:2, :2]))); k = 0
    while smooth_ok(flag) and sc * (2 ** (k + 1)) <= 1.0 and k < 6 and min(iw, ih) // (2 ** (k + 1)) >= 2: k += 1
    img = _mip(im, k) if k else img0; f = 2.0 ** k; UV = ((np.array(m["uv"], np.float32) + np.array([iw / 2.0 - 0.5, ih / 2.0 - 0.5], np.float32)) / np.float32(f)).astype(np.float32)
    buf = np.zeros((y1 - y0, x1 - x0, 4), np.uint8); off = np.array([x0, y0], np.float64); Dl = (D - off).astype(np.float32); bh, bw = buf.shape[:2]
    for a, b, c in m["t"]:
        dst = Dl[[a, b, c]]
        tx0 = max(0, int(math.floor(dst[:, 0].min())) - 1); tx1 = min(bw, int(math.ceil(dst[:, 0].max())) + 2); ty0 = max(0, int(math.floor(dst[:, 1].min())) - 1); ty1 = min(bh, int(math.ceil(dst[:, 1].max())) + 2)
        if tx1 <= tx0 or ty1 <= ty0: continue
        d2 = dst - np.array([tx0, ty0], np.float32)
        try: M = cv2.getAffineTransform(UV[[a, b, c]], d2)
        except cv2.error: continue
        w_ = cv2.warpAffine(img, M, (tx1 - tx0, ty1 - ty0), flags=flag, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        mk = np.zeros((ty1 - ty0, tx1 - tx0), np.uint8); q = np.round(d2 * 16).astype(np.int32)
        cv2.fillConvexPoly(mk, q, 255, cv2.LINE_8, 4); cv2.polylines(mk, [q], True, 255, 1, cv2.LINE_8, 4)
        sel = mk > 0; buf[ty0:ty1, tx0:tx1][sel] = w_[sel]
    return buf.astype(np.float32), x0, y0


def smooth_ok(flag): return flag != cv2.INTER_NEAREST


def B_get_mask(r, p):
    """The picture that is the layer mask of p (or None)."""
    mid = p.get("mask_part")
    return get(r["parts"], mid) if (mid and mid != p["id"]) else None


def uses_layer_fx(r):
    """True when a picture of the rig has a blend mode, a clipping mask or a layer mask. Such a rig is drawn by the CPU renderer only (the GPU paths know none of these)."""
    return any((p.get("blend", "normal") != "normal") or p.get("clip") or B_get_mask(r, p) is not None for p in r.get("parts", []))


def _part_patch(r, p, pose, rest, S, T, flag, smooth, W, H):
    """The picture of part p drawn into a small premultiplied float picture, in canvas pixels: (patch, x0, y0) or None. No opacity, no blend."""
    im = r["images"].get(p.get("img"))
    if not im: return None
    img0 = _decode(im)
    if img0 is None: return None
    ih, iw = img0.shape[:2]
    if p.get("mesh"):
        return _mesh_patch(r, p, pose, rest, S, T, img0, im, flag, W, H)
    M = S @ T @ part_matrix(p, pose, rest) @ mat(-iw / 2.0, -ih / 2.0)
    sc = math.sqrt(abs(np.linalg.det(M[:2, :2]))) if abs(np.linalg.det(M[:2, :2])) > 1e-12 else 0.0
    if sc < 1e-4: return None
    k = 0
    while smooth and sc * (2 ** (k + 1)) <= 1.0 and k < 6 and min(iw, ih) // (2 ** (k + 1)) >= 2: k += 1
    img = _mip(im, k) if k else img0
    if k: M = M @ mat(0, 0, 0, 2 ** k, 2 ** k)
    ih2, iw2 = img.shape[:2]
    cs = M @ np.array([[0, iw2, iw2, 0], [0, 0, ih2, ih2], [1, 1, 1, 1]], np.float64)
    x0 = max(0, int(math.floor(cs[0].min())) - 1); x1 = min(W, int(math.ceil(cs[0].max())) + 1)
    y0 = max(0, int(math.floor(cs[1].min())) - 1); y1 = min(H, int(math.ceil(cs[1].max())) + 1)
    if x1 <= x0 or y1 <= y0: return None
    Mo = M.copy(); Mo[0, 2] -= x0; Mo[1, 2] -= y0
    patch = cv2.warpAffine(img, Mo[:2], (x1 - x0, y1 - y0), flags=flag, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)).astype(np.float32)
    return patch, x0, y0


def _region_alpha(src, x0, y0, w, h):
    """The alpha (0..1) of the picture src = (patch, sx0, sy0) over the rectangle x0, y0, w, h of the canvas (0 where src is not). src None = all 0."""
    out = np.zeros((h, w), np.float32)
    if src is None: return out
    pt, sx0, sy0 = src; ph, pw = pt.shape[:2]
    ax0, ay0 = max(x0, sx0), max(y0, sy0); ax1, ay1 = min(x0 + w, sx0 + pw), min(y0 + h, sy0 + ph)
    if ax1 <= ax0 or ay1 <= ay0: return out
    out[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = pt[ay0 - sy0:ay1 - sy0, ax0 - sx0:ax1 - sx0, 3] / 255.0
    return out


def _blend_fn(mode, cb, cs):
    """Separable blend modes on straight colours 0..1 (cb = what is below, cs = the picture)."""
    if mode == "multiply": return cb * cs
    if mode == "screen": return cb + cs - cb * cs
    if mode == "overlay": return np.where(cb <= 0.5, 2.0 * cb * cs, 1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
    if mode == "darken": return np.minimum(cb, cs)
    if mode == "lighten": return np.maximum(cb, cs)
    if mode == "add": return np.minimum(1.0, cb + cs)
    if mode == "difference": return np.abs(cb - cs)
    if mode == "subtract": return np.maximum(0.0, cb - cs)
    if mode == "soft light":
        d = np.where(cb <= 0.25, ((16.0 * cb - 12.0) * cb + 4.0) * cb, np.sqrt(cb))
        return np.where(cs <= 0.5, cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb), cb + (2.0 * cs - 1.0) * (d - cb))
    return cs


def _blend_over(canvas, patch, x0, y0, op, mode):
    """Put a premultiplied picture (float32, 0..255) on the premultiplied canvas with a blend mode (the W3C compositing formula)."""
    H, W = canvas.shape[:2]; h, w = patch.shape[:2]
    sx0, sy0 = max(0, -x0), max(0, -y0); x1, y1 = min(W, x0 + w), min(H, y0 + h)
    if x1 <= max(0, x0) or y1 <= max(0, y0): return
    pt = patch[sy0:sy0 + (y1 - max(0, y0)), sx0:sx0 + (x1 - max(0, x0))] / 255.0
    if op < 0.999: pt = pt * op
    roi = canvas[max(0, y0):y1, max(0, x0):x1]
    cbp = roi[..., :3] / 255.0; ab = roi[..., 3:4] / 255.0; csp = pt[..., :3]; as_ = pt[..., 3:4]
    with np.errstate(divide="ignore", invalid="ignore"):
        cs = np.clip(np.where(as_ > 1e-6, csp / np.maximum(as_, 1e-6), 0.0), 0.0, 1.0); cb = np.clip(np.where(ab > 1e-6, cbp / np.maximum(ab, 1e-6), 0.0), 0.0, 1.0)
    mix = _blend_fn(mode, cb, cs)
    co = csp * (1.0 - ab) + as_ * ab * mix + (1.0 - as_) * cbp
    roi[..., :3] = co * 255.0; roi[..., 3:4] = (as_ + ab - as_ * ab) * 255.0


def render_pose(r, pose, rest, ds=1.0, parts_alpha=None, smooth=None, solo=None):
    """The rig as a straight-alpha BGRA picture of (w*ds) x (h*ds). pose / rest from pose_world / rest_world.
    parts_alpha: {part id: 0..1} extra opacity per part (animated alpha). solo: draw only these parts."""
    W = max(1, int(round(r["w"] * ds))); H = max(1, int(round(r["h"] * ds)))
    canvas = np.zeros((H, W, 4), np.float32)          # premultiplied, 0..255
    smooth = r["cfg"].get("smooth", True) if smooth is None else smooth
    flag = cv2.INTER_LINEAR if smooth else cv2.INTER_NEAREST
    S = mat(0, 0, 0, ds, ds); T = mat(r["w"] / 2.0, r["h"] / 2.0)
    hidden_groups = {g["id"] for g in r.get("groups", []) if g.get("hidden")}; galpha = {g["id"]: g.get("alpha", 100.0) / 100.0 for g in r.get("groups", [])}
    base_seen = False; base_patch = None                          # Patch 48: the picture a clipping mask is clipped to (the nearest one below that is not clipped itself)
    for p in sorted_parts(r):
        clipped = bool(p.get("clip")) and solo is None            # (a solo view shows a clipped picture as it is, so it never turns blank)
        if not clipped: base_seen = True; base_patch = None
        if not p.get("visible", True) or p.get("group") in hidden_groups: continue
        if solo is not None and p["id"] not in solo: continue
        op = max(0.0, min(1.0, p.get("alpha", 100.0) / 100.0 * galpha.get(p.get("group"), 1.0))) * (parts_alpha.get(p["id"], 1.0) if parts_alpha else 1.0)
        if op <= 0.001: continue
        res = _part_patch(r, p, pose, rest, S, T, flag, smooth, W, H)
        if res is None: continue
        patch, x0, y0 = res
        mp = B_get_mask(r, p)
        blend = p.get("blend", "normal")
        if mp is not None or clipped or blend != "normal":        # Patch 48: only a picture that uses a layer feature takes this way; the others are drawn exactly as before
            if mp is not None:
                mres = _part_patch(r, mp, pose, rest, S, T, flag, smooth, W, H)
                m = _region_alpha(mres, x0, y0, patch.shape[1], patch.shape[0])
                patch = patch * ((1.0 - m) if p.get("mask_inv") else m)[..., None]
            if clipped:
                if base_seen and base_patch is None: continue     # the base is hidden / empty: nothing is left to show
                if base_patch is not None: patch = patch * _region_alpha(base_patch, x0, y0, patch.shape[1], patch.shape[0])[..., None]
            if not clipped: base_patch = (patch, x0, y0)
            if blend == "normal": _paint_over(canvas, patch, x0, y0, op)
            else: _blend_over(canvas, patch, x0, y0, op, blend)
            continue
        base_patch = (patch, x0, y0)
        _paint_over(canvas, patch, x0, y0, op)
    a = canvas[..., 3:4]
    out = np.zeros((H, W, 4), np.uint8)
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(a > 0.5, canvas[..., :3] * (255.0 / np.maximum(a, 1e-3)), 0.0)
    out[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8); out[..., 3] = np.clip(a[..., 0] + 0.5, 0, 255).astype(np.uint8)
    bg = (r["cfg"].get("bg") or "").strip()
    if bg:
        m = re.match(r"^#?([0-9a-fA-F]{6})$", bg)
        if m:
            h = m.group(1); col = np.array([int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)], np.float32)
            al = out[..., 3:4].astype(np.float32) / 255.0
            out[..., :3] = np.clip(out[..., :3] * al + col * (1 - al) + 0.5, 0, 255).astype(np.uint8); out[..., 3] = 255
    return out


def rig_state(r, anim, t, rest=None, tmap=None, tclip=None, phys=True):
    """(pose, rest, parts_alpha) of the rig at animation time t: what every drawing path needs (CPU, the editor's GPU, the mesh GPU renderer)."""
    rest = rest or rest_world(r)
    ex = physics_offsets(r, anim, t if tclip is None else tclip, tmap) if (anim and phys) else None
    pose = pose_world(r, anim, t, rest, ex) if anim else rest
    pa = None
    if anim and anim["ptracks"]:
        pa = {pid: track_value((tr.get("alpha") or []), t, 100.0) / 100.0 for pid, tr in anim["ptracks"].items()}
    return pose, rest, pa


def rig_bg(r):
    """The background colour of the rig as (r, g, b, a) 0..1, or None (transparent)."""
    m = re.match(r"^#?([0-9a-fA-F]{6})$", (r["cfg"].get("bg") or "").strip())
    if not m: return None
    h_ = m.group(1); return (int(h_[0:2], 16) / 255.0, int(h_[2:4], 16) / 255.0, int(h_[4:6], 16) / 255.0, 1.0)


def mesh_job(r, gl_key, pose, rest, pa, ds):
    """(engine, MeshJob) of the mesh GPU renderer (render/meshgl.py) for this thread, or (None, None) when it cannot be used here."""
    if gl_key is None or not r["cfg"].get("gpu", True) or uses_layer_fx(r): return None, None          # Patch 48: blend / clipping / layer mask are drawn by the CPU renderer
    try:
        from . import meshgl as MG
        E = MG.engine()
        if E is None or not E.mesh_ok: return None, None
        W = max(1, int(round(r["w"] * ds))); H = max(1, int(round(r["h"] * ds)))
        return E, MG.MeshJob(r, gl_key, pose, rest, pa, W, H, ds, bool(r["cfg"].get("smooth", True)), rig_bg(r))
    except Exception as ex:
        _err("bone2d.mesh_job", ex, "Bone2D is drawn by the CPU instead"); return None, None


def _err(source, ex, fix):
    """Patch 57: the error goes to the error hub (pop-up, crash.log, circuit breaker) with what the program does about it."""
    try:
        from .. import errors as _errors; _errors.report(source, ex, fix=fix)
    except Exception: print("bone2d:", source, ex)


def render_at(r, anim, t, ds=1.0, rest=None, tmap=None, tclip=None, solo=None, phys=True, gl_key=None):
    """The rig at animation time t of `anim` (None = the rest pose). tclip / tmap: clip time and the clip-time -> animation-time map (for physics).
    gl_key: the rig is a loaded file that does not change (RigSource.key) -> it may be drawn by the GPU renderer (Live2D style); None = CPU."""
    pose, rest, pa = rig_state(r, anim, t, rest, tmap, tclip, phys)
    if solo is None:
        E, job = mesh_job(r, gl_key, pose, rest, pa, ds)          # Patch 46: skinned on the GPU, read back once (straight alpha), no CPU work on the pixels
        if E is not None:
            try: return E.render_rig_bgra(job)
            except Exception as ex:
                _err("bone2d.mesh_gpu", ex, "the Bone2D GPU mesh path is switched off; the next path draws"); E.mesh_ok = False
    if gl_key is not None and r["cfg"].get("gpu", True) and gl_enabled() and not uses_layer_fx(r):
        try:
            from . import bone2d_gl as G
            W = max(1, int(round(r["w"] * ds))); H = max(1, int(round(r["h"] * ds)))
            out = G.render(r, gl_key, pose, rest, W, H, ds, pa, solo, bool(r["cfg"].get("smooth", True)), rig_bg(r))
            if out is not None: return out
        except Exception as ex:
            _err("bone2d.gl", ex, "the Bone2D OpenGL path is switched off; the CPU draws"); set_gl_enabled(False)
    return render_pose(r, pose, rest, ds, pa, None, solo)


_GL_ON = [True]


def gl_enabled():
    try:
        from . import bone2d_gl as G
        return _GL_ON[0] and G.available()
    except Exception: return False


def set_gl_enabled(on): _GL_ON[0] = bool(on)


# ───────────────────────── files ─────────────────────────
def load_file(path):
    with open(path, "r", encoding="utf-8") as f: d = json.load(f)
    if not isinstance(d, dict): raise ValueError("not a Bone2D file")
    return fix_rig(d)


def _strip(r):
    """The rig as it is written to disk: only the images that a part still uses, no run-time keys."""
    d = copy.deepcopy({k: v for k, v in r.items() if k != "images" and not k.startswith("_")})
    used = {p.get("img") for p in r["parts"]}
    d["images"] = {k: {"name": v.get("name", ""), "png": v["png"]} for k, v in r["images"].items() if k in used}
    return d


def save_file(path, r):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(_strip(r), f, ensure_ascii=False)
    os.replace(tmp, path)


def file_duration(path):
    try:
        r = load_file(path); return anim_of(r, r["cfg"].get("default_anim"))["dur"]
    except Exception: return 5.0


# ───────────────────────── the media source used by the renderer ─────────────────────────
_RIGS = OrderedDict(); _RIGS_LOCK = threading.RLock()


def cached_rig(path):
    """The rig of a file, shared by every clip that uses it; read again when the file changes."""
    try: st = os.stat(path); key = (path, st.st_mtime_ns, st.st_size)
    except OSError: return None
    with _RIGS_LOCK:
        hit = _RIGS.get(key)
        if hit is not None: _RIGS.move_to_end(key); return hit
    try: r = load_file(path)
    except Exception as ex: print("bone2d: cannot open", path, ex); return None
    hit = RigSource(r, key)
    with _RIGS_LOCK:
        for k in [k for k in _RIGS if k[0] == path]: _RIGS.pop(k, None)
        _RIGS[key] = hit
        while len(_RIGS) > 24: _RIGS.popitem(last=False)
    return hit


class RigSource:
    """A loaded rig. The renderer asks for a per-clip view (clip config: animation, loop, speed)."""
    RIG_CACHE_BYTES = 80 * 1024 * 1024       # Patch 45 / 46: the picture cache of one rig is limited by bytes (render/ramgov.py sets it from the RAM limit)
    def __init__(self, rig, key):
        self.rig = rig; self.key = key; self.w = rig["w"]; self.h = rig["h"]; self.rest = rest_world(rig)
        self.fps = rig["cfg"].get("fps", 30); self.cache = OrderedDict(); self.lock = threading.Lock(); self._cache_bytes = 0
    def view(self, cfg):
        return Bone2DView(self, cfg or {})
    def close(self): pass


class Bone2DView:
    has_alpha = True
    def __init__(self, rs, cfg):
        self.rs = rs; self.w = rs.w; self.h = rs.h; self.fps = rs.fps
        self.anim = anim_of(rs.rig, cfg.get("anim") or ""); self.loop = cfg.get("loop") or ""
        self.speed = max(0.01, float(cfg.get("speed", 100.0) or 100.0)) / 100.0; self.offset = float(cfg.get("offset", 0.0) or 0.0)
    def _at(self, t): return anim_time(self.anim, t, self.loop, self.speed, self.offset)
    def gpu_job(self, t, ds=1.0):
        """A MeshJob for the mesh GPU renderer: the compositor draws the rig straight into the frame (no picture is made on the CPU).
        None when this thread has no GPU renderer: the caller then uses frame()."""
        rs = self.rs
        if rs.key is None: return None
        anim, lp, sp, of = self.anim, self.loop, self.speed, self.offset; at = anim_time(anim, t, lp, sp, of)
        r = rs.rig; E, job = mesh_job(r, rs.key, None, None, None, ds)
        if E is None: return None
        pose, rest, pa = rig_state(r, anim, at, rs.rest, lambda tt: anim_time(anim, tt, lp, sp, of), t)
        job.pose = pose; job.rest = rest; job.pa = pa
        return job
    def frame(self, t, ds=1.0):
        at = self._at(t)
        key = (self.anim["id"], round(t if phys_bones(self.rs.rig) else at, 4), round(ds, 3))
        with self.rs.lock:
            hit = self.rs.cache.get(key)
            if hit is not None: self.rs.cache.move_to_end(key); return hit
        anim, lp, sp, of = self.anim, self.loop, self.speed, self.offset
        img = render_at(self.rs.rig, anim, at, ds, self.rs.rest, lambda tt: anim_time(anim, tt, lp, sp, of), t, gl_key=self.rs.key)
        if getattr(_EXPORT_TLS, "on", False): return img          # an export never asks for the same picture twice: nothing is kept
        with self.rs.lock:
            self.rs.cache[key] = img; self.rs._cache_bytes += img.nbytes          # kept by size, not by count (48 pictures of a 4K rig were 3 GB)
            while len(self.rs.cache) > 1 and (len(self.rs.cache) > 48 or self.rs._cache_bytes > RigSource.RIG_CACHE_BYTES):
                self.rs._cache_bytes -= self.rs.cache.popitem(last=False)[1].nbytes
        return img
    def frame_bgr(self, t, ds=1.0): return np.ascontiguousarray(self.frame(t, ds)[..., :3])
    def close(self): pass


_EXPORT_TLS = threading.local()


def set_export_thread(on=True):
    """The export threads call this: finished rig pictures are not cached on them."""
    _EXPORT_TLS.on = bool(on)


def thumb_image(path, h):
    """A small BGRA picture of a rig file (for the media pool)."""
    r = cached_rig(path)
    if r is None: return None
    img = r.view({}).frame(0.0, 1.0)
    return cv2.resize(img, (max(1, int(img.shape[1] * h / img.shape[0])), h), interpolation=cv2.INTER_AREA)

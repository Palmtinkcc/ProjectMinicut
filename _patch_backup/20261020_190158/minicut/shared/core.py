"""Core data and helpers: constants, keyframes / properties, Settings, Project model, clip factory."""
from .deps import *
from .theme import *


FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


NOWIN = 0x08000000 if os.name == "nt" else 0


APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")


SR = 44100


CFG = {"frame_cache": 48}


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg"}


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


GIF_EXT = {".gif"}


AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".wma", ".opus"}


BLENDS = ["normal", "add", "multiply", "screen", "overlay", "soft light", "darken", "lighten", "difference", "subtract"]


CLIP_COLORS = {"video": "#1f4fbf", "image": "#1d6fa5", "gif": "#3b4fc4", "text": "#6b3fd1", "audio": "#0f7c8c"}


DEFAULT_PROPS = {"x": 0.0, "y": 0.0, "sx": 100.0, "sy": 100.0, "rot": 0.0, "opacity": 100.0, "volume": 100.0}


KEY_PROPS = [("x", "Position X"), ("y", "Position Y"), ("sx", "Scale X"), ("sy", "Scale Y"),
             ("rot", "Rotation"), ("opacity", "Opacity"), ("volume", "Volume")]


EASE_PRESETS = OrderedDict([("Linear", [0, 0, 1, 1]), ("Ease In", [.42, 0, 1, 1]), ("Ease Out", [0, 0, .58, 1]),
                            ("Ease In-Out", [.42, 0, .58, 1]), ("Back", [.34, 1.56, .64, 1]), ("Snap", [.9, 0, .1, 1])])


IDENT = [[0, 0], [1, 1]]


DEFAULT_CURVE = {"m": [[0, 0], [1, 1]], "r": [[0, 0], [1, 1]], "g": [[0, 0], [1, 1]], "b": [[0, 0], [1, 1]]}


QUALITIES = [("Performance · 25%", 0.25), ("Balanced · 50%", 0.5), ("Quality · 75%", 0.75), ("Full · 100%", 1.0)]


def new_id(): return uuid.uuid4().hex[:10]


def kind_of(p):
    e = os.path.splitext(p)[1].lower()
    if e in VIDEO_EXT: return "video"
    if e in GIF_EXT: return "gif"
    if e in IMAGE_EXT: return "image"
    if e in AUDIO_EXT: return "audio"
    return None


def is_visual(k): return k in ("video", "image", "gif", "text", "compound")


def safe_path(p):
    if os.name == "nt":
        try:
            p.encode("ascii"); return p
        except UnicodeEncodeError:
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(1024)
                if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024): return buf.value
            except Exception: pass
    return p


def safe_name(n): return re.sub(r'[\\/:*?"<>|]+', "_", n).strip() or "Untitled"


def fmt_time(t, fps=30):
    t = max(0.0, t); s = int(t); f = int(round((t - s) * fps))
    if f >= fps: f = 0; s += 1
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def imread_any(p):
    try:
        img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if img is not None and img.dtype != np.uint8: img = (img / 256).astype(np.uint8)
    return img


def to_bgra(img):
    if img is None: return None
    if img.ndim == 2: return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3: return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def np_to_qimage(img):
    h, w = img.shape[:2]
    if img.ndim == 3 and img.shape[2] == 4:
        rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)); fmt = QImage.Format_RGBA8888
    else:
        rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)); fmt = QImage.Format_RGB888
    return QImage(rgb.data, w, h, rgb.strides[0], fmt).copy()


def ffprobe_dur(path):
    try:
        p = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True, errors="ignore", creationflags=NOWIN)
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", p.stderr)
        if m: return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    except Exception: pass
    return 0.0


def probe(path):
    k = kind_of(path)
    try:
        if k == "video":
            cap = cv2.VideoCapture(safe_path(path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30; n = cap.get(cv2.CAP_PROP_FRAME_COUNT); cap.release()
            d = n / fps if n > 0 else ffprobe_dur(path)
            return k, d or 5.0
        if k == "gif":
            im = Image.open(path)
            d = sum(max(20, f.info.get("duration", 100) or 100) for f in ImageSequence.Iterator(im)) / 1000
            return k, max(d, 0.1)
        if k == "image": return k, 5.0
        if k == "audio": return k, ffprobe_dur(path) or 1.0
    except Exception: pass
    return None, 0.0


def bezier_ease(e, x):
    x1, y1, x2, y2 = e
    if (x1, y1, x2, y2) == (0, 0, 1, 1): return x
    s = x
    for _ in range(10):
        cx = 3 * x1 * s * (1 - s) ** 2 + 3 * x2 * s * s * (1 - s) + s ** 3 - x
        dx = 3 * x1 * (1 - s) ** 2 + 6 * (x2 - x1) * s * (1 - s) + 3 * (1 - x2) * s * s
        if abs(cx) < 1e-5 or abs(dx) < 1e-6: break
        s = min(1.0, max(0.0, s - cx / dx))
    return 3 * y1 * s * (1 - s) ** 2 + 3 * y2 * s * s * (1 - s) + s ** 3


def curve_eval(pts, xs):
    pts = sorted(pts); px = np.array([p[0] for p in pts], float); py = np.array([p[1] for p in pts], float)
    n = len(px)
    if n < 2: return np.asarray(xs, float)
    d = np.diff(py) / np.maximum(np.diff(px), 1e-6)
    m = np.empty(n); m[0] = d[0]; m[-1] = d[-1]
    if n > 2: m[1:-1] = (d[:-1] + d[1:]) / 2
    for i in range(n - 1):
        if d[i] == 0: m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / d[i], m[i + 1] / d[i]; s = a * a + b * b
            if s > 9: tau = 3 / math.sqrt(s); m[i] = tau * a * d[i]; m[i + 1] = tau * b * d[i]
    xs = np.asarray(xs, float)
    i = np.clip(np.searchsorted(px, xs) - 1, 0, n - 2)
    h = px[i + 1] - px[i]; t = np.clip((xs - px[i]) / np.maximum(h, 1e-6), 0, 1)
    h00 = 2 * t**3 - 3 * t**2 + 1; h10 = t**3 - 2 * t**2 + t; h01 = -2 * t**3 + 3 * t**2; h11 = t**3 - t**2
    y = h00 * py[i] + h10 * h * m[i] + h01 * py[i + 1] + h11 * h * m[i + 1]
    y = np.where(xs <= px[0], py[0], np.where(xs >= px[-1], py[-1], y))
    return np.clip(y, 0, 1)


def prop_at(c, name, lt):
    p = c["props"][name]; ks = p["k"]
    if not ks: return p["v"]
    if lt <= ks[0]["t"]: return ks[0]["v"]
    if lt >= ks[-1]["t"]: return ks[-1]["v"]
    for a, b in zip(ks, ks[1:]):
        if a["t"] <= lt <= b["t"]:
            span = b["t"] - a["t"]; u = 0 if span <= 0 else (lt - a["t"]) / span
            return a["v"] + (b["v"] - a["v"]) * bezier_ease(a.get("e", [0, 0, 1, 1]), u)
    return ks[-1]["v"]


def key_at(c, name, lt, tol=1 / 60):
    for k in c["props"][name]["k"]:
        if abs(k["t"] - lt) < tol: return k
    return None


def add_key(c, name, lt, v=None):
    p = c["props"][name]
    if v is None: v = prop_at(c, name, lt)
    k = key_at(c, name, lt)
    if k: k["v"] = v; return
    p["k"].append({"t": lt, "v": v, "e": [0, 0, 1, 1]}); p["k"].sort(key=lambda k: k["t"])


def remove_key(c, name, k):
    p = c["props"][name]; p["k"].remove(k)
    if not p["k"]: p["v"] = k["v"]


def set_prop(c, name, lt, v):
    if c["props"][name]["k"]: add_key(c, name, lt, v)
    else: c["props"][name]["v"] = v


DEFAULT_SHORTCUTS = OrderedDict([
    ("play", "Space"), ("split", "Ctrl+B"), ("delete", "Delete"), ("undo", "Ctrl+Z"), ("redo", "Ctrl+Shift+Z"),
    ("copy", "Ctrl+C"), ("paste", "Ctrl+V"), ("duplicate", "Ctrl+D"), ("save", "Ctrl+S"), ("export", "Ctrl+E"),
    ("import", "Ctrl+I"), ("add_text", "T"), ("keyframe", "K"), ("prev_frame", "Left"), ("next_frame", "Right"),
    ("go_start", "Home"), ("go_end", "End"), ("zoom_in", "Ctrl+="), ("zoom_out", "Ctrl+-"), ("zoom_fit", "Shift+Z"),
    ("snap", "S"), ("home", "Ctrl+H")])


ACTION_LABELS = {"play": "Play / Pause", "split": "Split clip", "delete": "Delete clip", "undo": "Undo", "redo": "Redo",
    "copy": "Copy clip", "paste": "Paste clip", "duplicate": "Duplicate clip", "save": "Save project",
    "export": "Export", "import": "Import media", "add_text": "Add text", "keyframe": "Add / remove keyframe",
    "prev_frame": "Previous frame", "next_frame": "Next frame", "go_start": "Go to start", "go_end": "Go to end",
    "zoom_in": "Timeline zoom in", "zoom_out": "Timeline zoom out", "zoom_fit": "Timeline zoom to fit",
    "snap": "Toggle auto snap", "home": "Back to projects"}


def with_groups(app, ids):
    """Add every clip that shares a group with any clip in ids."""
    gs = {c.get("group") for c in app.proj.clips if c["id"] in ids and c.get("group")}
    return set(ids) | {c["id"] for c in app.proj.clips if c.get("group") and c.get("group") in gs}


class Settings:
    def __init__(self):
        os.makedirs(APP_DIR, exist_ok=True)
        self.file = os.path.join(APP_DIR, "settings.json")
        self.d = {"asset_folder": os.path.join(os.path.expanduser("~"), "Videos"),
                  "project_folder": os.path.join(APP_DIR, "projects"),
                  "export_folder": os.path.join(os.path.expanduser("~"), "Videos"),
                  "preview_quality": 0.5, "preview_interp": "fast", "play_reduce": True, "frame_cache": 24,
                  "preview_fps": 30, "adaptive_preview": True, "hw_decode": False, "encode_hw": "auto", "proxy_preview": True, "proxy_height": 540, "proxy_quality": 23, "layout": None, "curve_presets": {}, "proxy_budget_gb": 40,
                  "fit_viewport": True, "gpu_compose": "auto", "render_threads": 0, "preview_ram_mb": 512, "low_priority": True, "proxy_hw": "auto", "audio_cache_gb": 8,
                  "snap": True, "default_w": 1920, "default_h": 1080, "default_fps": 30,
                  "shortcuts": dict(DEFAULT_SHORTCUTS), "theme": {}}
        try:
            with open(self.file, "r", encoding="utf-8") as f: d = json.load(f)
            sc = d.pop("shortcuts", {}); self.d.update(d); self.d["shortcuts"].update(sc)
        except Exception: pass
        load_theme(self.d.get("theme"))
        os.makedirs(self.d["project_folder"], exist_ok=True)
    def __getitem__(self, k): return self.d[k]
    def __setitem__(self, k, v): self.d[k] = v
    def save(self):
        self.d["theme"] = theme_changes()
        try:
            with open(self.file, "w", encoding="utf-8") as f: json.dump(self.d, f, indent=2, ensure_ascii=False)
        except Exception as ex: print("settings save failed", ex)


def make_clip(kind, path, track, start, dur, src_dur=0.0, name=""):
    return {"id": new_id(), "kind": kind, "path": path, "track": track, "start": start, "inp": 0.0, "dur": dur,
            "src_dur": src_dur, "name": name or (os.path.basename(path) if path else "Text"),
            "props": {k: {"v": v, "k": []} for k, v in DEFAULT_PROPS.items()},
            "blend": "normal", "effects": [],      # effects: ordered effect layers, see render/effects.py
            "text": "Your text", "font": "Segoe UI", "fsize": 96, "tcolor": "#ffffff", "bold": True,
            "stroke": 0, "scolor": "#000000", "mask": "None", "mask_feather": 0}


def migrate_clip(c):
    """Older projects stored colour / chroma settings as fixed clip fields; turn them into effect layers (idempotent)."""
    if not isinstance(c, dict): return c
    for ch in c.get("children", []): migrate_clip(ch)
    if "effects" in c: return c
    fx = []
    if float(c.get("tint_amt", 0) or 0) > 0:
        fx.append({"id": new_id(), "type": "tint", "on": True, "p": {"color": c.get("tint", "#2f7bff"), "amount": float(c["tint_amt"])}})
    curve = c.get("curve")
    if isinstance(curve, dict) and any(curve.get(k, IDENT) != IDENT for k in "mrgb"):
        fx.append({"id": new_id(), "type": "curves", "on": True, "p": {"curve": copy.deepcopy(curve)}})
    if c.get("chroma_enabled"):
        fx.append({"id": new_id(), "type": "chroma", "on": True, "p": {"color": c.get("chroma_color", "#00ff00"), "tolerance": int(c.get("chroma_tolerance", 55))}})
    c["effects"] = fx
    for k in ("tint", "tint_amt", "curve", "chroma_enabled", "chroma_color", "chroma_tolerance"): c.pop(k, None)
    old = {"Rectangle": ("Rect", .94, .94), "Ellipse": ("Circle", 1.0, 1.0)}.get(c.get("mask"))      # the old "Alpha mask" drop-down
    if old: c["mask"] = old[0]; c["mask_shape"] = {"cx": .5, "cy": .5, "w": old[1], "h": old[2], "rot": 0.0, "round": 0.0, "invert": False, "pts": []}
    return c


def make_track(kind, name):
    return {"id": new_id(), "kind": kind, "name": name, "hidden": False, "muted": False, "locked": False}


class Project:
    def __init__(self, name="Untitled", w=1920, h=1080, fps=30):
        self.name, self.w, self.h, self.fps = name, int(w), int(h), int(fps)
        self.bg = "#000000"; self.path = None; self.media = []; self.clips = []; self.graph = {"nodes": [], "links": [], "on": True}
        self.tracks = [make_track("video", "Video 1"), make_track("audio", "Audio 1")]
    def to_dict(self):
        return {"version": 2, "name": self.name, "w": self.w, "h": self.h, "fps": self.fps, "bg": self.bg,
                "media": self.media, "tracks": self.tracks, "clips": self.clips, "graph": self.graph}
    @staticmethod
    def from_dict(d):
        p = Project(d.get("name", "Untitled"), d.get("w", 1920), d.get("h", 1080), d.get("fps", 30))
        p.bg = d.get("bg", "#000000"); p.media = d.get("media", []); p.tracks = d.get("tracks") or p.tracks
        p.clips = d.get("clips", [])
        g = d.get("graph")
        if isinstance(g, dict): p.graph = {"nodes": list(g.get("nodes") or []), "links": list(g.get("links") or []), "on": g.get("on", True)}
        for t in p.tracks:
            for k, v in make_track(t.get("kind", "video"), "").items(): t.setdefault(k, v)
        for c in p.clips:
            migrate_clip(c)
            for k, v in make_clip(c.get("kind", "video"), c.get("path", ""), c.get("track"), 0, 1).items(): c.setdefault(k, v)
            for k, v in DEFAULT_PROPS.items(): c["props"].setdefault(k, {"v": v, "k": []})
        return p
    def duration(self): return max((c["start"] + c["dur"] for c in self.clips), default=0.0)
    def track(self, tid): return next((t for t in self.tracks if t["id"] == tid), None)
    def track_index(self, tid): return next((i for i, t in enumerate(self.tracks) if t["id"] == tid), 0)
    def add_track(self, kind, index=None):
        n = sum(1 for t in self.tracks if t["kind"] == kind) + 1
        tr = make_track(kind, f"{'Video' if kind == 'video' else 'Audio'} {n}")
        first_audio = next((i for i, t in enumerate(self.tracks) if t["kind"] == "audio"), len(self.tracks))
        if index is None: index = 0 if kind == "video" else len(self.tracks)
        index = min(index, first_audio) if kind == "video" else max(index, first_audio)
        self.tracks.insert(index, tr); return tr


def _shift_keys(clip, cut):
    for pr in clip["props"].values(): pr["k"] = [dict(k, t=k["t"] - cut) for k in pr["k"] if k["t"] >= cut]


def flatten_compounds(proj):
    clips = getattr(proj, "clips", None)
    if not clips or not any(c.get("kind") == "compound" for c in clips): return proj
    p = copy.copy(proj); p.clips = []; p.tracks = list(proj.tracks)
    for c in clips:
        if c.get("kind") != "compound": p.clips.append(c); continue
        tr = proj.track(c["track"])
        if tr and tr.get("muted"): continue
        p.tracks += c.get("subtracks", [])
        a, b = c["start"], c["start"] + c["dur"]; off = c["start"] - c["inp"]
        for ch in c.get("children", []):
            if ch["kind"] not in ("audio", "video"): continue
            s = ch["start"] + off; e = s + ch["dur"]; s2, e2 = max(s, a), min(e, b)
            if e2 <= s2: continue
            n = copy.deepcopy(ch) if s2 > s else dict(ch)
            n["start"] = s2; n["dur"] = e2 - s2; n["inp"] = ch["inp"] + (s2 - s)
            if s2 > s: _shift_keys(n, s2 - s)
            p.clips.append(n)
    return p


SIZE_PRESETS = [("16:9  Landscape · 1920×1080", 1920, 1080), ("9:16  Vertical · 1080×1920", 1080, 1920), ("1:1  Square · 1080×1080", 1080, 1080),
           ("4:5  Portrait · 1080×1350", 1080, 1350), ("4:3  · 1440×1080", 1440, 1080), ("21:9  Cinema · 2560×1080", 2560, 1080),
           ("16:9  4K · 3840×2160", 3840, 2160), ("16:9  HD · 1280×720", 1280, 720)]


def _sel_clips(self):
    ids = set(getattr(self, "multi", set()) or ())
    if self.sel: ids.add(self.sel)
    return [c for c in self.proj.clips if c["id"] in ids] if self.proj else []


def _group_ids(app, c):
    g = c.get("group")
    return {o["id"] for o in app.proj.clips if g and o.get("group") == g} | {c["id"]}

"""FX editor preview engine (Patch 52) - no Qt in it.

The preview applies the effect that is being built to ONE picture and loops it for a few seconds, so animated nodes
(Time, Wave, Noise, Wave (LFO) ...) can be seen moving. The picture comes from the project's own media, from a file, or
from a built-in test picture. To stay light on the computer the picture is processed at a reduced size, and that size
adapts to how fast the effect runs; a graph that does not move is rendered once and then left alone.
"""
import os, time
from types import SimpleNamespace

import cv2
import numpy as np

from ..render.fxpack.custom import FX_NODE_TYPES, compile_effect, collect_param_specs

LOOP_SECONDS = 3.0
BASE_WIDTH = 960               # the picture is kept at most this wide; the work size is a fraction of it
SAMPLE_NAMES = ["Color bars", "Landscape", "Shapes", "Gray ramp"]
_TIME_NODES = ("fx_time", "fx_lfo", "fx_wave_warp", "fx_noise_tex")


# ── test pictures ─────────────────────────────────────────────────────────────

def sample_picture(name: str, w: int = 960, h: int = 540) -> np.ndarray:
    """A BGRA test picture with colour, detail and edges (so most effects show something)."""
    img = np.zeros((h, w, 4), np.uint8); img[..., 3] = 255
    if name == "Color bars":
        cols = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0), (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]   # BGR
        bw = max(1, w // len(cols))
        for i, c in enumerate(cols): img[: int(h * 0.75), i * bw: (i + 1) * bw if i < len(cols) - 1 else w, :3] = c
        ramp = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
        img[int(h * 0.75):, :, 0] = ramp; img[int(h * 0.75):, :, 1] = ramp; img[int(h * 0.75):, :, 2] = ramp
    elif name == "Landscape":
        t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        sky_top = np.array([180, 110, 40], np.float32); sky_low = np.array([90, 150, 255], np.float32)      # BGR
        img[..., :3] = np.clip(sky_top[None, None, :] * (1 - t[..., None]) + sky_low[None, None, :] * t[..., None], 0, 255).astype(np.uint8)
        cv2.circle(img, (int(w * 0.72), int(h * 0.42)), int(h * 0.12), (170, 240, 255, 255), -1, cv2.LINE_AA)
        x = np.arange(w, dtype=np.float32)
        for k, (base, amp, col) in enumerate(((0.62, 0.07, (96, 70, 60)), (0.72, 0.06, (60, 45, 35)), (0.84, 0.05, (30, 22, 18)))):
            ridge = (base + amp * np.sin(x / w * (5 + 3 * k) + k * 1.7) + 0.02 * np.sin(x / w * (23 + 7 * k))) * h
            yy = np.arange(h, dtype=np.float32)[:, None]
            img[yy >= ridge[None, :], :3] = col
    elif name == "Shapes":
        t = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
        img[..., 0] = (40 + 60 * t).astype(np.uint8); img[..., 1] = 30; img[..., 2] = (70 + 30 * (1 - t)).astype(np.uint8)
        cv2.circle(img, (int(w * 0.25), int(h * 0.5)), int(h * 0.28), (60, 200, 255, 255), -1, cv2.LINE_AA)
        cv2.rectangle(img, (int(w * 0.45), int(h * 0.2)), (int(w * 0.7), int(h * 0.8)), (255, 140, 40, 255), -1)
        cv2.circle(img, (int(w * 0.82), int(h * 0.5)), int(h * 0.2), (120, 255, 120, 255), 6, cv2.LINE_AA)
        cv2.putText(img, "MINICUT", (int(w * 0.08), int(h * 0.92)), cv2.FONT_HERSHEY_SIMPLEX, h / 260.0, (255, 255, 255, 255), max(2, h // 140), cv2.LINE_AA)
    else:                                                      # "Gray ramp"
        ramp = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
        for c in range(3): img[..., c] = ramp
        img[: h // 2, : w // 6, :3] = 0; img[h // 2:, -w // 6:, :3] = 255
    return img


# ── loading the picture ───────────────────────────────────────────────────────

def _fit(img: np.ndarray, max_w: int) -> np.ndarray:
    if img is None: return None
    h, w = img.shape[:2]
    if w <= max_w: return np.ascontiguousarray(img)
    return cv2.resize(img, (max_w, max(1, int(round(h * max_w / w)))), interpolation=cv2.INTER_AREA)


def _to_bgra(img):
    if img is None: return None
    if img.dtype != np.uint8: img = np.clip(img / 256.0 if img.dtype == np.uint16 else img, 0, 255).astype(np.uint8)
    if img.ndim == 2: return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3: return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def _read_image_file(path):
    try: img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)       # works with Thai / unicode paths
    except Exception: img = None
    if img is None:
        try:
            from PIL import Image
            im = Image.open(path); im.load(); img = cv2.cvtColor(np.array(im.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
        except Exception: img = None
    return _to_bgra(img)


def _read_video_frame(path, t):
    try:
        try:
            from ..render.media import safe_path as _sp
            path = _sp(path)
        except Exception: pass
        cap = cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, img = cap.read()
        if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, img = cap.read()
        cap.release()
        return _to_bgra(img) if ok else None
    except Exception: return None


def load_picture(spec: dict, max_w: int = BASE_WIDTH):
    """spec: {"type": "sample", "name": ...} | {"type": "file", "path": ...} | {"type": "clip", "path", "kind", "t"}.
    Returns a BGRA picture (at most max_w wide) or None when it cannot be read."""
    if not isinstance(spec, dict): return None
    typ = spec.get("type")
    try:
        if typ == "sample": return sample_picture(spec.get("name", SAMPLE_NAMES[0]), min(max_w, BASE_WIDTH), int(min(max_w, BASE_WIDTH) * 9 / 16))
        path = spec.get("path")
        if not path or not os.path.exists(path): return None
        if typ == "file": return _fit(_read_image_file(path), max_w)
        if typ == "clip":
            kind = spec.get("kind")
            img = _read_video_frame(path, float(spec.get("t", 0.0))) if kind == "video" else _read_image_file(path)
            return _fit(img, max_w)
    except Exception:
        return None
    return None


# ── is the effect moving? ─────────────────────────────────────────────────────

def graph_is_animated(graph: dict) -> bool:
    """True when something in the graph changes over time (so the preview has to keep redrawing)."""
    graph = graph or {}
    driven = set()
    for lk in graph.get("links", []):
        try:
            if int(lk.get("ti", 0)) >= len(FX_NODE_TYPES.get(next((n["type"] for n in graph.get("nodes", []) if n.get("id") == lk.get("to")), ""), {}).get("ins", [])):
                driven.add(lk.get("to"))
        except Exception: pass
    for n in graph.get("nodes", []):
        if not isinstance(n, dict) or n.get("mute") or n.get("type") not in _TIME_NODES: continue
        p = n.get("p") or {}
        def num(k, d):
            try: return float(p.get(k, d))
            except Exception: return d
        typ = n["type"]
        if n.get("id") in driven or typ == "fx_time": return True        # a wired parameter may follow time: keep drawing
        if typ == "fx_noise_tex" and num("speed", 0.5) > 1e-9: return True
        if typ == "fx_wave_warp" and abs(num("amp", 20.0)) > 1e-9 and abs(num("speed", 1.0)) > 1e-9: return True
        if typ == "fx_lfo" and abs(num("speed", 0.5)) > 1e-9: return True
    return False


# ── the engine ────────────────────────────────────────────────────────────────

class FxPreview:
    TARGET_MS = 45.0            # about 20 pictures a second
    TOO_SLOW_MS = 80.0

    def __init__(self, ref_width: float = 1920.0):
        self.base = None            # the picture, at most BASE_WIDTH wide
        self.work = None            # the picture at the current work size
        self.scale = 1.0
        self.ref_width = float(ref_width)     # width of the project's picture: sizes in pixels are scaled to this
        self.fn = None; self.error = None; self.warnings = []
        self.values = {}            # slider values: exposed parameters and Parameter nodes
        self.animated = False
        self.last_ms = 0.0; self.last = None
        self._fast_run = 0

    # -- inputs --
    def set_source(self, img):
        self.base = img if img is None else _fit(_to_bgra(img), BASE_WIDTH); self.scale = 1.0; self._make_work(); self.last = None

    def set_graph(self, graph: dict) -> bool:
        """Compile the graph. On an error the previous effect keeps running and `error` says what is wrong."""
        try:
            fn = compile_effect(graph, [])
        except Exception as ex:
            self.error = str(ex).splitlines()[0] if str(ex) else "error"; return False
        self.fn = fn; self.error = None; self.warnings = list(getattr(fn, "_fx_warnings", [])); self.animated = graph_is_animated(graph)
        self.last = None
        # sliders: a value the person has moved stays; new sliders start at the node's own value
        specs = collect_param_specs(graph)
        self.values = {s[0]: self.values.get(s[0], s[3]) for s in specs}
        return True

    def set_value(self, key, v): self.values[key] = v; self.last = None

    # -- work size --
    def _make_work(self):
        if self.base is None: self.work = None; return
        h, w = self.base.shape[:2]; s = max(0.2, min(1.0, self.scale))
        self.work = self.base if s >= 0.999 else cv2.resize(self.base, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA)

    def _adapt(self, ms):
        """Slow effect -> smaller picture; plenty of time to spare -> bigger again (slowly, so it does not flicker)."""
        if ms > self.TOO_SLOW_MS and self.scale > 0.21:
            self.scale = max(0.2, self.scale * 0.8); self._fast_run = 0; self._make_work()
        elif ms < self.TARGET_MS * 0.5 and self.scale < 1.0:
            self._fast_run += 1
            if self._fast_run >= 15: self.scale = min(1.0, self.scale * 1.15); self._fast_run = 0; self._make_work()
        else: self._fast_run = 0

    # -- output --
    def render(self, t: float):
        """The effect applied to the picture at time t (looped over LOOP_SECONDS). None when there is no picture or no
        working effect yet. A still graph is rendered once and then the same picture is returned."""
        if self.work is None or self.fn is None: return None
        if not self.animated and self.last is not None: return self.last
        lt = float(t) % LOOP_SECONDS
        ctx = SimpleNamespace(k=max(1e-3, self.work.shape[1] / self.ref_width), lt=lt, fast=False,
                              clip={"start": 0.0, "dur": LOOP_SECONDS}, holder={}, progress_keyframed=False)
        t0 = time.perf_counter()
        try: out = self.fn(self.work, dict(self.values), ctx)
        except Exception as ex:
            self.error = "while running: " + (str(ex).splitlines()[0] if str(ex) else "error"); return self.last
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        self.last = out
        if self.animated: self._adapt(self.last_ms)
        return out

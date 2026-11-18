"""MeshGL (Patch 46): the whole frame is composed on the GPU, and Bone2D rigs are drawn as GPU-skinned meshes straight into it.

Why
---
Before, a frame was composed on the CPU (export) or by a Qt compositor that only the preview used. A Bone2D clip was drawn by a
separate OpenGL thread, read back to the CPU (QImage copy + copy + un-premultiply over the whole picture) and then uploaded again as an
ordinary picture. The editor canvas of Bone2D is smooth because it draws the mesh straight to the screen; the timeline was slow because
of everything around that draw. Here the rig never leaves the GPU:

    atlas texture (all pictures of the rig, mipmapped, uploaded once, the CPU copy is freed)
      + static vertex buffer (rest position, uv, 4 bone indices, 4 weights per vertex), static index buffer
      + one small bone-matrix texture per frame (the pose)   ->  the vertex shader skins the mesh (Live2D style), 1 draw call
    -> rig texture (MSAA, resolved on the GPU)  ->  drawn as one quad into the frame together with the video / image / text layers
    -> ONE read-back of the finished frame (preview and export), straight into a fresh numpy array.

Everything is "storage order" (B, G, R, A): pictures are uploaded as they are, nothing is swizzled on the CPU and the frame is read back as
BGR, so it goes to the encoder as it is. Row 0 of a numpy picture is the top; the vertex shaders put it into row 0 of the render target, so
there is no vertical flip anywhere.

Safety (same rules as glfx.py: a video editor must never crash because of a driver)
  * moderngl missing, OpenGL < 3.3, software GL (llvmpipe / GDI generic) -> the module stays off, the CPU draws exactly as before.
  * A "probing" note is written before the first context is made; if the program died there, GL stays off until reset() (Test GPU).
  * A self test (composite against the CPU reference, a skinned rig against the CPU rig drawing) runs once; a mismatch keeps it off.
  * Only threads that call enable_current_thread() (the preview thread, the export threads) may use it.
  * Any GL error -> fail(): off for the rest of the session, the CPU draws that same frame.
  * A rig error alone only switches the Bone2D mesh path off (mesh_ok), the layer compositing goes on.
  * The moderngl context of a thread is shared with glfx.py (one context per thread, reference counted).
"""
import json
import os
import threading
import time
import weakref
from collections import OrderedDict

import cv2
import numpy as np

from .vram import VramInfo
from .rmgr import ResourceManager, MB as _MB
from .gpuledger import LEDGER as _LEDGER
from . import gpucap as _gpucap
from .. import degrade as _degrade
from .. import errors as _errors      # Patch 57: every error goes through one hub (pop-up, circuit breaker)
from . import rprof as _rp            # Patch 47: frame stage profiler (off unless MINICUT_RPROF=1; every hook is one float test when off)

try:
    import moderngl
except Exception:                                    # not installed: everything stays on the CPU
    moderngl = None

try:
    from ..shared.core import APP_DIR
except Exception:
    APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")

STATE_FILE = os.path.join(APP_DIR, "meshgl_state.json")
ENGINE = 46
_ST = {"disabled": False, "status": "not started", "ok": False, "gen": 0, "lock": threading.Lock()}
_TLS = threading.local()
TEX_BUDGET = [128 * 2 ** 20]            # bytes of picture textures kept for the next frame (render/ramgov.py changes it with the RAM limit)
_IGPU_WORDS = ("intel", "uhd", "iris", "radeon graphics", "radeon(tm) graphics", "vega", "apple", "adreno", "mali", "powervr", "microsoft basic")
_SOFT_WORDS = ("gdi generic", "llvmpipe", "software", "swrast", "softpipe")


# ───────────────────────── state / crash guard ─────────────────────────
def _read():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("engine") == ENGINE else {}
    except Exception:
        return {}


def _write(d):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(d, engine=ENGINE) if d else {}, f)
    except Exception:
        pass


def status():
    return _ST["status"]


def reset():
    """Forget an earlier failure / crash note and allow GL again (the Test GPU button calls this)."""
    _write({})
    with _ST["lock"]:
        _ST["disabled"] = False; _ST["ok"] = False; _ST["status"] = "not started"; _ST["gen"] += 1       # every thread starts its engine again on its next frame


def fail(why):
    _errors.report("gpu.meshgl", str(why), fix="the GPU renderer is switched off; the CPU renderer draws from now on")
    _ST["disabled"] = True; _ST["status"] = "off: " + str(why)
    _write({"status": "failed", "reason": str(why)})
    try:
        from .debug_trace import trace_event
        trace_event("meshgl_off", reason=str(why))
    except Exception:
        pass


def enabled_by_user():
    if os.environ.get("MINICUT_NO_MESHGL"):
        return False
    try:
        from .gpu import GPU
        return GPU.mode != "off"                       # the "GPU compositing" setting (Off = CPU only) also switches this off
    except Exception:
        return True


def enable_current_thread():
    """Call once on a thread that renders frames (the preview thread, an export thread)."""
    _TLS.allowed = True


def set_export_mode(on=True):
    """This thread is an export thread: smaller texture cache (frames are never drawn twice), engine closed by close_thread()."""
    _TLS.export = bool(on)


def is_export():
    return bool(getattr(_TLS, "export", False))


# ───────────────────────── one moderngl context per thread, shared with glfx.py ─────────────────────────
def _give_back(need):
    """The ledger is about to refuse a resource: this thread's engine gives back its idle caches and pools first."""
    eng = getattr(_TLS, "engine", None)
    if eng is not None:
        _errors.report("gpu.memory", "GPU memory is nearly full", severity=_errors.MAJOR)
        eng._shrink(); _errors.note_fix("gpu.memory", "gave back idle caches and pools")
        if not eng.export: _degrade.pressure("ceiling")                 # Patch 58: step 3/4 of the ladder (low preview, then CPU) if it keeps happening


def _reaped(nbytes, count):
    _errors.report("gpu.leak", "%d GPU objects (%.0f MB) were dropped without release() and are being released" % (count, nbytes / _MB), severity=_errors.MAJOR,
                   fix="released them; a code path forgot release() - send this report")


def acquire_context():
    ctx = getattr(_TLS, "ctx", None)
    if ctx is None:
        try:
            ctx = moderngl.create_standalone_context()
        except Exception:
            if os.name != "posix":
                raise
            ctx = moderngl.create_standalone_context(backend="egl")        # Linux without a display: EGL
        # NOT gc_mode "auto" (tried in Patch 56, removed in 57: the Bone2D-in-compound test showed that some code relies on objects that nobody references).
        # The ledger below keeps every object alive, counts it until release(), and only on pressure releases the ones nobody references any more.
        try: _LEDGER.wrap(ctx, _give_back); _LEDGER.on_reap = _reaped      # Patch 57: every texture / buffer / renderbuffer is counted; the ceiling is enforced
        except Exception: pass
        _TLS.ctx = ctx; _TLS.refs = 0
    _TLS.refs += 1
    return ctx


def release_context():
    ctx = getattr(_TLS, "ctx", None)
    if ctx is None:
        return
    _TLS.refs = getattr(_TLS, "refs", 1) - 1
    if _TLS.refs <= 0:
        _TLS.ctx = None; _TLS.refs = 0
        try: ctx.release()
        except Exception: pass


def close_thread():
    """Release this thread's engine (an export thread calls it when it is done)."""
    eng = getattr(_TLS, "engine", None)
    _TLS.engine = None; _TLS.tried = False; _TLS.allowed = False; _TLS.export = False
    if eng is not None:
        try: eng.close()
        except Exception: pass


def engine():
    """The GL engine of this thread, started on first use. None = not available here: the caller draws on the CPU."""
    if moderngl is None or _ST["disabled"] or not getattr(_TLS, "allowed", False) or not enabled_by_user():
        return None
    if getattr(_TLS, "gen", 0) != _ST["gen"]:                  # Test GPU was pressed: forget what this thread learned
        old = getattr(_TLS, "engine", None); _TLS.engine = None; _TLS.tried = False; _TLS.gen = _ST["gen"]
        if old is not None:
            try: old.close()
            except Exception: pass
    eng = getattr(_TLS, "engine", None)
    if eng is not None:
        return eng
    if getattr(_TLS, "tried", False):
        return None
    _TLS.tried = True
    return _start()


def _start():
    with _ST["lock"]:
        first = not _ST["ok"]
        if first:
            st = _read()
            if st.get("status") == "probing":
                fail("the program stopped while the GPU renderer was tested last time (Test GPU tries again)")
                return None
            if st.get("status") == "failed" and not os.environ.get("MINICUT_MESHGL_FORCE"):
                _ST["disabled"] = True; _ST["status"] = "off: %s (Test GPU tries again)" % st.get("reason", "failed before")
                return None
            _write({"status": "probing"})
        try:
            eng = Engine()
            if not first:
                eng.mesh_ok = bool(_ST.get("mesh_ok"))               # the start-up test ran once for the process; later threads (export pieces) inherit its result
            if first:
                ok, why = eng.self_test()
                if not ok:
                    eng.close(); _write({"status": "failed", "reason": why}); _ST["disabled"] = True; _ST["status"] = "off: " + why
                    return None
        except Exception as ex:
            fail("start-up error: %s" % (ex,)); return None
        _TLS.engine = eng
        if not first: return eng
        _ST["ok"] = True; _ST["mesh_ok"] = bool(eng.mesh_ok)
        _ST["status"] = "active: %s [%s mesh GPU renderer%s]" % (eng.name, "iGPU" if eng.igpu else "GPU", "" if eng.mesh_ok else ", Bone2D mesh off: %s" % eng.mesh_info)
        _write({"status": "ok", "name": eng.name})
        try:                                            # the Settings window shows one GPU line: say what really draws
            from .gpu import GPU
            GPU.status = _ST["status"]
        except Exception:
            pass
        return eng


# ───────────────────────── what the renderer hands over ─────────────────────────
class MeshJob:
    """A Bone2D rig to draw at pose `pose` into a W x H picture (the rig size times ds). It behaves like a picture of that size
    (.shape), so the placement matrix is made the same way as for a video frame. bg: (r, g, b, a) 0..1 or None (transparent)."""
    __slots__ = ("rig", "key", "pose", "rest", "pa", "W", "H", "ds", "smooth", "bg", "shape")

    def __init__(self, rig, key, pose, rest, pa, W, H, ds, smooth=True, bg=None):
        self.rig = rig; self.key = key; self.pose = pose; self.rest = rest; self.pa = pa; self.W = int(W); self.H = int(H)
        self.ds = ds; self.smooth = bool(smooth); self.bg = bg; self.shape = (self.H, self.W, 4)


class CompoundJob:
    """A compound clip drawn on the GPU as a sub-frame (render core, step 2): `layers` is a list like the one composite() takes (pictures, MeshJobs and
    other CompoundJobs), drawn bottom first over a transparent W x H target. The result is a premultiplied texture that the parent draws like a
    picture of that size (.shape), so the placement matrix is made the same way as for a video frame. Nothing is made on the CPU."""
    __slots__ = ("W", "H", "layers", "shape")

    def __init__(self, W, H, layers):
        self.W = int(W); self.H = int(H); self.layers = layers; self.shape = (self.H, self.W, 4)


class EffectJob:
    """The effect stack of a layer, run on the GPU (render core, step 3): `src` is the picture (a numpy array), a MeshJob or a CompoundJob, `groups` are the
    passes of glfx (built by glfx.build_chain_shape). The source is made on the GPU, the passes run on its texture, and the result is drawn like a picture
    of the same size (.shape): no upload and no read-back for the effect."""
    __slots__ = ("src", "groups", "W", "H", "shape", "cache", "planes")

    def __init__(self, src, groups, W, H, cache=False, planes=None):
        self.src = src; self.groups = groups; self.W = int(W); self.H = int(H); self.cache = bool(cache); self.shape = (self.H, self.W, 4)
        self.planes = planes or {}          # name -> (H, W, 1) uint8 array that the passes read as a texture (the mask); the same array object every frame keeps its texture cached


_UNPREMUL = ("#version 330\nin vec2 v_uv; out vec4 o; uniform sampler2D u_in;\n"
             "void main() { vec4 c = texture(u_in, v_uv); o = c.a > 0.0 ? vec4(min(c.rgb / c.a, vec3(1.0)), c.a) : vec4(0.0); }\n")      # rigs and compounds are premultiplied, effects work on straight alpha


# ───────────────────────── shaders (GLSL 330) ─────────────────────────
_VS_QUAD = """#version 330
in vec2 a_pos;                       // 0..1 corner of the picture
uniform vec2 u_size;                 // picture size (px)
uniform vec3 u_r0; uniform vec3 u_r1; // picture px -> frame px (affine, 2 rows)
uniform vec2 u_frame;
out vec2 v_uv;
void main() {
    vec3 p = vec3(a_pos * u_size, 1.0);
    vec2 d = vec2(dot(u_r0, p), dot(u_r1, p));
    gl_Position = vec4(d / u_frame * 2.0 - 1.0, 0.0, 1.0);      // y is not flipped: picture row 0 -> render target row 0
    v_uv = a_pos;
}
"""

_FS_LIN = """#version 330
in vec2 v_uv; out vec4 f;
uniform sampler2D u_tex; uniform float u_op; uniform int u_premul;
void main() {
    vec4 c = texture(u_tex, v_uv);
    if (u_premul == 1) { f = c * u_op; }
    else { float a = c.a * u_op; f = vec4(c.rgb * a, a); }
}
"""

BLEND_IDS = {"normal": 0, "add": 1, "multiply": 2, "screen": 3, "overlay": 4, "soft light": 5, "darken": 6, "lighten": 7, "difference": 8, "subtract": 9}

# A layer with a blend mode (render core, step 3b): the layer is drawn on the opaque frame, reading what is already there (a copy of the target) at the same
# pixel; the formulas are those of fastcomp.blend_mode, the mix with the backdrop uses alpha x opacity like fastcomp._alpha_comp.
_FS_BLEND = """#version 330
in vec2 v_uv; out vec4 f;
uniform sampler2D u_tex; uniform sampler2D u_bg; uniform float u_op; uniform int u_premul; uniform int u_mode;
vec3 bl(vec3 b, vec3 t) {
    if (u_mode == 1) return min(b + t, 1.0);
    if (u_mode == 2) return b * t;
    if (u_mode == 3) return 1.0 - (1.0 - b) * (1.0 - t);
    if (u_mode == 4) return mix(2.0 * b * t, 1.0 - 2.0 * (1.0 - b) * (1.0 - t), step(0.5, b));
    if (u_mode == 5) return (1.0 - 2.0 * t) * b * b + 2.0 * t * b;
    if (u_mode == 6) return min(b, t);
    if (u_mode == 7) return max(b, t);
    if (u_mode == 8) return abs(b - t);
    if (u_mode == 9) return max(b - t, 0.0);
    return t;
}
void main() {
    vec4 c = texture(u_tex, v_uv); float a = c.a * u_op;
    vec3 top = (u_premul == 1) ? (c.a > 0.0 ? min(c.rgb / c.a, vec3(1.0)) : vec3(0.0)) : c.rgb;
    vec3 b = texelFetch(u_bg, ivec2(gl_FragCoord.xy), 0).rgb;
    f = vec4(mix(b, bl(b, top), a), 1.0);
}
"""

_FS_CUB = """#version 330
in vec2 v_uv; out vec4 f;
uniform sampler2D u_tex; uniform float u_op; uniform int u_premul;
float mitchell(float x) {
    const float B = 1.0 / 3.0, C = 1.0 / 3.0;
    x = abs(x);
    if (x < 1.0) return ((12.0 - 9.0 * B - 6.0 * C) * x * x * x + (-18.0 + 12.0 * B + 6.0 * C) * x * x + (6.0 - 2.0 * B)) / 6.0;
    if (x < 2.0) return ((-B - 6.0 * C) * x * x * x + (6.0 * B + 30.0 * C) * x * x + (-12.0 * B - 48.0 * C) * x + (8.0 * B + 24.0 * C)) / 6.0;
    return 0.0;
}
void main() {
    vec2 texel = 1.0 / vec2(textureSize(u_tex, 0));
    vec2 px = v_uv / texel - 0.5; vec2 fr = fract(px); vec2 fl = floor(px);
    vec4 col = vec4(0.0); float ws = 0.0;
    for (int j = -1; j <= 2; j++) {
        float wy = mitchell(float(j) - fr.y);
        for (int i = -1; i <= 2; i++) {
            float w = mitchell(float(i) - fr.x) * wy;
            col += texture(u_tex, (fl + vec2(float(i), float(j)) + 0.5) * texel) * w; ws += w;
        }
    }
    vec4 c = col / max(ws, 1e-5);
    if (u_premul == 1) { f = c * u_op; }
    else { float a = clamp(c.a, 0.0, 1.0) * u_op; f = vec4(clamp(c.rgb, 0.0, 1.0) * a, a); }
}
"""

# the skinned mesh: u_bones holds 2 texels per bone (the two rows of its 2x3 matrix); index nb is the identity (parts without a bone)
_VS_MESH = """#version 330
in vec2 a_pos; in vec2 a_uv; in vec4 a_bi; in vec4 a_bw;
uniform sampler2D u_bones; uniform vec2 u_sc; uniform vec2 u_off;
out vec2 v_uv;
void main() {
    vec3 p3 = vec3(a_pos, 1.0); vec2 p = vec2(0.0);
    for (int k = 0; k < 4; k++) {
        float w = a_bw[k];
        if (w <= 0.0) continue;
        int b = int(a_bi[k] + 0.5);
        vec4 r0 = texelFetch(u_bones, ivec2(b * 2, 0), 0);
        vec4 r1 = texelFetch(u_bones, ivec2(b * 2 + 1, 0), 0);
        p += w * vec2(dot(r0.xyz, p3), dot(r1.xyz, p3));
    }
    gl_Position = vec4(p * u_sc + u_off, 0.0, 1.0);
    v_uv = a_uv;
}
"""

_FS_MESH = """#version 330
in vec2 v_uv; out vec4 f;
uniform sampler2D u_atlas; uniform float u_alpha;
void main() { f = texture(u_atlas, v_uv) * u_alpha; }
"""

_VS_FULL = """#version 330
in vec2 a_pos; out vec2 v_uv;
void main() { v_uv = a_pos; gl_Position = vec4(a_pos * 2.0 - 1.0, 0.0, 1.0); }
"""

_FS_UNPREM = """#version 330
in vec2 v_uv; out vec4 f;
uniform sampler2D u_tex;
void main() { vec4 c = texture(u_tex, v_uv); f = c.a > 0.0 ? vec4(min(c.rgb / c.a, 1.0), c.a) : vec4(0.0); }
"""


def _as_picture(img):
    """uint8, 3 or 4 channels, contiguous (what the textures take)."""
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 1:
        img = cv2.cvtColor(img[..., 0], cv2.COLOR_GRAY2BGRA)
    return np.ascontiguousarray(img)


class _SceneGL:
    """One rig on the GPU: atlas texture, vertex / index buffers, the bone matrix texture and the draw ranges."""

    def __init__(self, eng, rig, key):
        self.vao = self.vbo = self.ibo = self.tex = self.bones = None
        try: self._build(eng, rig, key)
        except BaseException:
            self.release(); raise                              # Patch 56: a half-built rig gave its atlas (64 MB+) back to nobody, once per frame

    def _build(self, eng, rig, key):
        from . import bone2d_gl as G
        ctx = eng.ctx
        sc = G.Scene(); _t = _rp.t0()
        sc.build_atlas(rig, min(eng.max_tex, 4096)); sc.build_geom(rig, (key, 0)); _rp.end("rig_build", _t)
        self.bone_ids = list(sc.bone_ids); self.nb = len(self.bone_ids); self.parts = list(sc.parts); self.n_verts = sc.M
        self.tex = None; self.vbo = None; self.ibo = None; self.vao = None; self.bones = None
        self._rest_ref = None; self._rest_inv = None
        atlas = sc.atlas; _t = _rp.t0()
        self.tex = ctx.texture((atlas.shape[1], atlas.shape[0]), 4, np.ascontiguousarray(atlas))      # RGBA, premultiplied
        try:
            self.tex.swizzle = "BGRA"                                                                    # shaders see storage order (B, G, R, A)
        except Exception:
            self.tex.release(); self.tex = ctx.texture((atlas.shape[1], atlas.shape[0]), 4, np.ascontiguousarray(atlas[..., [2, 1, 0, 3]]))
        self.tex.repeat_x = False; self.tex.repeat_y = False
        try: self.tex.anisotropy = 4.0
        except Exception: pass
        self.tex.build_mipmaps(); _rp.end("upload:rig_atlas", _t, atlas.nbytes); self.nbytes = int(atlas.nbytes * 1.34)
        sc.atlas = None                                       # the CPU copy is not needed any more (64 MB for a 4096 atlas)
        n = sc.M
        if n:
            vd = np.empty((n, 12), np.float32)
            vd[:, 0:2] = sc.P; vd[:, 2:4] = sc.UV; vd[:, 4:8] = sc.BI; vd[:, 8:12] = sc.BW
            self.vbo = ctx.buffer(vd.tobytes())
            idx = np.concatenate(sc.tris).astype(np.uint32) if sc.tris else np.zeros(0, np.uint32)
            self.ibo = ctx.buffer(idx.tobytes())
            self.vao = ctx.vertex_array(eng.p_mesh, [(self.vbo, "2f 2f 4f 4f", "a_pos", "a_uv", "a_bi", "a_bw")], self.ibo, 4)
            self.starts = np.r_[0, np.cumsum([len(t) for t in sc.tris])[:-1]].astype(np.int64) if sc.tris else np.zeros(0, np.int64)
            self.counts = np.array([len(t) for t in sc.tris], np.int64)
        else:
            self.starts = np.zeros(0, np.int64); self.counts = np.zeros(0, np.int64)
        self.bones = ctx.texture(((self.nb + 1) * 2, 1), 4, dtype="f4"); self.bones.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.bones.repeat_x = False; self.bones.repeat_y = False
        # opacity of every part (own alpha x folder alpha) and whether it is shown at all; these are fixed for a loaded file
        pm = {p["id"]: p for p in rig["parts"]}
        hid = {g["id"] for g in rig.get("groups", []) if g.get("hidden")}; ga = {g["id"]: g.get("alpha", 100.0) / 100.0 for g in rig.get("groups", [])}
        base = np.zeros(len(self.parts), np.float64)
        for k, pid in enumerate(self.parts):
            p = pm.get(pid)
            if p is None or not p.get("visible", True) or p.get("group") in hid: continue
            base[k] = max(0.0, min(1.0, p.get("alpha", 100.0) / 100.0 * ga.get(p.get("group"), 1.0)))
        self.base_ops = base; self._static = self._ranges(base)
        self.bytes = (atlas.nbytes if atlas is not None else 0) + n * 48

    def release(self):
        for o in (self.vao, self.vbo, self.ibo, self.tex, self.bones):
            try:
                if o is not None: o.release()
            except Exception: pass
        self.vao = self.vbo = self.ibo = self.tex = self.bones = None

    def _ranges(self, ops):
        """[(first index, index count, alpha)]: neighbouring parts with the same opacity are one draw call (usually the whole rig is one)."""
        out = []; cur = None
        for k in range(len(ops)):
            a = float(ops[k])
            if a <= 0.001: cur = None; continue
            s, c = int(self.starts[k]), int(self.counts[k])
            if cur is not None and abs(cur[2] - a) < 1e-4 and cur[0] + cur[1] == s: cur[1] += c
            else: cur = [s, c, a]; out.append(cur)
        return out

    def upload_pose(self, pose, rest):
        if self._rest_ref is not rest:
            I = np.eye(3)
            self._rest_inv = np.stack([np.linalg.inv(rest[b]) if b in rest else I for b in self.bone_ids]) if self.nb else np.zeros((0, 3, 3))
            self._rest_ref = rest
        nb = self.nb; data = np.zeros((nb + 1, 2, 4), np.float32); data[nb, 0, 0] = 1.0; data[nb, 1, 1] = 1.0
        if nb:
            I = np.eye(3)
            P = np.stack([pose[b] if (b in pose and b in rest) else I for b in self.bone_ids])
            # a bone that is missing in pose / rest is the identity (the same rule as Scene.skin): its inverse must not be applied
            ok = np.array([(b in pose and b in rest) for b in self.bone_ids])
            SM = np.where(ok[:, None, None], P @ self._rest_inv, I)
            data[:nb, 0, :3] = SM[:, 0, :]; data[:nb, 1, :3] = SM[:, 1, :]
        _t = _rp.t0(); self.bones.write(data.tobytes()); _rp.end("upload:pose", _t, data.nbytes)

    def draw_list(self, pa):
        if not pa: return self._static
        ops = self.base_ops.copy()
        for k, pid in enumerate(self.parts):
            v = pa.get(pid)
            if v is not None: ops[k] *= max(0.0, min(1.0, v))
        return self._ranges(ops)


class Engine:
    """Per thread: shaders, texture / scene caches and render targets of one moderngl context."""

    def __init__(self):
        self.ctx = acquire_context()
        try:
            info = self.ctx.info
            self.name = str(info.get("GL_RENDERER", "OpenGL"))
            if self.ctx.version_code < 330:
                raise RuntimeError("OpenGL %.1f is too old (3.3 needed)" % (self.ctx.version_code / 100.0))
            if any(w in self.name.lower() for w in _SOFT_WORDS) and not os.environ.get("MINICUT_MESHGL_SOFT"):
                raise RuntimeError("only software OpenGL is available (%s): the CPU is faster" % self.name)
            self.max_tex = int(info.get("GL_MAX_TEXTURE_SIZE", 4096) or 4096)
            # An integrated GPU (Intel UHD / Iris, Ryzen "Radeon Graphics") shares the system memory and has far less bandwidth: smaller texture
            # cache and 2x instead of 4x anti-aliasing. A discrete card gets the full settings.
            low = self.name.lower(); self.igpu = any(w in low for w in _IGPU_WORDS) and not any(w in low for w in ("geforce", "rtx", "gtx", "quadro", "radeon rx", "radeon pro", "arc a", "arc(tm) a"))
            self.export = is_export()
            self._build()
        except Exception:
            release_context(); raise
        self.mesh_ok = False; self.mesh_info = ""

    def _build(self):
        c = self.ctx
        self.quad = c.buffer(np.array([0, 0, 1, 0, 0, 1, 1, 1], np.float32).tobytes())
        self.p_lin = c.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_LIN)
        self.p_cub = c.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_CUB)
        self.v_lin = c.vertex_array(self.p_lin, [(self.quad, "2f", "a_pos")]); self.v_cub = c.vertex_array(self.p_cub, [(self.quad, "2f", "a_pos")])
        self.p_bld = c.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_BLEND); self.v_bld = c.vertex_array(self.p_bld, [(self.quad, "2f", "a_pos")]); self.bgt = OrderedDict()
        self.p_mesh = c.program(vertex_shader=_VS_MESH, fragment_shader=_FS_MESH)
        self.p_unp = c.program(vertex_shader=_VS_FULL, fragment_shader=_FS_UNPREM)
        self.v_unp = c.vertex_array(self.p_unp, [(self.quad, "2f", "a_pos")])
        self.texes = OrderedDict(); self.tex_bytes = 0; self._pinned = set()
        # Patch 51: the video-memory limit is worked out from what this machine says (vram.py / rmgr.py), no longer a fixed number. The RAM governor's
        # number (TEX_BUDGET, from "Max RAM") stays the cap for an integrated GPU and for a machine that says nothing.
        self.vram = VramInfo(self.name, getattr(c, "extensions", ()))
        _st = [-1e9, 0]
        def hard_cap():                                         # Patch 58: the ceiling for THIS machine (render/gpucap.py), refreshed once a second
            now = time.monotonic()
            if now - _st[0] > 1.0:
                tot, av = _gpucap.system_ram(); snap = self.rm.snapshot(self.vram_used())
                _st[0] = now; _st[1] = _gpucap.compute(snap, tot, av, os.environ.get("MINICUT_VRAM_CAP_MB"))
            return _st[1]
        self.hard_cap = hard_cap
        self.rm = ResourceManager(self.vram, export=self.export, hard_cap=hard_cap, ram_cap=lambda: (min(TEX_BUDGET[0], 48 * 2 ** 20) if self.export else TEX_BUDGET[0]) * (0.5 if self.igpu else 1.0))
        _LEDGER.cap_provider = hard_cap
        self.cp_pool = OrderedDict(); self.cp_ms = OrderedDict()
        self.aa_samples = 2 if self.igpu else 4
        self.pool = {}; self.n_pool = 0                       # free textures by (w, h, channels): uploading a new frame reuses one
        self.scenes = OrderedDict(); self.cv = OrderedDict(); self.rig_ms = OrderedDict(); self.rig_pool = {}; self.unp = OrderedDict()
        self.frames = 0

    # ───────────── video memory (Patch 51)
    def _target_bytes(self):
        """About how many bytes the render targets, pools and rig atlases hold (they cannot be given back in the middle of a frame)."""
        n = 0; s = self.aa_samples
        for (W, H, aa), hit in self.cv.items(): n += W * H * 4 * (2 + (s if aa else 0))
        for (W, H) in self.rig_ms: n += W * H * 4 * s
        for (W, H), lst in self.rig_pool.items(): n += len(lst) * W * H * 8
        for (W, H), lst in self.cp_pool.items(): n += len(lst) * W * H * 8
        for (W, H) in self.cp_ms: n += W * H * 4 * s
        for (W, H) in self.bgt: n += W * H * 4
        for (W, H) in self.unp: n += W * H * 4
        for (w, h, ch), lst in self.pool.items(): n += len(lst) * w * h * ch
        for sc in self.scenes.values(): n += getattr(sc, "nbytes", 0)
        fe = self._fx_engine()
        if fe is not None:
            for (w, h, c, dt), lst in fe.pool.items(): n += len(lst) * w * h * c * (2 if dt == "f2" else 1)
        return n

    def _fx_engine(self):
        """The effect engine of this thread (glfx), which shares this context; None when GL effects are off."""
        try:
            from . import glfx as _gx
            return getattr(_gx._TLS, "engine", None)
        except Exception:
            return None

    def vram_used(self):
        return self.tex_bytes + self._target_bytes()

    @property
    def tex_budget(self):
        """Bytes the picture-texture cache may hold now (the Resource Manager's limit minus the targets and pools)."""
        fixed = self._target_bytes()
        return self.rm.cache_budget(self.tex_bytes + fixed, fixed)

    def _evict_cache(self, budget):
        """Drop the oldest cached picture textures until the cache fits `budget`; never one that an earlier layer of the frame in progress still needs."""
        for k in list(self.texes):                                  # a picture that no longer exists (its weak reference is dead) can never be shown again
            if self.texes[k][0]() is None and id(self.texes[k][1]) not in self._pinned: self._drop(k)
        for k in list(self.texes):
            if self.tex_bytes <= budget: break
            if id(self.texes[k][1]) in self._pinned: continue
            self._drop(k)

    def _shrink(self):
        """After out-of-memory: give back everything that is not in use right now."""
        self._evict_cache(0)
        for pool in (self.pool, self.rig_pool, self.cp_pool):
            for lst in pool.values():
                for o in lst:
                    for x in (o if isinstance(o, tuple) else (o,)):
                        try: x.release()
                        except Exception: pass
                lst.clear()
        self.n_pool = 0; self.pool.clear(); self.rig_pool.clear(); self.cp_pool.clear()
        for res in self.bgt.values():
            for o in res:
                try: o.release()
                except Exception: pass
        self.bgt.clear()
        fe = self._fx_engine()
        if fe is not None:
            for lst in fe.pool.values():
                for t in lst: t.release()
            fe.pool.clear(); fe.n_pool = 0

    def _alloc(self, fn):
        """Make a GPU resource; when the driver says out of memory, take less from now on, give back what is idle and try once more."""
        try: return fn()
        except Exception as ex:
            if "memory" not in str(ex).lower(): raise
            _errors.report("gpu.memory", "GPU memory is nearly full", severity=_errors.MAJOR, fix="gave back idle caches and pools, then tried once more")
            if not self.export: _degrade.pressure("out of memory", severe=True)
            self.rm.note_oom(); self._shrink(); _rp.count("vram_oom")
            return fn()

    # ───────────── textures of the layers
    def _tex(self, w, h, ch):
        lst = self.pool.get((w, h, ch))
        if lst:
            self.n_pool -= 1; return lst.pop()
        t = self._alloc(lambda: self.ctx.texture((w, h), ch, alignment=1))
        t.repeat_x = False; t.repeat_y = False
        return t

    def _free(self, t, key):
        self.pool.setdefault(key, []).append(t); self.n_pool += 1
        while self.n_pool > 6:                               # sizes change (a resize): drop the oldest unused ones
            for k in list(self.pool):
                lst = self.pool[k]
                if lst:
                    lst.pop(0).release(); self.n_pool -= 1
                    if self.n_pool <= 6: break
                if not lst: del self.pool[k]

    def _upload(self, img, mip):
        h, w = img.shape[:2]; ch = img.shape[2]; t = self._tex(w, h, ch); _t = _rp.t0()
        t.write(img, alignment=1)
        if mip:
            t.build_mipmaps(); t.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        else:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        _rp.end("upload:texture", _t, img.nbytes); _rp.count("tex_upload")
        return t

    def _layer_tex(self, img, mip, cache):
        """(texture, key to give it back with or None when it stays in the cache)."""
        h, w = img.shape[:2]; ch = img.shape[2]; key = (w, h, ch)
        if cache:
            ent = self.texes.get(id(img))
            if ent is not None and ent[0]() is img and (ent[2] or not mip):
                self.texes.move_to_end(id(img)); self._pinned.add(id(ent[1])); _rp.count("tex_hit"); return ent[1], None
            if ent is not None:
                self._drop(id(img))
            t = self._upload(img, mip); nbytes = w * h * ch * (1.34 if mip else 1.0)
            try: ref = weakref.ref(img)
            except TypeError: return t, key
            self.texes[id(img)] = (ref, t, mip, key, nbytes); self.tex_bytes += nbytes; self._pinned.add(id(t))
            self._evict_cache(self.tex_budget)
            return t, None
        _rp.count("tex_nocache")
        t = self._upload(img, mip); self._pinned.add(id(t)); return t, key

    def _drop(self, k):
        ref, t, mip, key, nbytes = self.texes.pop(k); self.tex_bytes -= nbytes
        self._free(t, key)

    # ───────────── render targets
    def _canvas(self, W, H, aa):
        """(target to draw into, target to read). With anti-aliasing the first is multisampled and is resolved into the second."""
        key = (W, H, aa); hit = self.cv.get(key)
        if hit is not None:
            self.cv.move_to_end(key); return hit[0], hit[1]
        c = self.ctx
        out_rb = c.renderbuffer((W, H), 4); out = c.framebuffer(color_attachments=[out_rb]); ms = None; ms_rb = None
        if aa:
            for s in ((self.aa_samples if W * H <= 2300000 else 2), 2):
                try:
                    ms_rb = c.renderbuffer((W, H), 4, samples=s); ms = c.framebuffer(color_attachments=[ms_rb]); break
                except Exception:
                    ms = None
        draw = ms if ms is not None else out
        self.cv[key] = (draw, out, [o for o in (ms, ms_rb, out, out_rb) if o is not None])
        while len(self.cv) > 3:
            for o in self.cv.popitem(last=False)[1][2]:
                try: o.release()
                except Exception: pass
        return draw, out

    @staticmethod
    def _needs_aa(M, w, h, W, H):
        """Soft edges are needed when the picture is turned, or when an edge of it lies inside the frame on a part of a pixel."""
        if abs(M[0, 1]) > 1e-4 or abs(M[1, 0]) > 1e-4:
            return True
        x0, x1 = M[0, 2], M[0, 2] + M[0, 0] * w; y0, y1 = M[1, 2], M[1, 2] + M[1, 1] * h
        for e, hi in ((x0, W), (x1, W), (y0, H), (y1, H)):
            if 0.0 < e < hi and abs(e - round(e)) > 0.02:
                return True
        return False

    # ───────────── a rig
    def _scene(self, job):
        sc = self.scenes.get(job.key)
        if sc is not None:
            self.scenes.move_to_end(job.key); return sc
        sc = _SceneGL(self, job.rig, job.key); self.scenes[job.key] = sc
        while len(self.scenes) > 4:
            self.scenes.popitem(last=False)[1].release()
        return sc

    def _rig_target(self, W, H):
        c = self.ctx; key = (W, H); ms = self.rig_ms.get(key)
        if ms is None:
            fbo = None; rb = None
            for s in ((2, 0) if self.igpu else (4, 2, 0)):
                try:
                    rb = c.renderbuffer((W, H), 4, samples=s) if s else c.renderbuffer((W, H), 4); fbo = c.framebuffer(color_attachments=[rb]); break
                except Exception:
                    fbo = None
            if fbo is None: raise RuntimeError("no render target for the rig")
            ms = self.rig_ms[key] = (fbo, rb)
            while len(self.rig_ms) > 2:
                for o in self.rig_ms.popitem(last=False)[1]:
                    try: o.release()
                    except Exception: pass
        return ms[0]

    def _rig_to_tex(self, job):
        """Draw the rig into a texture (premultiplied). Returns (fbo, texture) taken from the pool; give it back with _rig_back()."""
        c = self.ctx; W, H = job.W, job.H
        if W > self.max_tex or H > self.max_tex: raise RuntimeError("rig picture too big for this GPU")
        sc = self._scene(job); _t = _rp.t0(); sc.upload_pose(job.pose, job.rest); _rp.end("rig_pose", _t)
        ms = self._rig_target(W, H); lst = self.rig_pool.setdefault((W, H), [])
        if lst: res = lst.pop()
        else:
            tex = c.texture((W, H), 4)
            try:
                tex.repeat_x = False; tex.repeat_y = False; tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                res = (c.framebuffer(color_attachments=[tex]), tex)
            except BaseException:
                tex.release(); raise                                  # Patch 56
        try: return self._rig_draw(job, sc, ms, res, W, H)
        except BaseException:
            for o in res:                                             # Patch 56: a failed draw dropped the target: 8 MB (1080p) lost per frame
                try: o.release()
                except Exception: pass
            raise

    def _rig_draw(self, job, sc, ms, res, W, H):
        c = self.ctx
        bg = job.bg
        ms.use(); ms.clear(*(((bg[2], bg[1], bg[0], bg[3])) if bg is not None else (0.0, 0.0, 0.0, 0.0)))
        draws = sc.draw_list(job.pa); _tr = _rp.t0(); _rp.count("rig_draw_calls", len(draws))
        if draws and sc.vao is not None:
            c.enable_only(moderngl.BLEND); c.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
            p = self.p_mesh; w0 = float(job.rig["w"]); h0 = float(job.rig["h"])
            p["u_sc"].value = (2.0 * job.ds / W, 2.0 * job.ds / H)                       # rig space (origin = middle, y down) -> clip space
            p["u_off"].value = (w0 * job.ds / W - 1.0, h0 * job.ds / H - 1.0)
            p["u_atlas"].value = 0; p["u_bones"].value = 1
            sc.tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR) if job.smooth else (moderngl.NEAREST, moderngl.NEAREST)
            sc.tex.use(0); sc.bones.use(1)
            with _rp.gpu_timer(c, "gpu:rig"):
                for first, count, alpha in draws:
                    p["u_alpha"].value = alpha
                    sc.vao.render(moderngl.TRIANGLES, vertices=count, first=first)
            c.disable(moderngl.BLEND)
        c.copy_framebuffer(res[0], ms); _rp.end("draw:rig", _tr)
        return res

    def _rig_back(self, job, res):
        lst = self.rig_pool.setdefault((job.W, job.H), [])
        if len(lst) < 3: lst.append(res)
        else:
            for o in (res[0], res[1]):
                try: o.release()
                except Exception: pass

    def render_rig_bgra(self, job):
        """The rig as a straight-alpha BGRA picture (W x H): for what is not composed on the GPU (effects, thumbnails, the CPU path)."""
        c = self.ctx; W, H = job.W, job.H
        res = self._rig_to_tex(job)
        try:
            key = (W, H); u = self.unp.get(key)
            if u is None:
                rb = c.renderbuffer((W, H), 4); u = self.unp[key] = (c.framebuffer(color_attachments=[rb]), rb)
                while len(self.unp) > 2:
                    for o in self.unp.popitem(last=False)[1]:
                        try: o.release()
                        except Exception: pass
            u[0].use(); c.disable(moderngl.BLEND); res[1].use(0); self.p_unp["u_tex"].value = 0; self.v_unp.render(moderngl.TRIANGLE_STRIP)
            out = np.empty((H, W, 4), np.uint8); _t = _rp.t0(); u[0].read_into(out, components=4, alignment=1); _rp.end("readback:rig", _t, out.nbytes)
        finally:
            self._rig_back(job, res)
        return out

    # ───────────── a frame
    def _prepare(self, layers, W, H, temps, rigs, comps, effs):
        """Make every layer ready to draw: upload its picture, draw its rig, draw its compound (children first). Returns (prep, aa)."""
        prep = []; aa = False
        for L in layers:
            obj, M, op = L[0], np.asarray(L[1], np.float64), float(L[2]); cache = bool(L[3]) if len(L) > 3 else False
            mode = L[4] if len(L) > 4 and L[4] in BLEND_IDS else "normal"
            if isinstance(obj, MeshJob):
                res = self._rig_to_tex(obj); rigs.append((obj, res)); tex = res[1]; w, h = obj.W, obj.H; premul = 1; mip = False
                sx_, sy_ = float(np.hypot(M[0, 0], M[1, 0])), float(np.hypot(M[0, 1], M[1, 1]))
            elif isinstance(obj, CompoundJob):
                res = self._compound_to_tex(obj, temps, rigs, comps, effs); comps.append((obj, res)); tex = res[1]; w, h = obj.W, obj.H; premul = 1; mip = False
                self._pinned.add(id(tex)); sx_, sy_ = float(np.hypot(M[0, 0], M[1, 0])), float(np.hypot(M[0, 1], M[1, 1]))
            elif isinstance(obj, EffectJob):
                ft = self._effect_to_tex(obj, temps, rigs, comps, effs); tex = ft.tex; w, h = obj.W, obj.H; premul = 0; mip = False      # effects give straight alpha
                self._pinned.add(id(tex)); sx_, sy_ = float(np.hypot(M[0, 0], M[1, 0])), float(np.hypot(M[0, 1], M[1, 1]))
            else:
                img = _as_picture(obj); h, w = img.shape[:2]
                if w <= 0 or h <= 0: continue
                sx_, sy_ = float(np.hypot(M[0, 0], M[1, 0])), float(np.hypot(M[0, 1], M[1, 1]))
                if max(w, h) > self.max_tex:                  # a picture bigger than the GPU takes: shrink it (and say so to the matrix)
                    f = self.max_tex / float(max(w, h)); nw, nh = max(1, int(w * f)), max(1, int(h * f))
                    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA); M = M.copy(); M[:, 0] *= w / float(nw); M[:, 1] *= h / float(nh); w, h = nw, nh
                mip = max(sx_, sy_) < 0.75 and min(w, h) >= 4; premul = 0
                tex, back = self._layer_tex(img, mip, cache)
                if back is not None: temps.append((tex, back))
            cubic = (not mip) and min(sx_, sy_) > 1.05 and not os.environ.get("MINICUT_NO_BICUBIC")
            if self._needs_aa(M, w, h, W, H): aa = True
            prep.append((tex, w, h, M, op, premul, cubic, mode))
        return prep, aa

    def _bg_copy(self, W, H):
        """A texture to copy the target into, for a layer that reads what is under it (blend modes)."""
        key = (W, H); hit = self.bgt.get(key)
        if hit is None:
            def make():
                t = self.ctx.texture((W, H), 4); t.repeat_x = False; t.repeat_y = False; t.filter = (moderngl.NEAREST, moderngl.NEAREST)
                return (self.ctx.framebuffer(color_attachments=[t]), t)
            hit = self._alloc(make); self.bgt[key] = hit
            while len(self.bgt) > 2:
                for o in self.bgt.popitem(last=False)[1]:
                    try: o.release()
                    except Exception: pass
        else: self.bgt.move_to_end(key)
        return hit

    def _draw_prepped(self, prep, W, H, stage, target=None):
        """Draw the prepared layers, bottom first, with premultiplied 'over' blending, into the bound target. With `target` (an OPAQUE frame) a layer
        with a blend mode is drawn by the blend shader, which reads a copy of the target; without it (a compound, which is transparent) modes count as normal."""
        if not prep: return
        c = self.ctx
        c.enable_only(moderngl.BLEND); c.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
        with _rp.gpu_timer(c, stage):
            for tex, w, h, M, op, premul, cubic, mode in prep:
                if mode != "normal" and target is not None:
                    bg = self._bg_copy(W, H); c.copy_framebuffer(bg[0], target); target.use(); c.disable(moderngl.BLEND)
                    p, v = self.p_bld, self.v_bld
                    p["u_size"].value = (float(w), float(h)); p["u_frame"].value = (float(W), float(H))
                    p["u_r0"].value = (float(M[0, 0]), float(M[0, 1]), float(M[0, 2])); p["u_r1"].value = (float(M[1, 0]), float(M[1, 1]), float(M[1, 2]))
                    p["u_op"].value = op; p["u_premul"].value = premul; p["u_mode"].value = BLEND_IDS[mode]; p["u_tex"].value = 0; p["u_bg"].value = 1
                    tex.use(0); bg[1].use(1); v.render(moderngl.TRIANGLE_STRIP); _rp.count("blend_gpu")
                    c.enable_only(moderngl.BLEND); c.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
                    continue
                p, v = (self.p_cub, self.v_cub) if cubic else (self.p_lin, self.v_lin)
                p["u_size"].value = (float(w), float(h)); p["u_frame"].value = (float(W), float(H))
                p["u_r0"].value = (float(M[0, 0]), float(M[0, 1]), float(M[0, 2])); p["u_r1"].value = (float(M[1, 0]), float(M[1, 1]), float(M[1, 2]))
                p["u_op"].value = op; p["u_premul"].value = premul; p["u_tex"].value = 0
                tex.use(0); v.render(moderngl.TRIANGLE_STRIP)
        c.disable(moderngl.BLEND)

    # ───────────── compound clips (a sub-frame drawn on the GPU)
    def _comp_ms(self, W, H):
        key = (W, H); hit = self.cp_ms.get(key)
        if hit is not None:
            self.cp_ms.move_to_end(key); return hit[0]
        c = self.ctx; fbo = None; rb = None
        for sm in ((2, 0) if self.igpu else (4, 2, 0)):
            try:
                rb = self._alloc(lambda: c.renderbuffer((W, H), 4, samples=sm) if sm else c.renderbuffer((W, H), 4)); fbo = c.framebuffer(color_attachments=[rb]); break
            except Exception:
                fbo = None
        if fbo is None: raise RuntimeError("no render target for the compound")
        self.cp_ms[key] = (fbo, rb)
        while len(self.cp_ms) > 2:
            for o in self.cp_ms.popitem(last=False)[1]:
                try: o.release()
                except Exception: pass
        return fbo

    def _compound_to_tex(self, job, temps, rigs, comps, effs):
        """Draw a compound into a premultiplied texture (taken from the pool; give it back with _comp_back). Its children are made first."""
        c = self.ctx; W, H = job.W, job.H
        if W > self.max_tex or H > self.max_tex: raise RuntimeError("compound picture too big for this GPU")
        _t0 = _rp.t0()
        prep, aa = self._prepare(job.layers, W, H, temps, rigs, comps, effs)
        lst = self.cp_pool.get((W, H))
        if lst: res = lst.pop()
        else:
            def make():
                tex = c.texture((W, H), 4); tex.repeat_x = False; tex.repeat_y = False; tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                return (c.framebuffer(color_attachments=[tex]), tex)
            res = self._alloc(make)
        draw = self._comp_ms(W, H) if aa else res[0]
        draw.use(); draw.clear(0.0, 0.0, 0.0, 0.0)
        self._draw_prepped(prep, W, H, "gpu:compound")
        if aa: c.copy_framebuffer(res[0], draw)
        _rp.end("draw:compound", _t0); _rp.count("compound_gpu_nodes")
        return res

    def _effect_to_tex(self, job, temps, rigs, comps, effs):
        """Run the effect passes of a layer on the GPU and return the result (a glfx _Tex, given back to the effect engine at the end of the frame)."""
        from .glfx import _Tex, Pass
        fe = self._fx_engine()
        if fe is None: raise RuntimeError("GL effects are not active on this thread")
        _t0 = _rp.t0(); s = job.src; groups = job.groups
        if isinstance(s, MeshJob):
            res = self._rig_to_tex(s); rigs.append((s, res)); st = _Tex(res[1], s.W, s.H, 4); groups = [[Pass(_UNPREMUL)]] + groups
        elif isinstance(s, CompoundJob):
            res = self._compound_to_tex(s, temps, rigs, comps, effs); comps.append((s, res)); st = _Tex(res[1], s.W, s.H, 4); groups = [[Pass(_UNPREMUL)]] + groups
        else:
            img = _as_picture(s); h, w = img.shape[:2]
            if max(w, h) > self.max_tex: raise RuntimeError("picture too big for the GPU effects")
            tex, back = self._layer_tex(img, False, job.cache)
            if back is not None: temps.append((tex, back))
            st = _Tex(tex, w, h, img.shape[2])
        extra = {}
        for name, plane in job.planes.items():
            mt, back = self._layer_tex(plane, False, True); extra[name] = _Tex(mt, plane.shape[1], plane.shape[0], 1)
            if back is not None: temps.append((mt, back))
        with _rp.gpu_timer(self.ctx, "gpu:effects"):
            main = fe.run_tex(st, groups, extra)
        effs.append((fe, main)); _rp.end("draw:effects", _t0); _rp.count("effect_gpu_nodes")
        return main

    def _comp_back(self, job, res):
        lst = self.cp_pool.setdefault((job.W, job.H), [])
        if len(lst) < 3: lst.append(res)
        else:
            for o in (res[0], res[1]):
                try: o.release()
                except Exception: pass
        while len(self.cp_pool) > 4:                          # sizes change (a resize): drop the oldest sizes
            for old in self.cp_pool.popitem(last=False)[1]:
                for o in old:
                    try: o.release()
                    except Exception: pass

    def composite(self, layers, W, H, bgr):
        """layers: [(picture or MeshJob or CompoundJob, M (2x3: picture px -> frame px), opacity[, cache])], bottom first. Returns the frame, BGR uint8 (H, W, 3).
        cache=True: the picture does not change (a still image, text): its texture is kept for the next frame."""
        c = self.ctx; W = int(W); H = int(H); _tc = _rp.t0()
        if W > self.max_tex or H > self.max_tex: raise RuntimeError("frame too big for this GPU")
        temps = []; rigs = []; comps = []; effs = []; _rp.count("layers", len(layers)); self._pinned.clear()
        try:
            self._evict_cache(self.tex_budget)                     # the limit may have dropped since the last frame (another program took video memory)
            prep, aa = self._prepare(layers, W, H, temps, rigs, comps, effs)
            draw, out = self._canvas(W, H, aa); _td = _rp.t0()
            draw.use(); draw.clear(bgr[0] / 255.0, bgr[1] / 255.0, bgr[2] / 255.0, 1.0)         # storage order: the red channel of the target holds B
            self._draw_prepped(prep, W, H, "gpu:composite", target=draw)
            if draw is not out: c.copy_framebuffer(out, draw)
            _rp.end("draw:layers", _td); _tr = _rp.t0()
            buf = np.empty((H, W, 3), np.uint8); out.read_into(buf, components=3, alignment=1); _rp.end("readback:frame", _tr, buf.nbytes)
            self.frames += 1; _rp.end("composite", _tc)
            if _rp.on:
                st = self.rm.stats(self.vram_used()); _rp.note("tex_cache_mb", round(self.tex_bytes / 1e6)); _rp.note("vram_source", st["source"])
                _rp.note("vram_used_mb", int(round(st["used_mb"] / 10.0) * 10)); _rp.note("vram_allowed_mb", int(round(st["allowed_mb"] / 50.0) * 50))
            return buf
        finally:
            self._pinned.clear()
            for tex, key in temps: self._free(tex, key)
            for job, res in rigs: self._rig_back(job, res)
            for job, res in comps: self._comp_back(job, res)
            for fe, t in effs: fe.free(t)

    # ───────────── start-up test
    def self_test(self):
        from .gpu import test_scene, reference_composite
        layers, W, H, bgr = test_scene()
        ref = reference_composite(layers, W, H, bgr).astype(np.int16)
        out = self.composite([(a, M, op) for a, M, op in layers], W, H, bgr)
        if out is None or out.shape != (H, W, 3):
            return False, "the GPU returned a picture of the wrong size"
        # the edges of a picture are softened by the CPU warp and not by the GPU, so edge pixels are counted apart: a flipped or
        # colour-swapped picture differs over whole areas, an edge only along a line
        diff = np.abs(out.astype(np.int16) - ref).max(2); big = float((diff > 40).mean()); d = float(diff[diff <= 40].mean()) if (diff <= 40).any() else 0.0
        if big > 0.04 or d > 3.0:
            return False, "the GPU picture does not match the CPU picture (%.1f%% of the pixels differ, mean %.1f)" % (big * 100.0, d)
        try:
            self.mesh_ok = bool(self._mesh_test())
        except Exception as ex:
            self.mesh_ok = False; self.mesh_info = repr(ex)
            try:
                from .debug_trace import trace_event
                trace_event("meshgl_mesh_test_failed", error=repr(ex))
            except Exception:
                pass
        return True, "matches the CPU picture (edges %.1f%%, mean %.2f)" % (big * 100.0, d)

    def _mesh_test(self):
        """A small skinned rig drawn by the GPU must look like the CPU drawing of it."""
        from . import bone2d as B
        im = np.zeros((48, 64, 4), np.uint8)
        yy, xx = np.mgrid[0:48, 0:64]
        im[..., 0] = xx * 4; im[..., 1] = yy * 5; im[..., 2] = 255 - xx * 3; im[..., 3] = 255; im[:6, :6] = (255, 255, 255, 255)
        r = B.new_rig("selftest", 128, 128); r["images"]["i1"] = B.image_entry_array(im)
        r["parts"] = [{"id": "p1", "name": "p", "img": "i1", "bone": "b1", "x": 6.0, "y": -4.0, "rot": 15.0, "sx": 100.0, "sy": 100.0, "z": 0, "alpha": 100.0}]
        r["bones"] = [{"id": "b1", "name": "b", "parent": None, "x": 0.0, "y": 0.0, "rot": 0.0, "len": 40.0}]
        B.fix_rig(r); a = r["anims"][0]; a["tracks"] = {"b1": {"rot": [{"t": 0.0, "v": 28.0, "e": [0, 0, 1, 1]}]}}
        rest = B.rest_world(r); pose = B.pose_world(r, a, 0.0, rest)
        job = MeshJob(r, ("meshgl-selftest", id(r)), pose, rest, None, 128, 128, 1.0, True, None)
        gl = self.render_rig_bgra(job); cpu = B.render_pose(r, pose, rest, 1.0, None, True, None)
        both = (gl[..., 3] > 200) & (cpu[..., 3] > 200)
        self.mesh_info = "overlap %d px" % int(both.sum())
        if both.sum() < 500: return False
        d = float(np.abs(gl[..., :3][both].astype(np.int16) - cpu[..., :3][both].astype(np.int16)).mean())
        cover = float(np.abs(gl[..., 3].astype(np.int16) - cpu[..., 3].astype(np.int16)).mean())
        sc_ = self.scenes.pop(job.key, None)
        if sc_ is not None: sc_.release()
        self.mesh_info = "overlap %d px, colour diff %.1f, alpha diff %.1f" % (int(both.sum()), d, cover)
        return d < 10.0 and cover < 6.0

    def close(self):
        try:
            for sc in self.scenes.values(): sc.release()
            for ent in self.texes.values():
                try: ent[1].release()
                except Exception: pass
            for lst in self.pool.values():
                for t in lst:
                    try: t.release()
                    except Exception: pass
            for hit in self.cv.values():
                for o in hit[2]:
                    try: o.release()
                    except Exception: pass
            for hit in list(self.rig_ms.values()) + list(self.unp.values()):
                for o in hit:
                    try: o.release()
                    except Exception: pass
            for lst in list(self.rig_pool.values()) + list(self.cp_pool.values()):
                for res in lst:
                    for o in res:
                        try: o.release()
                        except Exception: pass
            for hit in list(self.cp_ms.values()) + list(self.bgt.values()):
                for o in hit:
                    try: o.release()
                    except Exception: pass
            self.vram.close()
        except Exception:
            pass
        self.scenes.clear(); self.texes.clear(); self.pool.clear(); self.cv.clear(); self.rig_ms.clear(); self.unp.clear(); self.rig_pool.clear(); self.cp_pool.clear(); self.cp_ms.clear()
        release_context()

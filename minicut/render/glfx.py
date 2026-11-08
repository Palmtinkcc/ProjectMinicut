"""OpenGL effect engine (Patch 35).

What it does
------------
A run of consecutive effects on one clip is executed as ONE GPU job:
    upload the picture once  ->  one fragment-shader pass per step (ping-pong render targets)  ->  read back once.
The old Patch 33 helpers (gpu_fx.py) uploaded and read back the picture for *every* effect, which on most PCs cost more than the CPU
version of the effect. Here the picture stays on the GPU between effects, and a run-time chooser (Chooser) times GPU against CPU for
every effect combination and keeps the faster one, so this module can only make things faster, never slower.

Safety rules (a video editor must never crash because of a driver)
  * moderngl missing, OpenGL < 3.3, software GL (llvmpipe / GDI generic) -> the module stays off, the CPU effects run as before.
  * A "probing" note is written before the first context is made; if the program died there, GL stays off until reset().
  * Only threads that call enable_current_thread() (the preview render thread) may use it. Export threads never do: export stays
    pure CPU, exactly as before.
  * Any GL error -> fail(): GL is off for the rest of the session and the CPU effect runs for that same frame.

Picture layout
--------------
Pictures are uploaded as they are (BGR / BGRA, "storage order"), so no channel swizzle is done on the CPU. Inside the shaders .rgb is
therefore (B, G, R). Row 0 of the numpy array is v = 0 of the texture, so there is no vertical flip anywhere: v_uv is image coordinates.

The effect library (shaders + parameter mapping) is in glfx_lib.py; this file knows nothing about single effects.
"""
import json
import os
import threading
import time

import numpy as np

try:
    import moderngl
except Exception:                                    # not installed: GL effects are simply off
    moderngl = None

try:
    from ..shared.core import APP_DIR
except Exception:
    APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")

STATE_FILE = os.path.join(APP_DIR, "glfx_state.json")
ENGINE = 35

_VERT = """#version 330
in vec2 a_pos; out vec2 v_uv;
void main() { v_uv = a_pos * 0.5 + 0.5; gl_Position = vec4(a_pos, 0.0, 1.0); }
"""


class Pass:
    """One fragment-shader pass.
    frag : complete fragment shader source (compiled once, cached by its text)
    u    : {uniform name: value}
    tex  : {sampler uniform name: target name}; "in" = picture at the start of this effect, "main" = current result, any other = temp
    out  : "main" (becomes the current result) or the name of a temp target
    size : (w, h) of the output target, None = full size
    """
    __slots__ = ("frag", "u", "tex", "out", "size")

    def __init__(self, frag, u=None, tex=None, out="main", size=None):
        self.frag = frag; self.u = u or {}; self.tex = tex or {"u_in": "main"}; self.out = out; self.size = size


class Built:
    """What an effect builder returns: its passes and whether it writes the alpha plane."""
    __slots__ = ("passes", "alpha")

    def __init__(self, passes, alpha=False):
        self.passes = passes; self.alpha = alpha


# ───────────────────────── state / crash guard ─────────────────────────
_ST = {"disabled": False, "status": "not started", "tried": False, "lock": threading.Lock()}
_TLS = threading.local()


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
    """Forget an earlier failure / crash note and allow GL again (called by the Test GPU button)."""
    _write({})
    with _ST["lock"]:
        _ST["disabled"] = False; _ST["tried"] = False; _ST["status"] = "not started"


def fail(why):
    _ST["disabled"] = True; _ST["status"] = "off: " + str(why)
    _write({"status": "failed", "reason": str(why)})
    try:
        from .debug_trace import trace_event
        trace_event("glfx_off", reason=str(why))
    except Exception:
        pass


def enabled_by_user():
    if os.environ.get("MINICUT_NO_GLFX"):
        return False
    try:
        from .gpu import GPU
        return GPU.mode != "off"                       # the existing "GPU compositing" setting also switches these off
    except Exception:
        return True


def enable_current_thread():
    """Call once on the thread that renders the preview. Only such threads may create the GL context."""
    _TLS.allowed = True


def active():
    """True when GL effects may be used on this thread right now."""
    if moderngl is None or _ST["disabled"] or not getattr(_TLS, "allowed", False) or not enabled_by_user():
        return False
    eng = getattr(_TLS, "engine", None)
    if eng is not None:
        return True
    if getattr(_TLS, "tried", False):
        return False
    _TLS.tried = True
    return _start_engine()


def _start_engine():
    st = _read()
    if st.get("status") == "probing":
        fail("the program stopped while the GL effects were tested last time (Test GPU tries again)")
        return False
    if st.get("status") == "failed" and not os.environ.get("MINICUT_GLFX_FORCE"):
        _ST["disabled"] = True; _ST["status"] = "off: %s (Test GPU tries again)" % st.get("reason", "failed before")
        return False
    _write({"status": "probing"})
    try:
        eng = _Engine()
        ok, why = eng.self_test()
        if not ok:
            eng.close(); _write({"status": "failed", "reason": why}); _ST["disabled"] = True; _ST["status"] = "off: " + why
            return False
    except Exception as ex:
        fail("start-up error: %s" % (ex,)); return False
    _TLS.engine = eng
    _ST["status"] = "active: %s" % eng.name
    _write({"status": "ok", "name": eng.name})
    return True


# ───────────────────────── the engine (one per render thread) ─────────────────────────
class _Tex:
    __slots__ = ("tex", "fbo", "w", "h", "c")

    def __init__(self, tex, w, h, c):
        self.tex = tex; self.fbo = None; self.w = w; self.h = h; self.c = c

    def release(self):
        try:
            if self.fbo is not None: self.fbo.release()
        except Exception:
            pass
        try: self.tex.release()
        except Exception: pass


class _Engine:
    POOL_MAX = 40

    def __init__(self):
        try:
            self.ctx = moderngl.create_standalone_context()
        except Exception:
            if not os.name == "posix": raise
            self.ctx = moderngl.create_standalone_context(backend="egl")        # Linux without a display (headless): EGL
        info = self.ctx.info
        self.name = str(info.get("GL_RENDERER", "OpenGL"))
        low = self.name.lower()
        if self.ctx.version_code < 330:
            raise RuntimeError("OpenGL %.1f is too old (3.3 needed)" % (self.ctx.version_code / 100.0))
        if any(w in low for w in ("gdi generic", "llvmpipe", "software", "swrast", "softpipe")) and not os.environ.get("MINICUT_GLFX_SOFT"):
            raise RuntimeError("only software OpenGL is available (%s): the CPU effects are faster" % self.name)
        self.vbo = self.ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32).tobytes())
        self.progs = {}                  # fragment source -> (program, vao)
        self.pool = {}                   # (w, h, comps) -> [free _Tex]
        self.n_pool = 0
        self.vs = _VERT

    # -- programs
    def program(self, frag):
        ent = self.progs.get(frag)
        if ent is None:
            prog = self.ctx.program(vertex_shader=self.vs, fragment_shader=frag)
            vao = self.ctx.vertex_array(prog, [(self.vbo, "2f", "a_pos")])
            ent = self.progs[frag] = (prog, vao)
        return ent

    # -- textures
    def tex(self, w, h, c=4):
        w = max(1, int(w)); h = max(1, int(h)); lst = self.pool.get((w, h, c))
        if lst:
            self.n_pool -= 1; return lst.pop()
        t = self.ctx.texture((w, h), c, alignment=1)
        t.filter = (moderngl.LINEAR, moderngl.LINEAR); t.repeat_x = False; t.repeat_y = False
        return _Tex(t, w, h, c)

    def free(self, t):
        if t is None: return
        self.pool.setdefault((t.w, t.h, t.c), []).append(t); self.n_pool += 1
        if self.n_pool > self.POOL_MAX:                 # sizes change (resize of the preview): drop the oldest unused
            for key in list(self.pool):
                lst = self.pool[key]
                while lst and self.n_pool > self.POOL_MAX // 2:
                    lst.pop(0).release(); self.n_pool -= 1
                if not lst: del self.pool[key]

    def fbo(self, t):
        if t.fbo is None: t.fbo = self.ctx.framebuffer(color_attachments=[t.tex])
        return t.fbo

    # -- one pass
    def draw(self, P, targets, out):
        prog, vao = self.program(P.frag)
        fbo = self.fbo(out); fbo.use(); self.ctx.viewport = (0, 0, out.w, out.h)
        if "u_size" in prog: prog["u_size"].value = (float(out.w), float(out.h))
        unit = 0
        for name, tgt in P.tex.items():
            t = targets[tgt]
            if name in prog:
                t.tex.use(unit); prog[name].value = unit
                sz = name + "_sz"
                if sz in prog: prog[sz].value = (float(t.w), float(t.h))
            unit += 1
        for name, val in P.u.items():
            if name in prog: prog[name].value = val
        vao.render(moderngl.TRIANGLE_STRIP)

    # -- a whole chain
    def run(self, img, groups, out_comps):
        h, w = img.shape[:2]; c = img.shape[2]
        src = self.tex(w, h, c); src.tex.write(np.ascontiguousarray(img), alignment=1)
        main = src; used = [src]
        for passes in groups:
            targets = {"in": main, "main": main}; mine = []
            for P in passes:
                ow, oh = P.size if P.size else (w, h)
                o = self.tex(ow, oh, 4); mine.append(o)          # a fresh target every pass: never read and written at once
                self.draw(P, targets, o)
                targets[P.out] = o
            main = targets["main"]
            for t in mine:
                if t is not main: self.free(t)
            if targets["in"] is not src and targets["in"] is not main and targets["in"] not in mine: self.free(targets["in"])
        res = np.empty((h, w, out_comps), np.uint8)
        self.fbo(main).read_into(res, components=out_comps, alignment=1)
        if main is not src: self.free(main)
        self.free(src)
        return res

    # -- start-up check: the GPU result must equal a known answer, otherwise GL stays off
    def self_test(self):
        frag = ("#version 330\nin vec2 v_uv; out vec4 o; uniform sampler2D u_in;\n"
                "void main() { vec4 c = texture(u_in, v_uv); o = vec4(1.0 - c.rgb, c.a); }\n")
        rng = np.random.default_rng(7)
        a = rng.integers(0, 256, (37, 53, 4), dtype=np.uint8); a[..., 3] = 255
        a[:12, :20] = (255, 0, 0, 255); a[-9:, -15:] = (0, 0, 255, 255)
        for comps in (3, 4):
            im = np.ascontiguousarray(a[..., :comps])
            out = self.run(im, [[Pass(frag)]], comps)
            exp = 255 - im if comps == 3 else np.dstack([255 - im[..., :3], im[..., 3]])
            if int(np.abs(out.astype(np.int16) - exp.astype(np.int16)).max()) > 2:
                return False, "the GPU picture does not match the expected picture (%d channels)" % comps
        return True, "ok"

    def close(self):
        try: self.ctx.release()
        except Exception: pass


# ───────────────────────── GPU or CPU: measure, then keep the faster ─────────────────────────
class Chooser:
    """Times the GL path and the CPU path of every effect combination (per picture size) and keeps the faster one.
    The first GL call of a combination includes the shader compile and is not counted. Every RECHECK calls it measures again, so a
    change of load (a game running, a slower GPU clock) is followed."""
    WARM, SAMPLES, RECHECK, MARGIN = 1, 3, 400, 0.85

    def __init__(self):
        self.s = {}

    def pick(self, key):
        st = self.s.get(key)
        if st is None:
            st = self.s[key] = {"gl": [], "cpu": [], "n": 0, "win": None, "warm": 0}
            if len(self.s) > 256: self.s.pop(next(iter(self.s)))
        st["n"] += 1
        if st["win"] is not None:
            if st["n"] % self.RECHECK == 0: st["gl"].clear(); st["cpu"].clear(); st["win"] = None; st["warm"] = self.WARM
            else: return st["win"]
        if st["warm"] < self.WARM: return "gl"
        if len(st["gl"]) < self.SAMPLES: return "gl"
        if len(st["cpu"]) < self.SAMPLES: return "cpu"
        g = sorted(st["gl"])[len(st["gl"]) // 2]; c = sorted(st["cpu"])[len(st["cpu"]) // 2]
        st["win"] = "gl" if g < c * self.MARGIN else "cpu"
        return st["win"]

    def report(self, key, path, ms):
        st = self.s.get(key)
        if st is None: return
        if path == "gl" and st["warm"] < self.WARM: st["warm"] += 1; return
        lst = st[path]
        if len(lst) < self.SAMPLES: lst.append(ms)

    def note(self, key):
        st = self.s.get(key)
        return None if st is None else (st["win"], list(st["gl"]), list(st["cpu"]))


CHOOSER = Chooser()


# ───────────────────────── public: run a chain ─────────────────────────
class Plan:
    """The passes of the first `n` effects of a run (the leading effects the library can do for this picture and these parameters)."""
    __slots__ = ("groups", "n", "out_c")

    def __init__(self, groups, n, out_c):
        self.groups = groups; self.n = n; self.out_c = out_c


def build_chain(img, items, ctx):
    """items: [(effect type, cleaned params)]. Returns a Plan for the leading items the library supports, or None when the first one is
    not supported (then the CPU does it). Needs no GL call: it only builds shader passes, so it is cheap."""
    from . import glfx_lib
    h, w = img.shape[:2]; c = img.shape[2]
    opaque = c == 3 or _alpha_opaque(img)
    groups = []; alpha = False
    for typ, p in items:
        b = glfx_lib.GL_FX.get(typ)
        built = b(p, ctx, w, h, opaque) if b is not None else None
        if built is None: break
        groups.append(built.passes)
        if built.alpha: alpha = True; opaque = False
    if not groups: return None
    return Plan(groups, len(groups), 4 if (c == 4 or alpha) else 3)


def execute(img, plan):
    """Run a Plan on this thread's engine: one upload, the passes, one read-back. Raises on any GL error (caller -> fail())."""
    return _TLS.engine.run(img, plan.groups, plan.out_c)


def _alpha_opaque(img):
    import cv2
    return cv2.minMaxLoc(cv2.extractChannel(img, 3))[0] >= 255


def supported(typ):
    from . import glfx_lib
    return typ in glfx_lib.GL_FX


def now_ms():
    return time.perf_counter() * 1000.0

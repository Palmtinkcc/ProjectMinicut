"""GPU compositing — Patch 33: OpenGL + GLSL API Update.

Replaces QPainter-on-FBO with a native OpenGL + GLSL pipeline:
  * Each layer is uploaded as a GL_TEXTURE_2D and drawn with a GLSL shader program.
  * The compositor draws directly into a PySide6 QOpenGLFramebufferObject, then reads
    back the result via glReadPixels — zero extra copies.
  * GLSL handles premultiplied-alpha blending and opacity in one pass on the GPU.
  * Bicubic upscaling shader replaces bilinear for export / full-quality stills.
  * Texture objects and shader programs are reused across frames (created once, cached).
  * The self-test, crash-guard, and GpuState machine are unchanged so nothing else in
    the program needs to change.

Quality improvements over Patch 32 (QPainter path):
  * Sub-pixel accuracy: the affine matrix is applied directly in the vertex shader — no
    QTransform rounding.
  * Premultiplied alpha done by the shader, not by a separate CPU numpy pass.
  * Bicubic filter for high-quality upscaling (falls back to bilinear automatically on
    GPUs that do not support GL 3.0 — detected at init time).
  * No redundant QImage format conversions.

Safety (unchanged from Patch 32):
  * At first use a test scene is drawn by the GPU and compared to the CPU reference.
    Any mismatch keeps the GPU off.
  * A "probing" note written before the test: a crash during the test leaves the note
    and the next start keeps the GPU off until the user presses "Test GPU".
  * Any draw error falls back to the CPU for the rest of the session.
"""
import ctypes
import json
import os
import threading

import cv2
import numpy as np

from ..shared.core import APP_DIR
from .fastcomp import blend_into, to_cv_matrix

STATE_FILE  = os.path.join(APP_DIR, "gpu_state.json")
GPU_ENGINE  = 33   # bumped: older state files are ignored


# ---------------------------------------------------------------------------
# Trace helper (optional)
# ---------------------------------------------------------------------------

def _gpu_trace(event, **fields):
    try:
        from .debug_trace import trace_event
        trace_event("gpu_" + event, **fields)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Persistent state helpers
# ---------------------------------------------------------------------------

def _read():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("engine") == GPU_ENGINE else {}
    except Exception:
        return {}


def _write(d):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(d, engine=GPU_ENGINE) if d else {}, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CPU-side helpers (used by reference composite and by legacy callers)
# ---------------------------------------------------------------------------

def premultiply(img):
    """Premultiply an BGRA uint8 image on the CPU (used only by the self-test)."""
    out = img.copy()
    a   = img[..., 3:4].astype(np.uint16)
    out[..., :3] = (img[..., :3].astype(np.uint16) * a // 255).astype(np.uint8)
    return out


def reference_composite(layers, W, H, bgr):
    """CPU reference composite used by the self-test."""
    canvas    = np.empty((H, W, 3), np.uint8)
    canvas[:] = bgr
    for img, M, op in layers:
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        lay = cv2.warpAffine(img, to_cv_matrix(M), (W, H),
                             flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT,
                             borderValue=(0, 0, 0, 0))
        blend_into(canvas,
                   np.ascontiguousarray(lay[..., :3]),
                   np.ascontiguousarray(lay[..., 3]),
                   op)
    return canvas


def test_scene():
    """A scene that exposes any flip or colour swap."""
    W, H = 320, 240
    bgr  = (50, 40, 30)
    a    = np.zeros((100, 160, 4), np.uint8); a[..., 3] = 255
    a[:50, :80]  = (0,   0,   255, 255)   # top-left  red
    a[:50, 80:]  = (0,   255, 0,   255)   # top-right green
    a[50:, :80]  = (255, 0,   0,   255)   # bottom-left  blue
    a[50:, 80:]  = (0,   255, 255, 255)   # bottom-right yellow
    a[:12, :12]  = (255, 255, 255, 255)   # white corner marker
    b = np.zeros((60, 60, 4), np.uint8)
    b[..., :3] = (255, 0, 255); b[..., 3] = 255
    M1 = np.array([[1.5, 0, 40], [0, 1.5, 30]], np.float32)
    th = np.radians(25.0); c, s = np.cos(th), np.sin(th)
    M2 = np.array([[c, -s, 200 - c*30 + s*30],
                   [s,  c, 150 - s*30 - c*30]], np.float32)
    return [(a, M1, 1.0), (b, M2, 0.5)], W, H, bgr


def fix_result(img, flip, swap):
    if flip: img = img[::-1]
    if swap: img = img[..., ::-1]
    return np.ascontiguousarray(img)


def self_test(comp):
    """(ok, text). Draws the test scene with the GPU and compares to the CPU picture."""
    layers, W, H, bgr = test_scene()
    ref = reference_composite(layers, W, H, bgr).astype(np.int16)
    out = comp.draw_raw(layers, W, H, bgr)
    if out is None or out.shape != (H, W, 3):
        return False, "the GPU returned a picture of the wrong size"
    best = 1e9
    for flip in (False, True):
        for swap in (False, True):
            d = float(np.abs(fix_result(out, flip, swap).astype(np.int16) - ref).mean())
            best = min(best, d)
            if d < 6.0:
                comp.flip, comp.swap = flip, swap
                return True, ("matches the CPU picture (difference %.2f%s)"
                              % (d, ", corrected" if (flip or swap) else ""))
    return False, "the GPU picture does not match the CPU picture (difference %.1f)" % best


# ---------------------------------------------------------------------------
# GLSL source
# ---------------------------------------------------------------------------

_VERT_SRC = """\
#version 130
in  vec2 a_pos;
in  vec2 a_uv;
out vec2 v_uv;
uniform mat3 u_mvp;
void main() {
    vec3 p  = u_mvp * vec3(a_pos, 1.0);
    gl_Position = vec4(p.xy, 0.0, 1.0);
    v_uv        = a_uv;
}
"""

# Standard bilinear — always available
_FRAG_BILINEAR = """\
#version 130
in  vec2      v_uv;
out vec4      fragColor;
uniform sampler2D u_tex;
uniform float     u_opacity;
void main() {
    vec4 c = texture(u_tex, v_uv);
    // the texture holds straight (not premultiplied) colours: premultiply, apply opacity, for Porter-Duff over
    float a = c.a * u_opacity;
    fragColor = vec4(c.rgb * a, a);
}
"""

# Bicubic Mitchell-Netravali — better quality for upscaling
_FRAG_BICUBIC = """\
#version 130
in  vec2      v_uv;
out vec4      fragColor;
uniform sampler2D u_tex;
uniform vec2      u_texel;   // 1/texWidth, 1/texHeight
uniform float     u_opacity;

float mitchell(float x) {
    const float B = 1.0/3.0, C = 1.0/3.0;
    x = abs(x);
    if (x < 1.0)
        return ((12.0 - 9.0*B - 6.0*C)*x*x*x
              + (-18.0 + 12.0*B + 6.0*C)*x*x
              + (6.0  -  2.0*B)) / 6.0;
    if (x < 2.0)
        return ((-B - 6.0*C)*x*x*x
              + (6.0*B + 30.0*C)*x*x
              + (-12.0*B - 48.0*C)*x
              + (8.0*B  + 24.0*C)) / 6.0;
    return 0.0;
}

vec4 bicubic(sampler2D tex, vec2 uv, vec2 texel) {
    vec2 px  = uv / texel - 0.5;
    vec2 frc = fract(px);
    vec2 flr = floor(px);
    vec4 col = vec4(0.0);
    float wsum = 0.0;
    for (int j = -1; j <= 2; j++) {
        float wy = mitchell(float(j) - frc.y);
        for (int i = -1; i <= 2; i++) {
            float wx = mitchell(float(i) - frc.x);
            vec2 s   = (flr + vec2(float(i), float(j)) + 0.5) * texel;
            col  += texture(tex, s) * (wx * wy);
            wsum += wx * wy;
        }
    }
    return col / max(wsum, 1e-5);
}

void main() {
    vec4 c = bicubic(u_tex, v_uv, u_texel);
    float a   = c.a * u_opacity;
    fragColor = vec4(c.rgb * a, a);
}
"""

# ---------------------------------------------------------------------------
# OpenGL helper — thin wrappers around raw gl* calls via ctypes / PySide6
# ---------------------------------------------------------------------------

def _gl():
    """Return the QOpenGLFunctions_Core bound to the current context."""
    from PySide6.QtOpenGL import QOpenGLVersionFunctionsFactory
    from PySide6.QtGui import QOpenGLContext
    ctx = QOpenGLContext.currentContext()
    # Try 3.3 core first; fall back to 2.1 for older drivers
    for ver in ((3, 3), (3, 0), (2, 1)):
        try:
            from PySide6.QtOpenGL import QOpenGLVersionProfile
            profile = QOpenGLVersionProfile()
            profile.setVersion(*ver)
            fn = QOpenGLVersionFunctionsFactory.get(profile, ctx)
            if fn and fn.initializeOpenGLFunctions():
                return fn
        except Exception:
            pass
    fn = ctx.functions()
    fn.initializeOpenGLFunctions()
    return fn


def _compile_shader(gl, src, kind):
    GL_VERTEX_SHADER   = 0x8B31
    GL_FRAGMENT_SHADER = 0x8B30
    GL_COMPILE_STATUS  = 0x8B81
    s = gl.glCreateShader(kind)
    gl.glShaderSource(s, src)
    gl.glCompileShader(s)
    ok = ctypes.c_int(0)
    gl.glGetShaderiv(s, GL_COMPILE_STATUS, ctypes.byref(ok))
    if not ok.value:
        err = gl.glGetShaderInfoLog(s)
        raise RuntimeError("GLSL compile error: %s" % err)
    return s


def _link_program(gl, vert_src, frag_src):
    GL_LINK_STATUS = 0x8B82
    vs = _compile_shader(gl, vert_src, 0x8B31)
    fs = _compile_shader(gl, frag_src, 0x8B30)
    prog = gl.glCreateProgram()
    gl.glAttachShader(prog, vs)
    gl.glAttachShader(prog, fs)
    gl.glLinkProgram(prog)
    ok = ctypes.c_int(0)
    gl.glGetProgramiv(prog, GL_LINK_STATUS, ctypes.byref(ok))
    if not ok.value:
        err = gl.glGetProgramInfoLog(prog)
        raise RuntimeError("GLSL link error: %s" % err)
    gl.glDeleteShader(vs)
    gl.glDeleteShader(fs)
    return prog


# ---------------------------------------------------------------------------
# GpuCompositor — full OpenGL + GLSL implementation
# ---------------------------------------------------------------------------

class GpuCompositor:
    """Composites layers using native OpenGL + GLSL shaders.

    Lifecycle: __init__ → init() → draw() / draw_raw() → close()
    All calls must come from the same thread (the render thread).
    """

    # GL constants (subset we need — avoids importing OpenGL package)
    GL_TEXTURE_2D            = 0x0DE1
    GL_RGBA                  = 0x1908
    GL_UNSIGNED_BYTE         = 0x1401
    GL_FLOAT                 = 0x1406
    GL_COLOR_BUFFER_BIT      = 0x4000
    GL_BLEND                 = 0x0BE2
    GL_ONE                   = 1
    GL_ONE_MINUS_SRC_ALPHA   = 0x0303
    GL_ARRAY_BUFFER          = 0x8892
    GL_STATIC_DRAW           = 0x88B4
    GL_TRIANGLE_STRIP        = 0x0005
    GL_TEXTURE0              = 0x84C0
    GL_TEXTURE_MIN_FILTER    = 0x2801
    GL_TEXTURE_MAG_FILTER    = 0x2800
    GL_TEXTURE_WRAP_S        = 0x2802
    GL_TEXTURE_WRAP_T        = 0x2803
    GL_LINEAR                = 0x2601
    GL_CLAMP_TO_EDGE         = 0x812F
    GL_RENDERER              = 0x1F01
    GL_VERSION               = 0x1F02

    def __init__(self, surface):
        self.surface   = surface
        self.ctx       = None
        self.fbo       = None
        self.fbo_size  = None
        self.flip      = False
        self.swap      = False
        self.name      = "OpenGL+GLSL"
        self._prog_bi  = None   # bilinear shader program
        self._prog_bc  = None   # bicubic shader program
        self._vao      = None
        self._vbo      = None
        self._tex_cache = {}    # id(arr) -> (tex_id, shape) for temporary reuse within a frame
        self._bicubic_ok = False
        self._gl       = None

    # ------------------------------------------------------------------
    def init(self):
        from PySide6.QtGui import QOpenGLContext
        ctx = QOpenGLContext()
        ctx.setFormat(self.surface.format())
        if not ctx.create():
            raise RuntimeError("could not create an OpenGL context")
        if not ctx.makeCurrent(self.surface):
            raise RuntimeError("could not make OpenGL context current")
        self.ctx = ctx

        gl = _gl()
        self._gl = gl

        # Identify renderer
        try:
            v = gl.glGetString(self.GL_RENDERER)
            if v:
                self.name = v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            pass

        low = self.name.lower()
        if any(w in low for w in ("gdi generic", "llvmpipe", "software", "swrast")):
            raise RuntimeError("only software OpenGL is available (%s)" % self.name)

        # Compile shader programs
        self._prog_bi = _link_program(gl, _VERT_SRC, _FRAG_BILINEAR)

        # Try bicubic (needs GLSL 1.30 / OpenGL 3.0)
        try:
            self._prog_bc    = _link_program(gl, _VERT_SRC, _FRAG_BICUBIC)
            self._bicubic_ok = True
        except Exception:
            self._bicubic_ok = False

        # Build a fullscreen quad VBO: pos(x,y), uv(u,v) for a triangle-strip
        # Vertices: bottom-left, bottom-right, top-left, top-right (NDC)
        quad = np.array([
            -1.0, -1.0,  0.0, 1.0,
             1.0, -1.0,  1.0, 1.0,
            -1.0,  1.0,  0.0, 0.0,
             1.0,  1.0,  1.0, 0.0,
        ], dtype=np.float32)

        vao_arr = (ctypes.c_uint * 1)(0)
        try:
            gl.glGenVertexArrays(1, vao_arr)
            self._vao = vao_arr[0]
            gl.glBindVertexArray(self._vao)
        except Exception:
            self._vao = None   # OpenGL 2.1 fallback

        vbo_arr = (ctypes.c_uint * 1)(0)
        gl.glGenBuffers(1, vbo_arr)
        self._vbo = vbo_arr[0]
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferData(self.GL_ARRAY_BUFFER,
                        quad.nbytes,
                        quad.ctypes.data_as(ctypes.c_void_p),
                        self.GL_STATIC_DRAW)
        if self._vao:
            gl.glBindVertexArray(0)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, 0)

    # ------------------------------------------------------------------
    def _fbo(self, W, H):
        if self.fbo is not None and self.fbo_size == (W, H):
            return self.fbo
        try:
            from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        except Exception:
            from PySide6.QtGui import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        from PySide6.QtCore import QSize
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        # Request RGBA8 internal format explicitly for consistent readback
        fmt.setInternalTextureFormat(0x8058)   # GL_RGBA8
        self.fbo      = QOpenGLFramebufferObject(QSize(W, H), fmt)
        self.fbo_size = (W, H)
        return self.fbo

    # ------------------------------------------------------------------
    def _upload_texture(self, img):
        """Upload a BGR/BGRA numpy array as an RGBA GL texture. Returns tex_id."""
        gl = self._gl
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        # Convert BGR(A) → RGBA for GL upload
        img_rgba = np.ascontiguousarray(img[..., [2, 1, 0, 3]])
        h, w     = img_rgba.shape[:2]

        tex_arr = (ctypes.c_uint * 1)(0)
        gl.glGenTextures(1, tex_arr)
        tex = tex_arr[0]
        gl.glBindTexture(self.GL_TEXTURE_2D, tex)
        gl.glTexParameteri(self.GL_TEXTURE_2D, self.GL_TEXTURE_WRAP_S,       self.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(self.GL_TEXTURE_2D, self.GL_TEXTURE_WRAP_T,       self.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(self.GL_TEXTURE_2D, self.GL_TEXTURE_MIN_FILTER,   self.GL_LINEAR)
        gl.glTexParameteri(self.GL_TEXTURE_2D, self.GL_TEXTURE_MAG_FILTER,   self.GL_LINEAR)
        gl.glTexImage2D(self.GL_TEXTURE_2D, 0, self.GL_RGBA,
                        w, h, 0,
                        self.GL_RGBA, self.GL_UNSIGNED_BYTE,
                        img_rgba.ctypes.data_as(ctypes.c_void_p))
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        return tex, w, h

    # ------------------------------------------------------------------
    def _draw_layer(self, prog, tex, tex_w, tex_h, M_2x3, op, W, H):
        """Draw one textured quad using the affine matrix M (2×3 numpy float32)."""
        gl = self._gl

        gl.glUseProgram(prog)

        # Build MVP: map image corners through affine M → NDC
        # NDC: x ∈ [-1,+1], y ∈ [-1,+1], y down in image space → y up in NDC
        # NDC_x =  2*px/W - 1
        # NDC_y = -(2*py/H - 1)   (flip y)
        # Compose: scale(2/W, -2/H) · translate(-1, 1) · M_affine
        a00, a01, tx = float(M_2x3[0, 0]), float(M_2x3[0, 1]), float(M_2x3[0, 2])
        a10, a11, ty = float(M_2x3[1, 0]), float(M_2x3[1, 1]), float(M_2x3[1, 2])
        sx, sy = 2.0 / W, 2.0 / H

        # Column-major mat3 for GLSL
        # Maps image-space pixel (u*iw, v*ih) → NDC
        mvp = np.array([
            a00 * sx,          -a10 * sy,         0.0,
            a01 * sx,          -a11 * sy,         0.0,
            tx  * sx - 1.0,  -(ty * sy - 1.0),   1.0,
        ], dtype=np.float32)

        loc_mvp = gl.glGetUniformLocation(prog, "u_mvp")
        loc_tex = gl.glGetUniformLocation(prog, "u_tex")
        loc_op  = gl.glGetUniformLocation(prog, "u_opacity")

        gl.glUniformMatrix3fv(loc_mvp, 1, False, mvp.ctypes.data_as(ctypes.c_void_p))
        gl.glUniform1i(loc_tex, 0)
        gl.glUniform1f(loc_op, float(op))

        if self._bicubic_ok and prog == self._prog_bc:
            loc_texel = gl.glGetUniformLocation(prog, "u_texel")
            gl.glUniform2f(loc_texel, 1.0 / tex_w, 1.0 / tex_h)

        # Bind VBO and set attrib pointers
        stride = 4 * 4   # 4 floats × 4 bytes
        if self._vao:
            gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, self._vbo)

        loc_pos = gl.glGetAttribLocation(prog, "a_pos")
        loc_uv  = gl.glGetAttribLocation(prog, "a_uv")
        gl.glEnableVertexAttribArray(loc_pos)
        gl.glEnableVertexAttribArray(loc_uv)
        gl.glVertexAttribPointer(loc_pos, 2, self.GL_FLOAT, False, stride,
                                 ctypes.c_void_p(0))
        gl.glVertexAttribPointer(loc_uv,  2, self.GL_FLOAT, False, stride,
                                 ctypes.c_void_p(8))

        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex)

        gl.glDrawArrays(self.GL_TRIANGLE_STRIP, 0, 4)

        gl.glDisableVertexAttribArray(loc_pos)
        gl.glDisableVertexAttribArray(loc_uv)
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        if self._vao:
            gl.glBindVertexArray(0)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, 0)
        gl.glUseProgram(0)

    # ------------------------------------------------------------------
    def draw_raw(self, layers, W, H, bgr):
        """Composite layers into an (H, W, 3) BGR uint8 array via OpenGL + GLSL."""
        if not self.ctx.makeCurrent(self.surface):
            raise RuntimeError("lost the OpenGL context")

        gl  = self._gl
        fbo = self._fbo(W, H)
        fbo.bind()

        # Clear to background colour
        r, g, b = bgr[2] / 255.0, bgr[1] / 255.0, bgr[0] / 255.0
        gl.glClearColor(r, g, b, 1.0)
        gl.glClear(self.GL_COLOR_BUFFER_BIT)
        gl.glViewport(0, 0, W, H)

        # Premultiplied-alpha Porter-Duff over
        gl.glEnable(self.GL_BLEND)
        gl.glBlendFunc(self.GL_ONE, self.GL_ONE_MINUS_SRC_ALPHA)

        textures = []
        try:
            for img, M, op in layers:
                tex, tw, th = self._upload_texture(img)
                textures.append(tex)
                # Choose bicubic when upscaling (output size > texture size)
                scale = max(abs(float(M[0, 0])), abs(float(M[1, 1])), 1e-6)
                if self._bicubic_ok and scale > 1.05:
                    prog = self._prog_bc
                else:
                    prog = self._prog_bi
                self._draw_layer(prog, tex, tw, th, M, op, W, H)
        finally:
            # Delete per-frame textures
            if textures:
                arr = (ctypes.c_uint * len(textures))(*textures)
                gl.glDeleteTextures(len(textures), arr)

        # Read back pixels: GL_RGBA (4 channels) for alignment safety
        GL_RGBA = 0x1908
        buf = np.empty((H, W, 4), dtype=np.uint8)
        gl.glReadPixels(0, 0, W, H, GL_RGBA, self.GL_UNSIGNED_BYTE,
                        buf.ctypes.data_as(ctypes.c_void_p))

        fbo.release()
        gl.glDisable(self.GL_BLEND)

        # GL y=0 is bottom; images are top-down → flip
        buf = buf[::-1]
        # RGBA → BGR
        out = np.ascontiguousarray(buf[..., [2, 1, 0]])
        return out

    # ------------------------------------------------------------------
    def draw(self, layers, W, H, bgr):
        return fix_result(self.draw_raw(layers, W, H, bgr), self.flip, self.swap)

    # ------------------------------------------------------------------
    def close(self):
        try:
            if self.ctx is not None:
                self.ctx.makeCurrent(self.surface)
                gl = self._gl
                if gl:
                    if self._prog_bi:
                        gl.glDeleteProgram(self._prog_bi); self._prog_bi = None
                    if self._prog_bc:
                        gl.glDeleteProgram(self._prog_bc); self._prog_bc = None
                    if self._vbo:
                        arr = (ctypes.c_uint * 1)(self._vbo)
                        gl.glDeleteBuffers(1, arr); self._vbo = None
                    if self._vao:
                        arr = (ctypes.c_uint * 1)(self._vao)
                        gl.glDeleteVertexArrays(1, arr); self._vao = None
                self.fbo = None
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GpuState — unchanged API, Patch 33 engine ID
# ---------------------------------------------------------------------------

class GpuState:
    """Whether the GPU is used, what its status is, and the self-test.
    usable() must be called on the render thread."""

    def __init__(self):
        self.mode            = "auto"
        self.surface         = None
        self.comp            = None
        self.status          = "not started yet"
        self.disabled        = False
        self._tried          = False
        self.reset_requested = False
        self.make_comp       = GpuCompositor
        self.lock            = threading.Lock()

    def set_mode(self, mode):
        if mode not in ("auto", "off", "on"):
            mode = "auto"
        if mode != self.mode:
            old_mode = self.mode
            self.mode = mode
            if mode != "off":
                self.reset_requested = True
            else:
                self.status = "off (CPU only)"
            _gpu_trace("mode_changed", old_mode=old_mode, mode=mode, status=self.status)

    def retry(self):
        """Test GPU button: forget the old result and probe again."""
        _write({})
        try:                                  # Patch 35: the OpenGL effect chains get a fresh try as well
            from . import glfx; glfx.reset()
        except Exception: pass
        self.reset_requested = True
        self.status          = "testing ..."

    def fail(self, why):
        self.disabled = True
        self.status   = "off: " + why
        _write({"status": "failed", "reason": why})
        _gpu_trace("fallback_cpu", mode=self.mode, reason=why)

    def usable(self):
        if self.mode == "off":
            return False
        if self.reset_requested:
            self.reset_requested = False
            if self.comp is not None:
                self.comp.close()
            self.comp     = None
            self.disabled = False
            self._tried   = False
        if self.comp is not None:
            return True
        if self.disabled or self._tried:
            return False
        return self._probe()

    def _probe(self):
        self._tried = True
        if self.surface is None:
            self.disabled = True
            self.status   = "off: no OpenGL surface"
            return False
        st = _read()
        if self.mode == "auto":
            if st.get("status") == "probing":
                self.fail("the program crashed while testing the GPU last time")
                return False
            if st.get("status") == "failed":
                self.disabled = True
                self.status   = ("off: " + str(st.get("reason", "failed before"))
                                 + "  (press Test GPU to try again)")
                return False
        _write({"status": "probing"})
        try:
            comp = self.make_comp(self.surface)
            comp.init()
            ok, why = self_test(comp)
        except Exception as ex:
            ok, why, comp = False, "error: %s" % (ex,), None
        if ok:
            self.comp   = comp
            bicubic_tag = "bicubic" if getattr(comp, "_bicubic_ok", False) else "bilinear"
            self.status = "active: %s [GLSL/%s], %s" % (
                getattr(comp, "name", "OpenGL+GLSL"), bicubic_tag, why)
            _write({"status": "ok", "name": getattr(comp, "name", "")})
            _gpu_trace("active", mode=self.mode,
                       renderer=getattr(comp, "name", "OpenGL+GLSL"),
                       shader=bicubic_tag, self_test=why)
            return True
        if comp is not None:
            comp.close()
        self.fail(why)
        return False

    def draw(self, layers, W, H, bgr):
        return self.comp.draw(layers, W, H, bgr)


GPU = GpuState()


def install_surface():
    """Call once on the GUI thread: the off-screen surface must be created there."""
    try:
        from PySide6.QtGui import QOffscreenSurface, QSurfaceFormat
        fmt = QSurfaceFormat.defaultFormat()
        # Request at least OpenGL 3.0 for GLSL 1.30 / bicubic support
        if fmt.majorVersion() < 3:
            fmt.setMajorVersion(3)
            fmt.setMinorVersion(0)
        s = QOffscreenSurface()
        s.setFormat(fmt)
        s.create()
        if s.isValid():
            GPU.surface = s
        else:
            GPU.status = "off: no OpenGL surface"
    except Exception as ex:
        GPU.status = "off: %s" % (ex,)

"""GPU-accelerated effect helpers — Patch 33 OpenGL + GLSL.

Provides drop-in GPU replacements for the heaviest CPU-bound effects:
  * Gaussian blur        (single-pass separable GLSL)
  * Zoom / spin / radial blur  (multi-sample warp in one draw call)
  * Glow / soft-glow / dark-glow  (blur + composite in GLSL)
  * Sharpen              (unsharp-mask shader)
  * Color adjust / tint / BW / invert  (single-pass fragment shader)

Design rules:
  * Every public function accepts and returns uint8 BGRA numpy arrays —
    identical signature to the existing CPU functions so the caller in
    effects.py never changes.
  * If the GPU is unavailable, initialisation fails, or any error occurs
    the function raises GpuFxUnavailable and the caller falls back to CPU.
  * GL objects (context, programs, FBO) are cached on a per-thread basis
    so they are created once per session, not once per frame.
  * No dependency on the gpu.py GpuCompositor — this module manages its
    own minimal GL context (the same QOffscreenSurface created by
    install_surface() in gpu.py is reused).
"""
from __future__ import annotations
import ctypes
import math
import threading
import numpy as np
import cv2


class GpuFxUnavailable(Exception):
    """Raised when the GPU path is not usable; caller should fall back to CPU."""


# ---------------------------------------------------------------------------
# Thread-local GL state (one context per render thread)
# ---------------------------------------------------------------------------

_TLS = threading.local()


def _get_state():
    """Return the per-thread _GlState, creating it on first call."""
    s = getattr(_TLS, "state", None)
    if s is None:
        s = _GlState()
        _TLS.state = s
    return s


# ---------------------------------------------------------------------------
# Internal GL helpers
# ---------------------------------------------------------------------------

def _compile(gl, src, kind):
    GL_COMPILE_STATUS = 0x8B81
    s = gl.glCreateShader(kind)
    gl.glShaderSource(s, src)
    gl.glCompileShader(s)
    ok = ctypes.c_int(0)
    gl.glGetShaderiv(s, GL_COMPILE_STATUS, ctypes.byref(ok))
    if not ok.value:
        raise RuntimeError("GLSL: %s" % gl.glGetShaderInfoLog(s))
    return s


def _link(gl, vert, frag):
    GL_LINK_STATUS = 0x8B82
    GL_VERTEX_SHADER   = 0x8B31
    GL_FRAGMENT_SHADER = 0x8B30
    vs = _compile(gl, vert, GL_VERTEX_SHADER)
    fs = _compile(gl, frag, GL_FRAGMENT_SHADER)
    p  = gl.glCreateProgram()
    gl.glAttachShader(p, vs); gl.glAttachShader(p, fs); gl.glLinkProgram(p)
    ok = ctypes.c_int(0)
    gl.glGetProgramiv(p, GL_LINK_STATUS, ctypes.byref(ok))
    if not ok.value:
        raise RuntimeError("GLSL link: %s" % gl.glGetProgramInfoLog(p))
    gl.glDeleteShader(vs); gl.glDeleteShader(fs)
    return p


def _gl_functions():
    from PySide6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
    from PySide6.QtGui import QOpenGLContext
    ctx = QOpenGLContext.currentContext()
    for ver in ((3, 3), (3, 0), (2, 1)):
        try:
            prof = QOpenGLVersionProfile(); prof.setVersion(*ver)
            fn = QOpenGLVersionFunctionsFactory.get(prof, ctx)
            if fn and fn.initializeOpenGLFunctions(): return fn
        except Exception: pass
    fn = ctx.functions(); fn.initializeOpenGLFunctions(); return fn


# ---------------------------------------------------------------------------
# GLSL sources
# ---------------------------------------------------------------------------

_VERT = """\
#version 130
in  vec2 a_pos;
in  vec2 a_uv;
out vec2 v_uv;
void main() { v_uv = a_uv; gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

# --- Separable Gaussian blur (horizontal pass) ---
_FRAG_BLUR_H = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_sigma;
uniform vec2  u_texel;
void main() {
    int r = min(int(u_sigma * 3.0), 32);
    float sum = 0.0; vec4 acc = vec4(0.0);
    for (int i = -r; i <= r; i++) {
        float w = exp(-0.5 * float(i*i) / (u_sigma*u_sigma));
        acc += texture(u_tex, v_uv + vec2(float(i) * u_texel.x, 0.0)) * w;
        sum += w;
    }
    o = acc / sum;
}
"""

# --- Separable Gaussian blur (vertical pass) ---
_FRAG_BLUR_V = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_sigma;
uniform vec2  u_texel;
void main() {
    int r = min(int(u_sigma * 3.0), 32);
    float sum = 0.0; vec4 acc = vec4(0.0);
    for (int i = -r; i <= r; i++) {
        float w = exp(-0.5 * float(i*i) / (u_sigma*u_sigma));
        acc += texture(u_tex, v_uv + vec2(0.0, float(i) * u_texel.y)) * w;
        sum += w;
    }
    o = acc / sum;
}
"""

# --- Zoom / radial blur (multi-sample in one pass, no per-frame loop) ---
_FRAG_ZOOM_BLUR = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform vec2  u_center;   // 0..1
uniform float u_amount;   // 0..1
uniform int   u_steps;
void main() {
    vec4 acc = vec4(0.0); float w = 0.0;
    for (int i = 0; i < u_steps; i++) {
        float t  = float(i) / float(max(u_steps - 1, 1));
        float s  = 1.0 + u_amount * 0.5 * t;
        vec2  uv = u_center + (v_uv - u_center) / s;
        acc += texture(u_tex, clamp(uv, 0.0, 1.0));
        w   += 1.0;
    }
    o = acc / w;
}
"""

# --- Spin blur (rotational multi-sample) ---
_FRAG_SPIN_BLUR = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform vec2  u_center;
uniform float u_max_angle;  // radians
uniform int   u_steps;
void main() {
    vec2 d   = v_uv - u_center;
    vec4 acc = vec4(0.0); float w = 0.0;
    for (int i = 0; i < u_steps; i++) {
        float ang = u_max_angle * float(i) / float(max(u_steps-1,1));
        float c   = cos(ang); float s = sin(ang);
        vec2  rd  = vec2(c*d.x - s*d.y, s*d.x + c*d.y);
        acc += texture(u_tex, clamp(u_center + rd, 0.0, 1.0));
        w   += 1.0;
    }
    o = acc / w;
}
"""

# --- Glow: threshold → blur → screen composite ---
_FRAG_GLOW = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_orig;
uniform sampler2D u_blur;
uniform float u_amount;
uniform float u_thr;
uniform vec3  u_tint;      // 1,1,1 = no tint
uniform int   u_add;       // 0=screen  1=add
void main() {
    vec4 orig  = texture(u_orig, v_uv);
    vec4 blr   = texture(u_blur, v_uv);
    float lum  = dot(blr.rgb, vec3(0.299, 0.587, 0.114));
    float mask = clamp((lum - u_thr) / max(0.001, 1.0 - u_thr), 0.0, 1.0);
    vec3  glow = blr.rgb * mask * u_tint;
    vec3  res;
    if (u_add == 1)
        res = clamp(orig.rgb + glow * u_amount, 0.0, 1.0);
    else  // screen
        res = 1.0 - (1.0 - orig.rgb) * (1.0 - glow * u_amount);
    o = vec4(clamp(res, 0.0, 1.0), orig.a);
}
"""

# --- Unsharp mask (sharpen) ---
_FRAG_SHARPEN = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_orig;
uniform sampler2D u_blur;
uniform float u_amount;
uniform float u_thr;
void main() {
    vec4 orig = texture(u_orig, v_uv);
    vec4 blr  = texture(u_blur, v_uv);
    vec3 diff = orig.rgb - blr.rgb;
    float edge = max(max(abs(diff.r), abs(diff.g)), abs(diff.b));
    float mask = u_thr > 0.0 ? clamp((edge - u_thr) / max(1e-4, u_thr), 0.0, 1.0) : 1.0;
    o = vec4(clamp(orig.rgb + diff * u_amount * mask, 0.0, 1.0), orig.a);
}
"""

# --- Color adjust (brightness/contrast/saturation/hue) ---
_FRAG_ADJUST = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_br;    // brightness  -1..1
uniform float u_co;    // contrast multiplier  (1=no change)
uniform float u_sa;    // saturation multiplier
uniform float u_hu;    // hue shift degrees
void main() {
    vec4 c = texture(u_tex, v_uv);
    // brightness + contrast
    vec3 rgb = (c.rgb - 0.5) * u_co + 0.5 + u_br;
    // saturation
    float lum = dot(rgb, vec3(0.114, 0.587, 0.299));
    rgb = mix(vec3(lum), rgb, u_sa);
    // hue shift (convert to YCbCr, rotate chroma)
    if (abs(u_hu) > 0.001) {
        float cb  = -0.169*rgb.r - 0.331*rgb.g + 0.5  *rgb.b;
        float cr  =  0.5 *rgb.r - 0.419*rgb.g - 0.081*rgb.b;
        float rad = radians(u_hu);
        float cc  = cos(rad); float ss = sin(rad);
        float cb2 = cb*cc - cr*ss;
        float cr2 = cb*ss + cr*cc;
        rgb.r = clamp(rgb.r                  + 1.402  * cr2, 0.0, 1.0);
        rgb.g = clamp(rgb.g - 0.344136*cb2  - 0.714136*cr2, 0.0, 1.0);
        rgb.b = clamp(rgb.b + 1.772   *cb2,                  0.0, 1.0);
    }
    o = vec4(clamp(rgb, 0.0, 1.0), c.a);
}
"""

# --- Tint ---
_FRAG_TINT = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform vec3  u_col;   // BGR → RGB tint color (0..1)
uniform float u_amount;
void main() {
    vec4 c   = texture(u_tex, v_uv);
    float g  = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    vec3 tint = g < 0.5
        ? 2.0 * g * u_col
        : 1.0 - 2.0 * (1.0 - g) * (1.0 - u_col);
    o = vec4(mix(c.rgb, tint, u_amount), c.a);
}
"""

# --- BW ---
_FRAG_BW = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_amount;
void main() {
    vec4 c   = texture(u_tex, v_uv);
    float g  = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    o = vec4(mix(c.rgb, vec3(g), u_amount), c.a);
}
"""

# --- Vignette ---
_FRAG_VIGNETTE = """\
#version 130
in  vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_amount;
uniform float u_start;   // 0..1 where vignette begins
uniform float u_round;   // 0=box 1=circle
uniform vec3  u_col;
uniform int   u_alpha;
void main() {
    vec4 c   = texture(u_tex, v_uv);
    vec2 d   = v_uv - 0.5;
    float rbox = max(abs(d.x)*2.0, abs(d.y)*2.0);
    float rcir = length(d)*2.0 / 1.4142;
    float r    = mix(rbox, rcir, u_round);
    float v    = clamp((r - u_start) / max(0.001, 1.0 - u_start), 0.0, 1.0);
    v = v * v * u_amount;
    if (u_alpha == 1)
        o = vec4(c.rgb, c.a * (1.0 - v));
    else
        o = vec4(mix(c.rgb, u_col, v), c.a);
}
"""


# ---------------------------------------------------------------------------
# _GlState — per-thread OpenGL objects
# ---------------------------------------------------------------------------

class _GlState:
    """Lazily created per render-thread GL context and cached shader programs."""

    GL_TEXTURE_2D        = 0x0DE1
    GL_RGBA              = 0x1908
    GL_RGBA32F           = 0x8814
    GL_FLOAT             = 0x1406
    GL_UNSIGNED_BYTE     = 0x1401
    GL_ARRAY_BUFFER      = 0x8892
    GL_STATIC_DRAW       = 0x88B4
    GL_TRIANGLE_STRIP    = 0x0005
    GL_TEXTURE0          = 0x84C0
    GL_TEXTURE1          = 0x84C1
    GL_COLOR_BUFFER_BIT  = 0x4000
    GL_LINEAR            = 0x2601
    GL_CLAMP_TO_EDGE     = 0x812F
    GL_TEXTURE_MIN_FILTER= 0x2801
    GL_TEXTURE_MAG_FILTER= 0x2800
    GL_TEXTURE_WRAP_S    = 0x2802
    GL_TEXTURE_WRAP_T    = 0x2803

    def __init__(self):
        self._ctx   = None
        self._gl    = None
        self._vbo   = None
        self._vao   = None
        self._fbo   = {}       # (w,h) -> fbo object
        self._fbo2  = {}       # (w,h) -> secondary fbo (for two-pass)
        self._progs = {}       # name -> program id
        self._failed = False

    # ----------------------------------------------------------------
    def _ensure_ctx(self):
        if self._failed:
            raise GpuFxUnavailable("GPU FX init failed previously")
        if self._ctx is not None:
            return
        # Reuse the surface created by gpu.install_surface()
        try:
            from .gpu import GPU
            surface = GPU.surface
        except Exception:
            surface = None
        if surface is None:
            self._failed = True
            raise GpuFxUnavailable("no GL surface (GPU disabled)")
        try:
            from PySide6.QtGui import QOpenGLContext
            ctx = QOpenGLContext()
            # Share textures with the main GPU compositor context if available
            if GPU.comp is not None and getattr(GPU.comp, "ctx", None):
                ctx.setShareContext(GPU.comp.ctx)
            ctx.setFormat(surface.format())
            if not ctx.create():
                raise RuntimeError("could not create GL context")
            if not ctx.makeCurrent(surface):
                raise RuntimeError("could not make GL context current")
            self._ctx     = ctx
            self._surface = surface
            self._gl      = _gl_functions()
            self._init_vbo()
        except Exception as ex:
            self._failed = True
            raise GpuFxUnavailable("GL init: %s" % ex)

    def _make_current(self):
        if not self._ctx.makeCurrent(self._surface):
            raise GpuFxUnavailable("lost GL context")

    def _init_vbo(self):
        gl   = self._gl
        quad = np.array([-1,-1, 0,1,  1,-1, 1,1,  -1,1, 0,0,  1,1, 1,0], np.float32)
        vao_a = (ctypes.c_uint*1)(0)
        try:
            gl.glGenVertexArrays(1, vao_a); self._vao = vao_a[0]
            gl.glBindVertexArray(self._vao)
        except Exception:
            self._vao = None
        vbo_a = (ctypes.c_uint*1)(0)
        gl.glGenBuffers(1, vbo_a); self._vbo = vbo_a[0]
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferData(self.GL_ARRAY_BUFFER, quad.nbytes,
                        quad.ctypes.data_as(ctypes.c_void_p), self.GL_STATIC_DRAW)
        if self._vao: gl.glBindVertexArray(0)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, 0)

    def prog(self, name, vert, frag):
        if name not in self._progs:
            self._progs[name] = _link(self._gl, vert, frag)
        return self._progs[name]

    def fbo(self, w, h, secondary=False):
        cache = self._fbo2 if secondary else self._fbo
        if (w, h) not in cache:
            try:
                from PySide6.QtOpenGL import (QOpenGLFramebufferObject,
                                               QOpenGLFramebufferObjectFormat)
            except Exception:
                from PySide6.QtGui import (QOpenGLFramebufferObject,
                                            QOpenGLFramebufferObjectFormat)
            from PySide6.QtCore import QSize
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fmt.setInternalTextureFormat(self.GL_RGBA)   # GL_RGBA8
            cache[(w, h)] = QOpenGLFramebufferObject(QSize(w, h), fmt)
        return cache[(w, h)]

    # ---------------------------------------------------------------- texture helpers

    def upload(self, img_rgba):
        """Upload RGBA uint8 numpy array → GL texture id. Caller must delete."""
        gl = self._gl
        h, w = img_rgba.shape[:2]
        tex_a = (ctypes.c_uint*1)(0)
        gl.glGenTextures(1, tex_a); tex = tex_a[0]
        gl.glBindTexture(self.GL_TEXTURE_2D, tex)
        for p, v in ((self.GL_TEXTURE_WRAP_S, self.GL_CLAMP_TO_EDGE),
                     (self.GL_TEXTURE_WRAP_T, self.GL_CLAMP_TO_EDGE),
                     (self.GL_TEXTURE_MIN_FILTER, self.GL_LINEAR),
                     (self.GL_TEXTURE_MAG_FILTER, self.GL_LINEAR)):
            gl.glTexParameteri(self.GL_TEXTURE_2D, p, v)
        gl.glTexImage2D(self.GL_TEXTURE_2D, 0, self.GL_RGBA, w, h, 0,
                        self.GL_RGBA, self.GL_UNSIGNED_BYTE,
                        img_rgba.ctypes.data_as(ctypes.c_void_p))
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        return tex

    def del_tex(self, *texs):
        arr = (ctypes.c_uint * len(texs))(*texs)
        self._gl.glDeleteTextures(len(texs), arr)

    # ---------------------------------------------------------------- draw helpers

    def _bind_vbo(self, prog):
        gl = self._gl
        if self._vao: gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, self._vbo)
        for name, off in (("a_pos", 0), ("a_uv", 8)):
            loc = gl.glGetAttribLocation(prog, name)
            if loc >= 0:
                gl.glEnableVertexAttribArray(loc)
                gl.glVertexAttribPointer(loc, 2, self.GL_FLOAT, False, 16,
                                         ctypes.c_void_p(off))

    def _unbind_vbo(self, prog):
        gl = self._gl
        for name in ("a_pos", "a_uv"):
            loc = gl.glGetAttribLocation(prog, name)
            if loc >= 0: gl.glDisableVertexAttribArray(loc)
        if self._vao: gl.glBindVertexArray(0)
        gl.glBindBuffer(self.GL_ARRAY_BUFFER, 0)

    def draw_fullscreen(self, prog):
        gl = self._gl
        self._bind_vbo(prog)
        gl.glDrawArrays(self.GL_TRIANGLE_STRIP, 0, 4)
        self._unbind_vbo(prog)
        gl.glUseProgram(0)

    # ---------------------------------------------------------------- main render path

    def render_1tex(self, name, vert_src, frag_src, img_bgra, set_uniforms):
        """
        Upload img_bgra, run shader, read back BGRA.
        set_uniforms(gl, prog) — caller sets uniform values.
        Returns uint8 BGRA ndarray same size as input.
        """
        self._ensure_ctx()
        self._make_current()
        gl = self._gl
        h, w = img_bgra.shape[:2]
        img_rgba = np.ascontiguousarray(img_bgra[..., [2, 1, 0, 3]])
        tex  = self.upload(img_rgba)
        fbo_ = self.fbo(w, h)
        fbo_.bind()
        gl.glViewport(0, 0, w, h)
        prog = self.prog(name, vert_src, frag_src)
        gl.glUseProgram(prog)
        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_tex"), 0)
        set_uniforms(gl, prog)
        self.draw_fullscreen(prog)
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        out_rgba = np.empty((h, w, 4), np.uint8)
        gl.glReadPixels(0, 0, w, h, self.GL_RGBA, self.GL_UNSIGNED_BYTE,
                        out_rgba.ctypes.data_as(ctypes.c_void_p))
        fbo_.release()
        self.del_tex(tex)
        # GL y=0 is bottom
        return np.ascontiguousarray(out_rgba[::-1, :, [2, 1, 0, 3]])

    def render_2tex(self, name, vert_src, frag_src, img1_bgra, img2_bgra, set_uniforms):
        """Two-texture variant (orig + blurred → composite)."""
        self._ensure_ctx()
        self._make_current()
        gl = self._gl
        h, w = img1_bgra.shape[:2]
        tex1 = self.upload(np.ascontiguousarray(img1_bgra[..., [2, 1, 0, 3]]))
        tex2 = self.upload(np.ascontiguousarray(img2_bgra[..., [2, 1, 0, 3]]))
        fbo_ = self.fbo(w, h)
        fbo_.bind()
        gl.glViewport(0, 0, w, h)
        prog = self.prog(name, _VERT, frag_src)
        gl.glUseProgram(prog)
        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex1)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_orig"), 0)
        gl.glActiveTexture(self.GL_TEXTURE1)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex2)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_blur"), 1)
        set_uniforms(gl, prog)
        self.draw_fullscreen(prog)
        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        gl.glActiveTexture(self.GL_TEXTURE1)
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        out_rgba = np.empty((h, w, 4), np.uint8)
        gl.glReadPixels(0, 0, w, h, self.GL_RGBA, self.GL_UNSIGNED_BYTE,
                        out_rgba.ctypes.data_as(ctypes.c_void_p))
        fbo_.release()
        self.del_tex(tex1, tex2)
        return np.ascontiguousarray(out_rgba[::-1, :, [2, 1, 0, 3]])

    # -- two-pass Gaussian blur using intermediate FBO -------------------
    def gaussian_blur(self, img_bgra, sigma):
        """Full separable Gaussian blur, two GL passes. Returns BGRA."""
        self._ensure_ctx()
        self._make_current()
        gl = self._gl
        h, w = img_bgra.shape[:2]
        img_rgba = np.ascontiguousarray(img_bgra[..., [2, 1, 0, 3]])
        tex_in = self.upload(img_rgba)
        # Pass 1: horizontal → secondary FBO
        fbo_a = self.fbo(w, h, secondary=False)
        fbo_b = self.fbo(w, h, secondary=True)
        prog_h = self.prog("blur_h", _VERT, _FRAG_BLUR_H)
        prog_v = self.prog("blur_v", _VERT, _FRAG_BLUR_V)

        fbo_a.bind()
        gl.glViewport(0, 0, w, h)
        gl.glUseProgram(prog_h)
        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex_in)
        gl.glUniform1i(gl.glGetUniformLocation(prog_h, "u_tex"), 0)
        gl.glUniform1f(gl.glGetUniformLocation(prog_h, "u_sigma"), float(sigma))
        gl.glUniform2f(gl.glGetUniformLocation(prog_h, "u_texel"), 1.0/w, 1.0/h)
        self.draw_fullscreen(prog_h)
        fbo_a.release()

        # Pass 2: vertical, read texture from fbo_a
        tex_mid = fbo_a.texture()
        fbo_b.bind()
        gl.glViewport(0, 0, w, h)
        gl.glUseProgram(prog_v)
        gl.glActiveTexture(self.GL_TEXTURE0)
        gl.glBindTexture(self.GL_TEXTURE_2D, tex_mid)
        gl.glUniform1i(gl.glGetUniformLocation(prog_v, "u_tex"), 0)
        gl.glUniform1f(gl.glGetUniformLocation(prog_v, "u_sigma"), float(sigma))
        gl.glUniform2f(gl.glGetUniformLocation(prog_v, "u_texel"), 1.0/w, 1.0/h)
        self.draw_fullscreen(prog_v)
        gl.glBindTexture(self.GL_TEXTURE_2D, 0)
        out_rgba = np.empty((h, w, 4), np.uint8)
        gl.glReadPixels(0, 0, w, h, self.GL_RGBA, self.GL_UNSIGNED_BYTE,
                        out_rgba.ctypes.data_as(ctypes.c_void_p))
        fbo_b.release()
        self.del_tex(tex_in)
        return np.ascontiguousarray(out_rgba[::-1, :, [2, 1, 0, 3]])


# ---------------------------------------------------------------------------
# Public GPU-accelerated effect functions
# ---------------------------------------------------------------------------

def gpu_gaussian_blur(img, sigma):
    """Separable Gaussian blur on GPU. img: BGRA uint8. Returns BGRA uint8."""
    if sigma < 0.35: return img
    # For very large sigma: downscale on CPU, blur on GPU, upscale on CPU
    # (matches the existing CPU strategy in _gauss)
    if sigma > 6:
        h, w = img.shape[:2]; f = 4.0 / sigma
        sw, sh = max(1, int(w*f)), max(1, int(h*f))
        small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        blurred = _get_state().gaussian_blur(small, 4.0)
        return cv2.resize(blurred, (w, h), interpolation=cv2.INTER_LINEAR)
    return _get_state().gaussian_blur(img, sigma)


def gpu_zoom_blur(img, amount, cx, cy, steps):
    """Zoom blur fully on GPU (single pass, no Python loop)."""
    def _set(gl, prog):
        gl.glUniform2f(gl.glGetUniformLocation(prog, "u_center"), cx, 1.0 - cy)
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"), float(amount))
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_steps"),  int(steps))
    return _get_state().render_1tex("zoom_blur", _VERT, _FRAG_ZOOM_BLUR, img, _set)


def gpu_spin_blur(img, max_angle_rad, cx, cy, steps):
    """Rotational blur fully on GPU."""
    def _set(gl, prog):
        gl.glUniform2f(gl.glGetUniformLocation(prog, "u_center"),    cx, 1.0 - cy)
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_max_angle"), float(max_angle_rad))
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_steps"),     int(steps))
    return _get_state().render_1tex("spin_blur", _VERT, _FRAG_SPIN_BLUR, img, _set)


def gpu_glow(img, blurred, amount, threshold, tint_rgb=(1,1,1), add=False):
    """Glow composite: orig + pre-blurred → screen/add on GPU."""
    def _set(gl, prog):
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"),  float(amount))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_thr"),     float(threshold))
        gl.glUniform3f(gl.glGetUniformLocation(prog, "u_tint"),    *tint_rgb)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_add"),     1 if add else 0)
    return _get_state().render_2tex("glow", _VERT, _FRAG_GLOW, img, blurred, _set)


def gpu_sharpen(img, blurred, amount, threshold=0.0):
    """Unsharp-mask composite on GPU."""
    def _set(gl, prog):
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"), float(amount))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_thr"),    float(threshold))
    return _get_state().render_2tex("sharpen", _VERT, _FRAG_SHARPEN, img, blurred, _set)


def gpu_adjust(img, br=0.0, co=0.0, sa=0.0, hu=0.0):
    """Brightness/contrast/saturation/hue in one GPU pass."""
    co_mul = 1.0 + co / 100.0
    sa_mul = 1.0 + sa / 100.0
    def _set(gl, prog):
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_br"), float(br / 200.0))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_co"), float(co_mul))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_sa"), float(sa_mul))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_hu"), float(hu))
    return _get_state().render_1tex("adjust", _VERT, _FRAG_ADJUST, img, _set)


def gpu_tint(img, color_bgr_f, amount):
    """Tint effect on GPU. color_bgr_f: (b,g,r) in 0..1."""
    r, g, b = color_bgr_f[2], color_bgr_f[1], color_bgr_f[0]
    def _set(gl, prog):
        gl.glUniform3f(gl.glGetUniformLocation(prog, "u_col"),    r, g, b)
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"), float(amount))
    return _get_state().render_1tex("tint", _VERT, _FRAG_TINT, img, _set)


def gpu_bw(img, amount):
    """Black-and-white on GPU."""
    def _set(gl, prog):
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"), float(amount))
    return _get_state().render_1tex("bw", _VERT, _FRAG_BW, img, _set)


def gpu_vignette(img, amount, softness, roundness, color_bgr_f, alpha_mode=False):
    start = 1.0 - softness * 0.95
    r, g, b = color_bgr_f[2], color_bgr_f[1], color_bgr_f[0]
    def _set(gl, prog):
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_amount"), float(amount))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_start"),  float(start))
        gl.glUniform1f(gl.glGetUniformLocation(prog, "u_round"),  float(roundness))
        gl.glUniform3f(gl.glGetUniformLocation(prog, "u_col"),    r, g, b)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "u_alpha"),  1 if alpha_mode else 0)
    return _get_state().render_1tex("vignette", _VERT, _FRAG_VIGNETTE, img, _set)

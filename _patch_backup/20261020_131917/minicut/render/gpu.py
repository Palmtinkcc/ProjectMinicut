"""Optional GPU compositing (OpenGL through Qt), with a self-test and a crash guard.

The picture is still prepared on the CPU (decoding, effects). What moves to the GPU is placing the layers: scaling,
rotating, opacity and blending, which is the expensive part. The GPU draws into an off-screen buffer on the render
thread, and the finished picture is read back as before, so nothing else in the program changes.

Safety:
  * At the first use a small test scene is drawn by the GPU and by the CPU. If the two pictures do not match (or
    anything fails) the GPU is not used. The program also tries upside-down and red/blue-swapped results and corrects them.
  * Before the test a note 'probing' is written to gpu_state.json. If the program crashed inside the test, the next
    start sees that note and keeps the GPU off. The Test GPU button in Settings tries again.
  * Any error while drawing switches to the CPU for the rest of the session."""
import json, os, threading
import cv2
import numpy as np
from ..shared.core import APP_DIR
from .fastcomp import blend_into, to_cv_matrix

STATE_FILE = os.path.join(APP_DIR, "gpu_state.json")


def _read():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


def _write(d):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(d, f)
    except Exception: pass


def premultiply(img):
    out = img.copy(); a = img[..., 3:4].astype(np.uint16)
    out[..., :3] = (img[..., :3].astype(np.uint16) * a // 255).astype(np.uint8)
    return out


def reference_composite(layers, W, H, bgr):
    """The same layers placed by the CPU (warp + blend). Used by the self-test and by the tests."""
    canvas = np.empty((H, W, 3), np.uint8); canvas[:] = bgr
    for img, M, op in layers:
        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        lay = cv2.warpAffine(img, to_cv_matrix(M), (W, H), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        blend_into(canvas, np.ascontiguousarray(lay[..., :3]), np.ascontiguousarray(lay[..., 3]), op)
    return canvas


def test_scene():
    """A scene that shows any flip or colour swap: four colour quadrants with a white marker in one corner."""
    W, H = 320, 240; bgr = (50, 40, 30)
    a = np.zeros((100, 160, 4), np.uint8); a[..., 3] = 255
    a[:50, :80] = (0, 0, 255, 255); a[:50, 80:] = (0, 255, 0, 255)       # top-left red, top-right green  (BGR order)
    a[50:, :80] = (255, 0, 0, 255); a[50:, 80:] = (0, 255, 255, 255)     # bottom-left blue, bottom-right yellow
    a[:12, :12] = (255, 255, 255, 255)
    b = np.zeros((60, 60, 4), np.uint8); b[..., :3] = (255, 0, 255); b[..., 3] = 255
    M1 = np.array([[1.5, 0, 40], [0, 1.5, 30]], np.float32)
    th = np.radians(25.0); c, s = np.cos(th), np.sin(th)
    M2 = np.array([[c, -s, 200 - c * 30 + s * 30], [s, c, 150 - s * 30 - c * 30]], np.float32)
    return [(a, M1, 1.0), (b, M2, 0.5)], W, H, bgr


def fix_result(img, flip, swap):
    if flip: img = img[::-1]
    if swap: img = img[..., ::-1]
    return np.ascontiguousarray(img)


def self_test(comp):
    """(ok, text). Draws the test scene with the GPU and compares it with the CPU picture."""
    layers, W, H, bgr = test_scene()
    ref = reference_composite(layers, W, H, bgr).astype(np.int16)
    out = comp.draw_raw(layers, W, H, bgr)
    if out is None or out.shape != (H, W, 3): return False, "the GPU returned a picture of the wrong size"
    best = 1e9
    for flip in (False, True):
        for swap in (False, True):
            d = float(np.abs(fix_result(out, flip, swap).astype(np.int16) - ref).mean()); best = min(best, d)
            if d < 6.0:
                comp.flip, comp.swap = flip, swap
                return True, "matches the CPU picture (difference %.2f%s)" % (d, ", corrected" if (flip or swap) else "")
    return False, "the GPU picture does not match the CPU picture (difference %.1f)" % best


class GpuCompositor:
    """Draws layers with QPainter on an OpenGL frame buffer (off-screen). Lives on the render thread."""
    def __init__(self, surface):
        self.surface = surface; self.ctx = None; self.fbo = None; self.fbo_size = None
        self.flip = False; self.swap = False; self.name = "OpenGL"
    def init(self):
        from PySide6.QtGui import QOpenGLContext
        ctx = QOpenGLContext(); ctx.setFormat(self.surface.format())
        if not ctx.create(): raise RuntimeError("could not create an OpenGL context")
        if not ctx.makeCurrent(self.surface): raise RuntimeError("could not use the OpenGL context")
        self.ctx = ctx
        try:
            v = ctx.functions().glGetString(0x1F01)            # GL_RENDERER
            if v: self.name = v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception: pass
        low = self.name.lower()
        if any(w in low for w in ("gdi generic", "llvmpipe", "software", "swrast")):
            raise RuntimeError("only software OpenGL is available (%s)" % self.name)
    def _fbo(self, W, H):
        if self.fbo is not None and self.fbo_size == (W, H): return self.fbo
        try:
            from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        except Exception:
            from PySide6.QtGui import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        from PySide6.QtCore import QSize
        fmt = QOpenGLFramebufferObjectFormat(); fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        self.fbo = QOpenGLFramebufferObject(QSize(W, H), fmt); self.fbo_size = (W, H)
        return self.fbo
    @staticmethod
    def _qimage(img):
        from PySide6.QtGui import QImage
        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        img = np.ascontiguousarray(img)
        if cv2.countNonZero(cv2.compare(cv2.extractChannel(img, 3), 255, cv2.CMP_LT)): img = premultiply(img)
        h, w = img.shape[:2]
        return QImage(img.data, w, h, img.strides[0], QImage.Format_ARGB32_Premultiplied), img     # keep img alive
    @staticmethod
    def _to_bgr(qi, W, H):
        from PySide6.QtGui import QImage
        n = qi.sizeInBytes(); ptr = qi.constBits()
        try: buf = np.frombuffer(ptr, np.uint8, count=n)
        except Exception: buf = np.frombuffer(ptr.asarray(n), np.uint8)
        bpl = qi.bytesPerLine(); arr = buf[:bpl * H].reshape(H, bpl)[:, :W * 4].reshape(H, W, 4)
        if qi.format() in (QImage.Format_RGBA8888, QImage.Format_RGBA8888_Premultiplied): return np.ascontiguousarray(arr[..., 2::-1])
        return np.ascontiguousarray(arr[..., :3])
    def draw_raw(self, layers, W, H, bgr):
        from PySide6.QtGui import QPainter, QColor, QTransform
        try: from PySide6.QtOpenGL import QOpenGLPaintDevice
        except Exception: from PySide6.QtGui import QOpenGLPaintDevice
        if not self.ctx.makeCurrent(self.surface): raise RuntimeError("lost the OpenGL context")
        fbo = self._fbo(W, H); fbo.bind()
        keep = []
        try:
            p = QPainter(QOpenGLPaintDevice(W, H))
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.fillRect(0, 0, W, H, QColor(int(bgr[2]), int(bgr[1]), int(bgr[0])))
            for img, M, op in layers:
                qi, arr = self._qimage(img); keep.append((qi, arr))
                p.setOpacity(float(op))
                p.setTransform(QTransform(float(M[0][0]), float(M[1][0]), float(M[0][1]), float(M[1][1]), float(M[0][2]), float(M[1][2])))
                p.drawImage(0, 0, qi)
            p.end()
            out = fbo.toImage()
        finally:
            fbo.release()
        return self._to_bgr(out, W, H)
    def draw(self, layers, W, H, bgr):
        return fix_result(self.draw_raw(layers, W, H, bgr), self.flip, self.swap)
    def close(self):
        try:
            if self.ctx is not None: self.ctx.makeCurrent(self.surface)
            self.fbo = None
        except Exception: pass


class GpuState:
    """Whether the GPU is used, what its status is, and the self-test. usable() runs on the render thread."""
    def __init__(self):
        self.mode = "auto"; self.surface = None; self.comp = None; self.status = "not started yet"
        self.disabled = False; self._tried = False; self.reset_requested = False; self.make_comp = GpuCompositor
        self.lock = threading.Lock()
    def set_mode(self, mode):
        if mode not in ("auto", "off", "on"): mode = "auto"
        if mode != self.mode:
            self.mode = mode
            if mode != "off": self.reset_requested = True
            else: self.status = "off (CPU only)"
    def retry(self):
        """Test GPU button: forget the old result and probe again on the next preview frame."""
        _write({}); self.reset_requested = True; self.status = "testing ..."
    def fail(self, why):
        self.disabled = True; self.status = "off: " + why; _write({"status": "failed", "reason": why})
    def usable(self):
        if self.mode == "off": return False
        if self.reset_requested:
            self.reset_requested = False
            if self.comp is not None: self.comp.close()
            self.comp = None; self.disabled = False; self._tried = False
        if self.comp is not None: return True
        if self.disabled or self._tried: return False
        return self._probe()
    def _probe(self):
        self._tried = True
        if self.surface is None: self.disabled = True; self.status = "off: no OpenGL surface"; return False
        st = _read()
        if self.mode == "auto":
            if st.get("status") == "probing":
                self.fail("the program crashed while testing the GPU last time"); return False
            if st.get("status") == "failed":
                self.disabled = True; self.status = "off: " + str(st.get("reason", "failed before")) + "  (press Test GPU to try again)"; return False
        _write({"status": "probing"})
        try:
            comp = self.make_comp(self.surface); comp.init(); ok, why = self_test(comp)
        except Exception as ex:
            ok, why, comp = False, "error: %s" % (ex,), None
        if ok:
            self.comp = comp; self.status = "active: %s, %s" % (getattr(comp, "name", "OpenGL"), why)
            _write({"status": "ok", "name": getattr(comp, "name", "")}); return True
        if comp is not None: comp.close()
        self.fail(why); return False
    def draw(self, layers, W, H, bgr):
        return self.comp.draw(layers, W, H, bgr)


GPU = GpuState()


def install_surface():
    """Call once on the GUI thread: the off-screen surface has to be made there."""
    try:
        from PySide6.QtGui import QOffscreenSurface, QSurfaceFormat
        s = QOffscreenSurface(); s.setFormat(QSurfaceFormat.defaultFormat()); s.create()
        if s.isValid(): GPU.surface = s
        else: GPU.status = "off: no OpenGL surface"
    except Exception as ex:
        GPU.status = "off: %s" % (ex,)

"""Bone2D drawn on the GPU, the way Live2D does it.

 * every picture becomes a triangle mesh; moving / bending the puppet only recomputes the (few hundred) vertices (numpy, one pass for the
   whole rig), never the pixels
 * all pictures are packed into ONE texture (a texture atlas, with mipmaps) and the whole rig is drawn with ONE draw call
   (alpha blending, back to front)
 * the pictures are shrunk automatically (mipmaps / atlas scale) so a 4K rig with hundreds of layers does not need the memory bandwidth

Two users: the editor canvas (a QOpenGLWidget draws with its own context) and the renderer of MiniCut (preview / export / thumbnails),
which sends a job to one background thread that owns a hidden OpenGL context. When OpenGL is not available everything falls back to
the CPU drawing in bone2d.py."""
import math, threading, queue, uuid
from concurrent.futures import Future
from collections import OrderedDict
import numpy as np
import cv2
import ctypes

from . import bone2d as B

GUTTER = 4
_NULL = ctypes.c_void_p(0)
GL_TRIANGLES, GL_UNSIGNED_INT, GL_UNSIGNED_SHORT, GL_FLOAT = 4, 0x1405, 0x1403, 0x1406
GL_BLEND, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_COLOR_BUFFER_BIT = 0x0BE2, 1, 0x0303, 0x4000
GL_DEPTH_TEST, GL_CULL_FACE, GL_SCISSOR_TEST = 0x0B71, 0x0B44, 0x0C11
GL_MAX_TEXTURE_SIZE = 0x0D33


# ───────────────────────── the scene: atlas + vertex data of a rig (no GL here) ─────────────────────────
class Scene:
    """Everything a rig needs on the GPU, as numpy arrays. build_atlas() when the pictures change, build_geom() when the mesh / bones / parts
    change, frame() for every drawn frame (the pose)."""
    _ids = 0

    def __init__(self):
        Scene._ids += 1; self.id = Scene._ids; self.akey = None; self.gkey = None; self.atlas = np.zeros((4, 4, 4), np.uint8); self.rects = {}; self.parts = []; self.fkey = None
        self.P = self.UV = self.BI = self.BW = None; self.bone_ids = []; self.counts = []; self.tris = []; self.M = 0; self.atlas_hw = (4, 4)

    # ---- the atlas
    def build_atlas(self, rig, maxtex=4096):
        used = {}
        for p in rig["parts"]:
            iid = p.get("img"); im = rig["images"].get(iid)
            if im and iid not in used: used[iid] = im.setdefault("_k", uuid.uuid4().hex)
        key = (tuple(sorted(used.items())), maxtex)
        if key == self.akey: return False
        ims = {}
        for iid in used:
            a = B._decode(rig["images"][iid], cache=False)             # Patch 46: the decoded picture is not kept (it lives in the atlas)
            if a is not None: ims[iid] = (a, used[iid])
        self.akey = key; self.gkey = None; g = GUTTER; self.rects = {}
        if not ims: self.atlas = np.zeros((4, 4, 4), np.uint8); self.atlas_hw = (4, 4); return True
        items = sorted(ims.items(), key=lambda kv: -kv[1][0].shape[0]); s = min(1.0, (maxtex - 2 * g) / float(max(max(a.shape[:2]) for i, (a, k) in items)))
        while True:
            sz = [(i, max(1, int(round(a.shape[1] * s))), max(1, int(round(a.shape[0] * s)))) for i, (a, k) in items]
            area = sum((w + 2 * g) * (h + 2 * g) for _, w, h in sz); mw = max(w + 2 * g for _, w, h in sz)
            AW = min(maxtex, max(mw, 1 << int(math.ceil(math.log2(max(64.0, math.sqrt(area * 1.12)))))))
            x = y = rowh = 0; pos = {}
            for i, w, h in sz:
                if x + w + 2 * g > AW: x = 0; y += rowh; rowh = 0
                pos[i] = (x + g, y + g, w, h); x += w + 2 * g; rowh = max(rowh, h + 2 * g)
            AH = y + rowh
            if AH <= maxtex: break
            s *= 0.85
        AH = (AH + 3) // 4 * 4; atlas = np.zeros((AH, AW, 4), np.uint8)
        for i, (a, k) in ims.items():
            x, y, w, h = pos[i]; oh, ow = a.shape[:2]
            if (w, h) != (ow, oh): a = cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)
            atlas[y:y + h, x:x + w] = a[..., [2, 1, 0, 3]]                          # BGRA -> RGBA (premultiplied)
            self.rects[i] = (x, y, w, h, ow, oh)
        self.atlas = atlas; self.atlas_hw = atlas.shape[:2]; return True

    # ---- the vertices
    def build_geom(self, rig, key):
        if key is not None and key == self.gkey: return
        self.gkey = key; self.fkey = None
        bones = B.bone_order(rig); bidx = {b["id"]: i for i, b in enumerate(bones)}; nb = len(bones); own = {b["id"]: b.get("owner") for b in bones}
        AH, AW = self.atlas_hw; Ps, UVs, BIs, BWs, T = [], [], [], [], []; self.parts = []; self.counts = []; self.tris = []; off = 0
        for p in B.sorted_parts(rig):
            rc = self.rects.get(p.get("img"))
            if rc is None: continue
            rx, ry, rw, rh, ow, oh = rc; m = p.get("mesh"); base = B.mat(p["x"], p["y"], p["rot"], p["sx"] / 100.0, p["sy"] / 100.0)
            if m and m.get("t"):
                V = np.asarray(m["v"], np.float64).reshape(-1, 2); UVp = np.asarray(m["uv"], np.float64).reshape(-1, 2); tri = np.asarray(m["t"], np.int64).reshape(-1, 3)
            else:
                hw, hh = ow / 2.0, oh / 2.0; V = UVp = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]], np.float64); tri = np.array([[0, 1, 2], [0, 2, 3]], np.int64); m = None
            n = len(V); Pw = V @ base[:2, :2].T + base[:2, 2]
            q = np.clip(UVp + [ow / 2.0, oh / 2.0], -GUTTER + 0.5, [ow + GUTTER - 0.5, oh + GUTTER - 0.5]) * [rw / float(ow), rh / float(oh)] + [rx, ry]
            q = q / [float(AW), float(AH)]
            gb = bidx.get(p.get("bone"), nb); bi = np.full((n, 4), nb, np.int32); bw = np.zeros((n, 4), np.float32)
            if m:
                for i, ws in enumerate(m["w"]):
                    lst, rem = B.eff_weights(ws, lambda b: b in bidx and own.get(b) in (None, p["id"]))          # Patch 49: independent weights, scaled to 1 only when they add up to more than 1
                    lst = sorted(lst, key=lambda t: -t[1]); keep = 3 if rem > 0.001 else 4; lst = lst[:keep]; tot = sum(w for _b, w in lst)
                    want = 1.0 - rem if rem > 0.001 else (1.0 if lst else 0.0)
                    if tot > 1e-9: lst = [(b, w * want / tot) for b, w in lst]
                    for k, (bj, w) in enumerate(lst): bi[i, k] = bidx[bj]; bw[i, k] = w
                    if rem > 0.001 or not lst: bi[i, 3] = gb; bw[i, 3] = rem if lst else 1.0
            else: bi[:, 3] = gb; bw[:, 3] = 1.0
            Ps.append(Pw); UVs.append(q); BIs.append(bi); BWs.append(bw); T.append((tri + off).astype(np.uint32).ravel()); self.parts.append(p["id"]); self.counts.append(n); self.tris.append(T[-1]); off += n
        self.bone_ids = [b["id"] for b in bones]; self.M = off
        if off:
            self.P = np.concatenate(Ps).astype(np.float32); self.UV = np.concatenate(UVs).astype(np.float32); self.BI = np.concatenate(BIs); self.BW = np.concatenate(BWs)
        else: self.P = np.zeros((0, 2), np.float32); self.UV = np.zeros((0, 2), np.float32); self.BI = np.zeros((0, 4), np.int32); self.BW = np.zeros((0, 4), np.float32)
        self.vbuf = np.zeros((off, 5), np.float32); self.vbuf[:, 2:4] = self.UV; self.starts = np.r_[0, np.cumsum(self.counts)[:-1]].astype(np.int64) if self.counts else np.zeros(0, np.int64)

    def skin(self, pose, rest):
        """World positions of every vertex of every part for this pose (one numpy pass)."""
        nb = len(self.bone_ids); SM = np.zeros((nb + 1, 3, 3), np.float32); SM[nb] = np.eye(3)
        for i, b in enumerate(self.bone_ids):
            SM[i] = (pose[b] @ np.linalg.inv(rest[b])) if (b in pose and b in rest) else np.eye(3)
        out = np.zeros((self.M, 2), np.float32); P = self.P
        for j in range(4):
            Mj = SM[self.BI[:, j]]; w = self.BW[:, j]
            out[:, 0] += w * (Mj[:, 0, 0] * P[:, 0] + Mj[:, 0, 1] * P[:, 1] + Mj[:, 0, 2]); out[:, 1] += w * (Mj[:, 1, 0] * P[:, 0] + Mj[:, 1, 1] * P[:, 1] + Mj[:, 1, 2])
        return out

    def frame(self, rig, pose, rest, parts_alpha=None, solo=None, skinned=None):
        """(vertex array (M, 5) = x y u v alpha, index array) of the visible parts, back to front."""
        pos = self.skin(pose, rest) if skinned is None else skinned; self.vbuf[:, :2] = pos
        pm = {p["id"]: p for p in rig["parts"]}; hid = {g["id"] for g in rig.get("groups", []) if g.get("hidden")}; ga = {g["id"]: g.get("alpha", 100.0) / 100.0 for g in rig.get("groups", [])}
        ops = np.zeros(len(self.parts), np.float32); idx = []
        for k, pid in enumerate(self.parts):
            p = pm.get(pid)
            if p is None or not p.get("visible", True) or p.get("group") in hid: continue
            if solo is not None and pid not in solo: continue
            op = max(0.0, min(1.0, p.get("alpha", 100.0) / 100.0 * ga.get(p.get("group"), 1.0))) * (parts_alpha.get(pid, 1.0) if parts_alpha else 1.0)
            if op <= 0.001: continue
            ops[k] = op; idx.append(self.tris[k])
        self.vbuf[:, 4] = np.repeat(ops, self.counts) if self.counts else 0.0
        return self.vbuf, (np.concatenate(idx) if idx else np.zeros(0, np.uint32))


# ───────────────────────── the GL side ─────────────────────────
VS = """
attribute vec2 aPos; attribute vec2 aUV; attribute float aA; uniform vec2 uSc; uniform vec2 uOff;
varying vec2 vUV; varying float vA;
void main(){ gl_Position = vec4(aPos * uSc + uOff, 0.0, 1.0); vUV = aUV; vA = aA; }
"""
FS = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D uTex; varying vec2 vUV; varying float vA;
void main(){ gl_FragColor = texture2D(uTex, vUV) * vA; }
"""
VS_C = """
attribute vec2 aPos; attribute vec4 aCol; uniform vec2 uSc; uniform vec2 uOff; varying vec4 vC;
void main(){ gl_Position = vec4(aPos * uSc + uOff, 0.0, 1.0); vC = aCol; }
"""
FS_C = """
#ifdef GL_ES
precision mediump float;
#endif
varying vec4 vC;
void main(){ gl_FragColor = vC; }
"""


class GLPainter:
    """GL objects of one context: shaders, buffers and the atlas textures (one per scene)."""
    def __init__(self, ctx):
        from PySide6.QtOpenGL import QOpenGLShaderProgram, QOpenGLShader, QOpenGLBuffer
        self.ctx = ctx; self.f = ctx.functions(); self.tex = OrderedDict(); self.max_tex = 4096
        try: self.max_tex = int(min(8192, max(1024, self.f.glGetIntegerv(GL_MAX_TEXTURE_SIZE))))
        except Exception: pass
        def prog(vs, fs):
            p = QOpenGLShaderProgram(); ok = p.addShaderFromSourceCode(QOpenGLShader.Vertex, vs) and p.addShaderFromSourceCode(QOpenGLShader.Fragment, fs) and p.link()
            if not ok: raise RuntimeError("shader: " + p.log())
            return p
        self.prog = prog(VS, FS); self.cprog = prog(VS_C, FS_C)
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer); self.vbo.create()

    def destroy(self):
        for k, (key, t) in list(self.tex.items()):
            try: t.destroy()
            except Exception: pass
        self.tex.clear()

    def atlas_texture(self, scene, smooth):
        from PySide6.QtGui import QImage
        from PySide6.QtOpenGL import QOpenGLTexture
        key = (scene.akey, bool(smooth)); hit = self.tex.get(scene.id)
        if hit is not None and hit[0] == key: self.tex.move_to_end(scene.id); return hit[1]
        if hit is not None:
            try: hit[1].destroy()
            except Exception: pass
        a = np.ascontiguousarray(scene.atlas); h, w = a.shape[:2]
        img = QImage(a.data, w, h, w * 4, QImage.Format_RGBA8888).copy()                  # premultiplied data, tagged plain so Qt does not convert it
        t = QOpenGLTexture(QOpenGLTexture.Target2D); t.setAutoMipMapGenerationEnabled(True); t.setData(img, QOpenGLTexture.GenerateMipMaps if smooth else QOpenGLTexture.DontGenerateMipMaps)
        if smooth: t.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear); t.setMagnificationFilter(QOpenGLTexture.Linear)
        else: t.setMinificationFilter(QOpenGLTexture.Nearest); t.setMagnificationFilter(QOpenGLTexture.Nearest)
        t.setWrapMode(QOpenGLTexture.ClampToEdge); self.tex[scene.id] = (key, t)
        while len(self.tex) > 6:
            k0, (kk, t0) = next(iter(self.tex.items())); self.tex.pop(k0)
            try: t0.destroy()
            except Exception: pass
        return t

    def begin(self, w, h, clear=None):
        f = self.f; f.glViewport(0, 0, int(w), int(h))
        for cap in (GL_DEPTH_TEST, GL_CULL_FACE, GL_SCISSOR_TEST): f.glDisable(cap)
        if clear is not None: f.glClearColor(*clear); f.glClear(GL_COLOR_BUFFER_BIT)
        f.glEnable(GL_BLEND); f.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)

    def _upload(self, verts, idx):
        """The triangles as a plain vertex list (glDrawElements is not usable through PySide, glDrawArrays is as fast for these sizes)."""
        v = np.ascontiguousarray(verts[np.asarray(idx, np.int64)], np.float32); self.vbo.bind(); self.vbo.allocate(v.tobytes(), v.nbytes); return len(v)

    def draw_scene(self, scene, verts, idx, sc, off, smooth=True):
        """sc / off: world -> clip space (x' = x * sc[0] + off[0], y' = y * sc[1] + off[1])."""
        from PySide6.QtGui import QVector2D
        if not len(idx): return
        f = self.f; tex = self.atlas_texture(scene, smooth); n = self._upload(verts, idx); p = self.prog; p.bind(); tex.bind(0)
        p.setUniformValue("uSc", QVector2D(*sc)); p.setUniformValue("uOff", QVector2D(*off))
        st = verts.shape[1] * 4
        for name, o, k in (("aPos", 0, 2), ("aUV", 8, 2), ("aA", 16, 1)):
            loc = p.attributeLocation(name); p.enableAttributeArray(loc); p.setAttributeBuffer(loc, GL_FLOAT, o, k, st)
        f.glDrawArrays(GL_TRIANGLES, 0, n)
        for name in ("aPos", "aUV", "aA"): p.disableAttributeArray(p.attributeLocation(name))
        tex.release(); self.vbo.release(); p.release()

    def draw_colored(self, xy, rgba, idx, sc, off):
        """Triangles with a colour per vertex (premultiplied rgba 0..1): the paper, the weight heat map."""
        from PySide6.QtGui import QVector2D
        if not len(idx): return
        v = np.ascontiguousarray(np.concatenate([np.asarray(xy, np.float32).reshape(-1, 2), np.asarray(rgba, np.float32).reshape(-1, 4)], 1)); n = self._upload(v, np.asarray(idx, np.uint32))
        p = self.cprog; p.bind(); p.setUniformValue("uSc", QVector2D(*sc)); p.setUniformValue("uOff", QVector2D(*off))
        for name, o, k in (("aPos", 0, 2), ("aCol", 8, 4)):
            loc = p.attributeLocation(name); p.enableAttributeArray(loc); p.setAttributeBuffer(loc, GL_FLOAT, o, k, 24)
        self.f.glDrawArrays(GL_TRIANGLES, 0, n)
        for name in ("aPos", "aCol"): p.disableAttributeArray(p.attributeLocation(name))
        self.vbo.release(); p.release()


def quad_indices(n):
    """Indices of n quads made of 4 vertices each."""
    b = np.arange(n, dtype=np.uint32)[:, None] * 4; return (b + np.array([0, 1, 2, 0, 2, 3], np.uint32)).ravel()


# ───────────────────────── the background renderer (preview / export / thumbnails) ─────────────────────────
class _State:
    surf = None; fmt = None; thread = None; q = None; failed = False; lock = threading.Lock(); ready = threading.Event(); err = ""


_S = _State()


def surface_format():
    from PySide6.QtGui import QSurfaceFormat
    f = QSurfaceFormat(); f.setRenderableType(QSurfaceFormat.OpenGL); f.setVersion(2, 1); f.setProfile(QSurfaceFormat.NoProfile); f.setSamples(0); f.setDepthBufferSize(0); f.setStencilBufferSize(0); return f


def init():
    """Call once from the GUI thread (the hidden surface has to be made there). Safe to call again."""
    if _S.surf is not None or _S.failed: return _S.surf is not None
    try:
        from PySide6.QtGui import QGuiApplication, QOffscreenSurface
        from PySide6.QtCore import QThread
        app = QGuiApplication.instance()
        if app is None or QThread.currentThread() != app.thread(): return False
        s = QOffscreenSurface(); s.setFormat(surface_format()); s.create()
        if not s.isValid(): _S.failed = True; return False
        _S.surf = s; _S.fmt = s.format(); return True
    except Exception as ex:
        _S.failed = True; _S.err = str(ex); return False


def available(): return _S.surf is not None and not _S.failed


def _loop():
    from PySide6.QtGui import QOpenGLContext
    try:
        ctx = QOpenGLContext(); ctx.setFormat(surface_format())
        if not ctx.create() or not ctx.makeCurrent(_S.surf): raise RuntimeError("no OpenGL context")
        painter = GLPainter(ctx); st = {"painter": painter, "ctx": ctx, "scenes": OrderedDict(), "fbo": None}
    except Exception as ex:
        _S.failed = True; _S.err = str(ex); _S.ready.set()
        while True:
            job = _S.q.get()
            if job is None: return
            job[0].set_exception(RuntimeError("opengl unavailable"))
    _S.ready.set()
    while True:
        job = _S.q.get()
        if job is None: break
        fut, fn = job
        try: fut.set_result(fn(st))
        except Exception as ex: fut.set_exception(ex)
    try: painter.destroy(); ctx.doneCurrent()
    except Exception: pass


def _submit(fn, timeout=60.0):
    if not available(): raise RuntimeError("opengl unavailable")
    with _S.lock:
        if _S.thread is None:
            _S.q = queue.Queue(); _S.thread = threading.Thread(target=_loop, name="bone2d-gl", daemon=True); _S.thread.start()
    if not _S.ready.wait(timeout): raise RuntimeError("opengl start timeout")
    if _S.failed: raise RuntimeError("opengl unavailable: " + _S.err)
    fut = Future(); _S.q.put((fut, fn)); return fut.result(timeout)


def shutdown():
    if _S.thread is not None and _S.q is not None: _S.q.put(None)


def _scene_for(st, rig, key):
    sc = st["scenes"].get(key)
    if sc is None:
        sc = Scene(); st["scenes"][key] = sc
        while len(st["scenes"]) > 6:
            k0, s0 = st["scenes"].popitem(last=False); st["painter"].tex.pop(s0.id, None)
    else: st["scenes"].move_to_end(key)
    return sc


def unpremultiply(img):
    """BGRA premultiplied uint8 -> straight alpha BGRA uint8, in place. Only the soft edge pixels (0 < alpha < 255) need any arithmetic: the rest
    are either fully opaque (unchanged) or fully clear (colour 0), so a 1080p frame no longer costs a full-frame uint32 pass."""
    img = np.ascontiguousarray(img); flat = img.reshape(-1, 4); al = flat[:, 3]
    clear = np.flatnonzero(al == 0)
    if len(clear): flat[clear, :3] = 0
    soft = np.flatnonzero((al > 0) & (al < 255))
    if len(soft):
        sub = flat[soft]; a = sub[:, 3:4].astype(np.uint32); flat[soft, :3] = np.minimum((sub[:, :3].astype(np.uint32) * 255 + a // 2) // a, 255).astype(np.uint8)
    return img


def render(rig, key, pose, rest, W, H, ds, parts_alpha=None, solo=None, smooth=True, bg=None, ver=0):
    """The rig as a straight-alpha BGRA picture W x H (None when OpenGL cannot do it: the caller then draws on the CPU)."""
    if not available() or W > 4096 or H > 4096: return None
    def job(st):
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        pa = st["painter"]; sc = _scene_for(st, rig, key)
        sc.build_atlas(rig, pa.max_tex); sc.build_geom(rig, (key, ver))
        fb = st["fbo"]
        if fb is None or fb.size().width() != W or fb.size().height() != H:
            fmt = QOpenGLFramebufferObjectFormat(); fmt.setSamples(4); fmt.setAttachment(QOpenGLFramebufferObject.NoAttachment)
            fb = QOpenGLFramebufferObject(W, H, fmt)
            if not fb.isValid(): fmt.setSamples(0); fb = QOpenGLFramebufferObject(W, H, fmt)
            st["fbo"] = fb
        verts, idx = sc.frame(rig, pose, rest, parts_alpha, solo)
        fb.bind(); pa.begin(W, H, bg if bg is not None else (0.0, 0.0, 0.0, 0.0))
        ssx, ssy = 2.0 * ds / W, -2.0 * ds / H; pa.draw_scene(sc, verts, idx, (ssx, ssy), (0.0, 0.0), smooth)
        pa.f.glFlush(); img = fb.toImage(); fb.release()      # Patch 45: toImage() syncs by itself; glFinish was a second, useless stall
        h_, w_ = img.height(), img.width(); bpl = img.bytesPerLine(); arr = np.frombuffer(img.constBits(), np.uint8, count=bpl * h_).reshape(h_, bpl // 4, 4)[:, :w_]
        return np.array(arr, copy=True)               # a real copy: `arr` points into the QImage, which is freed when this function returns (ascontiguousarray does not copy an already contiguous array)
    out = _submit(job)
    return unpremultiply(out)

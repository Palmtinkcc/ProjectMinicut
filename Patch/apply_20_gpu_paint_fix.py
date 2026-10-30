#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 20: FIX FOR THE CRASH IN THE GPU TEST
==========================================================
Install AFTER apply_19_viewport_engine.py.

The program closed itself with "QPaintDevice: Cannot destroy paint device that is being painted" when the GPU self-test
ran (at the first frame that is played, and when Test GPU is pressed). Cause: the OpenGL paint device was created inside
the QPainter(...) call without a name, so Python destroyed it at once while the painter was still drawing on it.
Now the device has a name and lives until the painter has ended, the painter is always ended (also after an error), and
the painter is started with begin() so a failure to start is reported instead of crashing.

Notes in gpu_state.json written by the earlier version (for example "the program crashed while testing") are ignored, so
the GPU is tested again by itself the next time; there is no need to press Test GPU first.

Changed file: minicut/render/gpu.py (the original is backed up first)

    python apply_20_gpu_paint_fix.py            install the update
    python apply_20_gpu_paint_fix.py --check    only show what would change
    python apply_20_gpu_paint_fix.py --revert   undo the last install
    python apply_20_gpu_paint_fix.py --force    install even if you edited this file yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {'minicut/render/gpu.py': {'base': 'b3df5b42bf864f026959d4fd78ff4110cae8f217a6a9cee72600f5cc682b341c',
                           'content': '"""Optional GPU compositing (OpenGL through Qt), with a self-test and a crash guard.\n'
                                      '\n'
                                      'The picture is still prepared on the CPU (decoding, effects). What moves to the GPU is placing the layers: scaling,\n'
                                      'rotating, opacity and blending, which is the expensive part. The GPU draws into an off-screen buffer on the render\n'
                                      'thread, and the finished picture is read back as before, so nothing else in the program changes.\n'
                                      '\n'
                                      'Safety:\n'
                                      '  * At the first use a small test scene is drawn by the GPU and by the CPU. If the two pictures do not match (or\n'
                                      '    anything fails) the GPU is not used. The program also tries upside-down and red/blue-swapped results and corrects '
                                      'them.\n'
                                      "  * Before the test a note 'probing' is written to gpu_state.json. If the program crashed inside the test, the next\n"
                                      '    start sees that note and keeps the GPU off. The Test GPU button in Settings tries again.\n'
                                      '  * Any error while drawing switches to the CPU for the rest of the session."""\n'
                                      'import json, os, threading\n'
                                      'import cv2\n'
                                      'import numpy as np\n'
                                      'from ..shared.core import APP_DIR\n'
                                      'from .fastcomp import blend_into, to_cv_matrix\n'
                                      '\n'
                                      'STATE_FILE = os.path.join(APP_DIR, "gpu_state.json")\n'
                                      'GPU_ENGINE = 2        # notes written by an older version of this file are ignored (their failures may have been '
                                      'fixed)\n'
                                      '\n'
                                      '\n'
                                      'def _read():\n'
                                      '    try:\n'
                                      '        with open(STATE_FILE, encoding="utf-8") as f: d = json.load(f)\n'
                                      '        return d if d.get("engine") == GPU_ENGINE else {}\n'
                                      '    except Exception: return {}\n'
                                      '\n'
                                      '\n'
                                      'def _write(d):\n'
                                      '    try:\n'
                                      '        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)\n'
                                      '        with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(dict(d, engine=GPU_ENGINE) if d else {}, f)\n'
                                      '    except Exception: pass\n'
                                      '\n'
                                      '\n'
                                      'def premultiply(img):\n'
                                      '    out = img.copy(); a = img[..., 3:4].astype(np.uint16)\n'
                                      '    out[..., :3] = (img[..., :3].astype(np.uint16) * a // 255).astype(np.uint8)\n'
                                      '    return out\n'
                                      '\n'
                                      '\n'
                                      'def reference_composite(layers, W, H, bgr):\n'
                                      '    """The same layers placed by the CPU (warp + blend). Used by the self-test and by the tests."""\n'
                                      '    canvas = np.empty((H, W, 3), np.uint8); canvas[:] = bgr\n'
                                      '    for img, M, op in layers:\n'
                                      '        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)\n'
                                      '        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)\n'
                                      '        lay = cv2.warpAffine(img, to_cv_matrix(M), (W, H), flags=cv2.INTER_LINEAR,\n'
                                      '                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))\n'
                                      '        blend_into(canvas, np.ascontiguousarray(lay[..., :3]), np.ascontiguousarray(lay[..., 3]), op)\n'
                                      '    return canvas\n'
                                      '\n'
                                      '\n'
                                      'def test_scene():\n'
                                      '    """A scene that shows any flip or colour swap: four colour quadrants with a white marker in one corner."""\n'
                                      '    W, H = 320, 240; bgr = (50, 40, 30)\n'
                                      '    a = np.zeros((100, 160, 4), np.uint8); a[..., 3] = 255\n'
                                      '    a[:50, :80] = (0, 0, 255, 255); a[:50, 80:] = (0, 255, 0, 255)       # top-left red, top-right green  (BGR order)\n'
                                      '    a[50:, :80] = (255, 0, 0, 255); a[50:, 80:] = (0, 255, 255, 255)     # bottom-left blue, bottom-right yellow\n'
                                      '    a[:12, :12] = (255, 255, 255, 255)\n'
                                      '    b = np.zeros((60, 60, 4), np.uint8); b[..., :3] = (255, 0, 255); b[..., 3] = 255\n'
                                      '    M1 = np.array([[1.5, 0, 40], [0, 1.5, 30]], np.float32)\n'
                                      '    th = np.radians(25.0); c, s = np.cos(th), np.sin(th)\n'
                                      '    M2 = np.array([[c, -s, 200 - c * 30 + s * 30], [s, c, 150 - s * 30 - c * 30]], np.float32)\n'
                                      '    return [(a, M1, 1.0), (b, M2, 0.5)], W, H, bgr\n'
                                      '\n'
                                      '\n'
                                      'def fix_result(img, flip, swap):\n'
                                      '    if flip: img = img[::-1]\n'
                                      '    if swap: img = img[..., ::-1]\n'
                                      '    return np.ascontiguousarray(img)\n'
                                      '\n'
                                      '\n'
                                      'def self_test(comp):\n'
                                      '    """(ok, text). Draws the test scene with the GPU and compares it with the CPU picture."""\n'
                                      '    layers, W, H, bgr = test_scene()\n'
                                      '    ref = reference_composite(layers, W, H, bgr).astype(np.int16)\n'
                                      '    out = comp.draw_raw(layers, W, H, bgr)\n'
                                      '    if out is None or out.shape != (H, W, 3): return False, "the GPU returned a picture of the wrong size"\n'
                                      '    best = 1e9\n'
                                      '    for flip in (False, True):\n'
                                      '        for swap in (False, True):\n'
                                      '            d = float(np.abs(fix_result(out, flip, swap).astype(np.int16) - ref).mean()); best = min(best, d)\n'
                                      '            if d < 6.0:\n'
                                      '                comp.flip, comp.swap = flip, swap\n'
                                      '                return True, "matches the CPU picture (difference %.2f%s)" % (d, ", corrected" if (flip or swap) else '
                                      '"")\n'
                                      '    return False, "the GPU picture does not match the CPU picture (difference %.1f)" % best\n'
                                      '\n'
                                      '\n'
                                      'class GpuCompositor:\n'
                                      '    """Draws layers with QPainter on an OpenGL frame buffer (off-screen). Lives on the render thread."""\n'
                                      '    def __init__(self, surface):\n'
                                      '        self.surface = surface; self.ctx = None; self.fbo = None; self.fbo_size = None\n'
                                      '        self.flip = False; self.swap = False; self.name = "OpenGL"\n'
                                      '    def init(self):\n'
                                      '        from PySide6.QtGui import QOpenGLContext\n'
                                      '        ctx = QOpenGLContext(); ctx.setFormat(self.surface.format())\n'
                                      '        if not ctx.create(): raise RuntimeError("could not create an OpenGL context")\n'
                                      '        if not ctx.makeCurrent(self.surface): raise RuntimeError("could not use the OpenGL context")\n'
                                      '        self.ctx = ctx\n'
                                      '        try:\n'
                                      '            v = ctx.functions().glGetString(0x1F01)            # GL_RENDERER\n'
                                      '            if v: self.name = v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)\n'
                                      '        except Exception: pass\n'
                                      '        low = self.name.lower()\n'
                                      '        if any(w in low for w in ("gdi generic", "llvmpipe", "software", "swrast")):\n'
                                      '            raise RuntimeError("only software OpenGL is available (%s)" % self.name)\n'
                                      '    def _fbo(self, W, H):\n'
                                      '        if self.fbo is not None and self.fbo_size == (W, H): return self.fbo\n'
                                      '        try:\n'
                                      '            from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat\n'
                                      '        except Exception:\n'
                                      '            from PySide6.QtGui import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat\n'
                                      '        from PySide6.QtCore import QSize\n'
                                      '        fmt = QOpenGLFramebufferObjectFormat(); fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)\n'
                                      '        self.fbo = QOpenGLFramebufferObject(QSize(W, H), fmt); self.fbo_size = (W, H)\n'
                                      '        return self.fbo\n'
                                      '    @staticmethod\n'
                                      '    def _qimage(img):\n'
                                      '        from PySide6.QtGui import QImage\n'
                                      '        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)\n'
                                      '        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)\n'
                                      '        img = np.ascontiguousarray(img)\n'
                                      '        if cv2.countNonZero(cv2.compare(cv2.extractChannel(img, 3), 255, cv2.CMP_LT)): img = premultiply(img)\n'
                                      '        h, w = img.shape[:2]\n'
                                      '        return QImage(img.data, w, h, img.strides[0], QImage.Format_ARGB32_Premultiplied), img     # keep img alive\n'
                                      '    @staticmethod\n'
                                      '    def _to_bgr(qi, W, H):\n'
                                      '        from PySide6.QtGui import QImage\n'
                                      '        n = qi.sizeInBytes(); ptr = qi.constBits()\n'
                                      '        try: buf = np.frombuffer(ptr, np.uint8, count=n)\n'
                                      '        except Exception: buf = np.frombuffer(ptr.asarray(n), np.uint8)\n'
                                      '        bpl = qi.bytesPerLine(); arr = buf[:bpl * H].reshape(H, bpl)[:, :W * 4].reshape(H, W, 4)\n'
                                      '        if qi.format() in (QImage.Format_RGBA8888, QImage.Format_RGBA8888_Premultiplied): return '
                                      'np.ascontiguousarray(arr[..., 2::-1])\n'
                                      '        return np.ascontiguousarray(arr[..., :3])\n'
                                      '    def draw_raw(self, layers, W, H, bgr):\n'
                                      '        from PySide6.QtGui import QPainter, QColor, QTransform\n'
                                      '        try: from PySide6.QtOpenGL import QOpenGLPaintDevice\n'
                                      '        except Exception: from PySide6.QtGui import QOpenGLPaintDevice\n'
                                      '        if not self.ctx.makeCurrent(self.surface): raise RuntimeError("lost the OpenGL context")\n'
                                      '        fbo = self._fbo(W, H); fbo.bind()\n'
                                      '        dev = QOpenGLPaintDevice(W, H)       # a name for it: it has to stay alive until the painter has ended\n'
                                      '        p = QPainter(); keep = []\n'
                                      '        try:\n'
                                      '            if not p.begin(dev): raise RuntimeError("could not paint on the OpenGL buffer")\n'
                                      '            p.setRenderHint(QPainter.SmoothPixmapTransform, True)\n'
                                      '            p.fillRect(0, 0, W, H, QColor(int(bgr[2]), int(bgr[1]), int(bgr[0])))\n'
                                      '            for img, M, op in layers:\n'
                                      '                qi, arr = self._qimage(img); keep.append((qi, arr))\n'
                                      '                p.setOpacity(float(op))\n'
                                      '                p.setTransform(QTransform(float(M[0][0]), float(M[1][0]), float(M[0][1]), float(M[1][1]), '
                                      'float(M[0][2]), float(M[1][2])))\n'
                                      '                p.drawImage(0, 0, qi)\n'
                                      '            p.end()\n'
                                      '            out = fbo.toImage()\n'
                                      '        finally:\n'
                                      '            if p.isActive(): p.end()         # also when something went wrong half way\n'
                                      '            fbo.release()\n'
                                      '        del p, dev\n'
                                      '        return self._to_bgr(out, W, H)\n'
                                      '    def draw(self, layers, W, H, bgr):\n'
                                      '        return fix_result(self.draw_raw(layers, W, H, bgr), self.flip, self.swap)\n'
                                      '    def close(self):\n'
                                      '        try:\n'
                                      '            if self.ctx is not None: self.ctx.makeCurrent(self.surface)\n'
                                      '            self.fbo = None\n'
                                      '        except Exception: pass\n'
                                      '\n'
                                      '\n'
                                      'class GpuState:\n'
                                      '    """Whether the GPU is used, what its status is, and the self-test. usable() runs on the render thread."""\n'
                                      '    def __init__(self):\n'
                                      '        self.mode = "auto"; self.surface = None; self.comp = None; self.status = "not started yet"\n'
                                      '        self.disabled = False; self._tried = False; self.reset_requested = False; self.make_comp = GpuCompositor\n'
                                      '        self.lock = threading.Lock()\n'
                                      '    def set_mode(self, mode):\n'
                                      '        if mode not in ("auto", "off", "on"): mode = "auto"\n'
                                      '        if mode != self.mode:\n'
                                      '            self.mode = mode\n'
                                      '            if mode != "off": self.reset_requested = True\n'
                                      '            else: self.status = "off (CPU only)"\n'
                                      '    def retry(self):\n'
                                      '        """Test GPU button: forget the old result and probe again on the next preview frame."""\n'
                                      '        _write({}); self.reset_requested = True; self.status = "testing ..."\n'
                                      '    def fail(self, why):\n'
                                      '        self.disabled = True; self.status = "off: " + why; _write({"status": "failed", "reason": why})\n'
                                      '    def usable(self):\n'
                                      '        if self.mode == "off": return False\n'
                                      '        if self.reset_requested:\n'
                                      '            self.reset_requested = False\n'
                                      '            if self.comp is not None: self.comp.close()\n'
                                      '            self.comp = None; self.disabled = False; self._tried = False\n'
                                      '        if self.comp is not None: return True\n'
                                      '        if self.disabled or self._tried: return False\n'
                                      '        return self._probe()\n'
                                      '    def _probe(self):\n'
                                      '        self._tried = True\n'
                                      '        if self.surface is None: self.disabled = True; self.status = "off: no OpenGL surface"; return False\n'
                                      '        st = _read()\n'
                                      '        if self.mode == "auto":\n'
                                      '            if st.get("status") == "probing":\n'
                                      '                self.fail("the program crashed while testing the GPU last time"); return False\n'
                                      '            if st.get("status") == "failed":\n'
                                      '                self.disabled = True; self.status = "off: " + str(st.get("reason", "failed before")) + "  (press Test '
                                      'GPU to try again)"; return False\n'
                                      '        _write({"status": "probing"})\n'
                                      '        try:\n'
                                      '            comp = self.make_comp(self.surface); comp.init(); ok, why = self_test(comp)\n'
                                      '        except Exception as ex:\n'
                                      '            ok, why, comp = False, "error: %s" % (ex,), None\n'
                                      '        if ok:\n'
                                      '            self.comp = comp; self.status = "active: %s, %s" % (getattr(comp, "name", "OpenGL"), why)\n'
                                      '            _write({"status": "ok", "name": getattr(comp, "name", "")}); return True\n'
                                      '        if comp is not None: comp.close()\n'
                                      '        self.fail(why); return False\n'
                                      '    def draw(self, layers, W, H, bgr):\n'
                                      '        return self.comp.draw(layers, W, H, bgr)\n'
                                      '\n'
                                      '\n'
                                      'GPU = GpuState()\n'
                                      '\n'
                                      '\n'
                                      'def install_surface():\n'
                                      '    """Call once on the GUI thread: the off-screen surface has to be made there."""\n'
                                      '    try:\n'
                                      '        from PySide6.QtGui import QOffscreenSurface, QSurfaceFormat\n'
                                      '        s = QOffscreenSurface(); s.setFormat(QSurfaceFormat.defaultFormat()); s.create()\n'
                                      '        if s.isValid(): GPU.surface = s\n'
                                      '        else: GPU.status = "off: no OpenGL surface"\n'
                                      '    except Exception as ex:\n'
                                      '        GPU.status = "off: %s" % (ex,)\n',
                           'new': 'ebdea6a1a2f01f056ad9d2423f34779873142b07677060de867039903eec3433'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "gpu_paint_fix"
try: sys.stdout.reconfigure(errors="replace")
except Exception: pass


def norm_hash(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
def path_of(rel): return os.path.join(HERE, *rel.split("/"))
def read(rel):
    p = path_of(rel)
    return open(p, "rb").read() if os.path.exists(p) else None
def say(msg=""): print(msg, flush=True)


def edited_text(rel, raw):
    """New bytes for a text-edited file. Raises ValueError if an expected text is not found exactly once."""
    info = EDITS[rel]
    text = raw.decode("utf-8"); crlf = "\r\n" in text; t = text.replace("\r\n", "\n")
    for old, new in info["edits"]:
        n = t.count(old)
        if n != 1: raise ValueError("%s: expected the patch text exactly once, found %d times" % (rel, n))
        t = t.replace(old, new, 1)
    return (t.replace("\n", "\r\n") if crlf else t).encode("utf-8")


def plan():
    """Work out what happens to every file. Nothing is written here."""
    rows, outputs = [], {}
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        cur = read(rel)
        if cur is None:
            rows.append((rel, "missing", "file not found: install the previous update first")); continue
        if norm_hash(cur) == info["new"]:
            rows.append((rel, "same", "already up to date")); continue
        if norm_hash(cur) != info["base"]:
            rows.append((rel, "edited", "differs from the version this patch was made for")); continue
        try:
            outputs[rel] = edited_text(rel, cur) if rel in EDITS else info["content"].encode("utf-8")
            rows.append((rel, "ok", "will be updated"))
        except ValueError as ex:
            rows.append((rel, "edited", str(ex)))
    for rel, src in NEW_FILES.items():
        cur = read(rel)
        if cur is None: rows.append((rel, "new", "will be created")); outputs[rel] = src.encode("utf-8")
        elif cur.decode("utf-8", "replace") == src: rows.append((rel, "same", "already up to date"))
        else: rows.append((rel, "edited", "already exists and differs from this patch"))
    return rows, outputs


def import_ok():
    code = "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; import minicut.app"
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=180)
        return r.returncode == 0, (r.stderr or r.stdout)[-1500:]
    except Exception as ex: return False, str(ex)


def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    ds = sorted(d for d in os.listdir(BACKUP_ROOT) if os.path.exists(os.path.join(BACKUP_ROOT, d, "MANIFEST.json")))
    return os.path.join(BACKUP_ROOT, ds[-1]) if ds else None


def revert(bdir):
    man = json.load(open(os.path.join(bdir, "MANIFEST.json"), encoding="utf-8"))
    for rel in man["replaced"]: shutil.copy2(os.path.join(bdir, *rel.split("/")), path_of(rel))
    for rel in man["created"]:
        if os.path.exists(path_of(rel)): os.remove(path_of(rel))
    say("Restored %d file(s), removed %d new file(s) from %s" % (len(man["replaced"]), len(man["created"]), bdir))


def main():
    if not os.path.isfile(path_of("minicut/app.py")):
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_20_gpu_paint_fix.py in the MiniCut folder (next to file.py) and run it again."); return 2
    if "--revert" in sys.argv:
        b = latest_backup()
        if not b: say("No backup found in _patch_backup/."); return 1
        revert(b); return 0
    rows, outputs = plan()
    say("MiniCut update: proxy bar, proxy settings, node page\n")
    for rel, st, note in rows: say("  %-40s %s" % (rel, note))
    say()
    if "--check" in sys.argv: return 0
    if all(st == "same" for _, st, _ in rows): say("Nothing to do: the update is already installed."); return 0
    if any(st == "missing" for _, st, _ in rows):
        say("STOPPED. A required file is missing:\n  " + "\n  ".join(rel for rel, st, _ in rows if st == "missing") +
            "\nInstall the previous update (apply_19_viewport_engine.py) first."); return 3
    bad = [rel for rel, st, _ in rows if st == "edited"]
    if bad and "--force" not in sys.argv:
        say("STOPPED. These files are not in the state this patch expects:\n  " + "\n  ".join(bad) +
            "\nIf the previous update is not installed yet, install it first.\n"
            "Otherwise your edits would be overwritten (they are backed up first). Run with --force to continue anyway.")
        return 3
    if bad:
        for rel in bad:
            try:
                if rel in EDITS: outputs[rel] = edited_text(rel, read(rel))
                elif rel in REPLACE: outputs[rel] = REPLACE[rel]["content"].encode("utf-8")
            except ValueError as ex: say("STOPPED: %s" % ex); return 3
    base_ok, _ = import_ok()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); bdir = os.path.join(BACKUP_ROOT, stamp); replaced, created = [], []
    os.makedirs(bdir, exist_ok=True)
    for rel in outputs:
        cur = path_of(rel)
        if os.path.exists(cur):
            dst = os.path.join(bdir, *rel.split("/")); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(cur, dst); replaced.append(rel)
        else: created.append(rel)
    json.dump({"patch": PATCH_NAME, "created": created, "replaced": replaced}, open(os.path.join(bdir, "MANIFEST.json"), "w", encoding="utf-8"), indent=1)
    try:
        for rel, data in outputs.items():
            p = path_of(rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f: f.write(data)
            if rel.endswith(".py"): py_compile.compile(p, doraise=True)
    except Exception as ex:
        say("ERROR while writing files: %s\nRestoring the backup ..." % ex); revert(bdir); return 1
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        if norm_hash(read(rel)) != info["new"]:
            say("ERROR: %s did not come out as expected, restoring the backup." % rel); revert(bdir); return 1
    ok, err = import_ok()
    if base_ok and not ok:
        say("The program no longer imports after the update, restoring the backup.\n" + err); revert(bdir); return 1
    for sub in ("minicut/render", "minicut/workspace", "minicut/shared"):
        shutil.rmtree(os.path.join(path_of(sub), "__pycache__"), ignore_errors=True)
    say("Done. %d file(s) updated, %d created.  Backup: %s" % (len(replaced), len(created), bdir))
    say("Start MiniCut as usual (Run_MiniCut.bat). Node page: pick a media on the left to edit its nodes.")
    say("To undo:  python apply_20_gpu_paint_fix.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

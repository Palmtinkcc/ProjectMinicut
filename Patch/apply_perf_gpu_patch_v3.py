#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 3: PREVIEW PERFORMANCE (phase 1)
=====================================================
Install AFTER apply_perf_gpu_patch_v2.py.

What changes:
  * Preview proxies: while a video is in the project, a small copy (540p, every frame a keyframe) is made in the
    background (folder ~/.minicut/proxies). The preview reads the proxy, so seeking is fast.
    Export and the layout size still use the original file. Setting: "Smooth preview: use small background proxy copies".
  * Less work on every playback tick: the project is copied only when it changes, and the preview cache key uses
    a version number instead of converting the whole project to JSON for every frame.

Not in this patch yet: prefetch thread (proxies already make seeking cheap, so it is left for later).

Only these files are changed (originals are backed up first):
  minicut/render/renderer.py, minicut/render/media.py, minicut/app.py, minicut/shared/core.py, minicut/shared/dialogs.py

    python apply_perf_gpu_patch_v3.py            install the update
    python apply_perf_gpu_patch_v3.py --check    only show what would change
    python apply_perf_gpu_patch_v3.py --revert   undo the last install
    python apply_perf_gpu_patch_v3.py --force    install even if you edited one of the files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

EDITS = {'minicut/app.py': {'base': 'ebd5f0340e82c3ed2352540a472b23027a4c9caa6cf4ed0fe865be7a5920d9a5',
                    'crlf': False,
                    'edits': [('self.pool=MediaPool();', "self.pool=MediaPool(use_proxy=self.settings['proxy_preview']);"),
                              ('        if d.exec():\n            self.apply_preview_fps()\n',
                               '        if d.exec():\n'
                               '            self.apply_preview_fps()\n'
                               "            if self.pool.use_proxy != self.settings['proxy_preview']:\n"
                               "                with self.renderer._src_lock: self.pool.use_proxy = self.settings['proxy_preview']; self.pool.src.clear()\n"
                               '                self.renderer.clear_preview_cache()\n')],
                    'new': '0d8434c6430afbbb3d31500cd09d308d8e5df2b2227c096a3a2cb4fdb9e01f09'},
 'minicut/render/media.py': {'base': '9557f646b3ce868f74dc1149c5c39946db8d739c9b7e97c1a322ab5f43635479',
                             'crlf': False,
                             'edits': [('class VideoSource:\n'
                                        '    def __init__(self, path):\n'
                                        '        self.cap = open_capture(safe_path(path))\n'
                                        '        if not self.cap.isOpened(): raise IOError("cannot open " + path)\n'
                                        '        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30\n'
                                        '        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)\n'
                                        '        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))\n',
                                        'PROXY_HEIGHT = 540\n'
                                        'PROXY_POOL = QThreadPool(); PROXY_POOL.setMaxThreadCount(1)   # one proxy at a time, in the background\n'
                                        '\n'
                                        '\n'
                                        'def _proxy_path(path):\n'
                                        '    import hashlib\n'
                                        '    st = os.stat(path)\n'
                                        '    key = hashlib.sha1(("%s|%d|%d" % (os.path.abspath(path), st.st_size, '
                                        'int(st.st_mtime))).encode("utf-8")).hexdigest()[:24]\n'
                                        '    d = os.path.join(APP_DIR, "proxies"); os.makedirs(d, exist_ok=True)\n'
                                        '    return os.path.join(d, key + ".mp4")\n'
                                        '\n'
                                        '\n'
                                        'def proxy_ready(path):\n'
                                        '    """Finished proxy file for this video, or None. A proxy is a small copy in which every frame is a keyframe,\n'
                                        '    so seeking in it is fast. Only the preview uses it; export always reads the original."""\n'
                                        '    try:\n'
                                        '        f = _proxy_path(path)\n'
                                        '        return f if os.path.exists(f) and os.path.getsize(f) > 0 else None\n'
                                        '    except Exception: return None\n'
                                        '\n'
                                        '\n'
                                        'def make_proxy(path):\n'
                                        '    dst = _proxy_path(path); tmp = dst + ".part.mp4"\n'
                                        '    cmd = [FFMPEG, "-y", "-v", "error", "-i", path, "-an", "-vf", "scale=-2:min(%d\\\\,ih)" % PROXY_HEIGHT,\n'
                                        '           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "1", "-pix_fmt", "yuv420p", tmp]\n'
                                        '    try:\n'
                                        '        r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN | (0x00004000 if os.name == "nt" else 0))\n'
                                        '        if r.returncode == 0 and os.path.getsize(tmp) > 0: os.replace(tmp, dst); return True\n'
                                        '    except Exception as ex: print("proxy error:", ex)\n'
                                        '    try: os.remove(tmp)\n'
                                        '    except Exception: pass\n'
                                        '    return False\n'
                                        '\n'
                                        '\n'
                                        'class _ProxyJob(QRunnable):\n'
                                        '    def __init__(self, path, cb): super().__init__(); self.path = path; self.cb = cb\n'
                                        '    def run(self):\n'
                                        '        try: ok = make_proxy(self.path)\n'
                                        '        except Exception: ok = False\n'
                                        '        self.cb(ok)\n'
                                        '\n'
                                        '\n'
                                        'class VideoSource:\n'
                                        '    def __init__(self, path, proxy=None):\n'
                                        '        # Size, fps and length always come from the original file. Frames come from the proxy when one is given.\n'
                                        '        probe = open_capture(safe_path(path))\n'
                                        '        if not probe.isOpened(): raise IOError("cannot open " + path)\n'
                                        '        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30\n'
                                        '        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)\n'
                                        '        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))\n'
                                        '        if proxy:\n'
                                        '            probe.release(); self.cap = cv2.VideoCapture(safe_path(proxy))\n'
                                        '            if not self.cap.isOpened(): raise IOError("cannot open proxy " + proxy)\n'
                                        '        else: self.cap = probe\n'),
                                       ('        if ds < 0.999: img = cv2.resize(img, (max(1, int(self.w * ds)), max(1, int(self.h * ds))), '
                                        'interpolation=cv2.INTER_AREA)\n',
                                        '        tw, th = max(1, int(self.w * ds)), max(1, int(self.h * ds))\n'
                                        '        if img.shape[1] != tw or img.shape[0] != th:\n'
                                        '            img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA if tw < img.shape[1] else '
                                        'cv2.INTER_LINEAR)\n'),
                                       ('    def __init__(self): self.src = {}; self.make_compound = None\n',
                                        '    def __init__(self, use_proxy=False): self.src = {}; self.make_compound = None; self.use_proxy = use_proxy; '
                                        'self._proxy_jobs = set()\n'
                                        '    def _video(self, p):\n'
                                        '        if not self.use_proxy: return VideoSource(p)\n'
                                        '        proxy = proxy_ready(p)\n'
                                        '        if proxy is None:\n'
                                        '            # Build the proxy in the background; when it is ready, the next get() uses it.\n'
                                        '            if p not in self._proxy_jobs:\n'
                                        '                self._proxy_jobs.add(p)\n'
                                        '                PROXY_POOL.start(_ProxyJob(p, lambda ok, p=p: self.src.pop(p, None) if ok else '
                                        'self._proxy_jobs.discard(p)))\n'
                                        '            return VideoSource(p)\n'
                                        '        return VideoSource(p, proxy)\n'),
                                       ('self.src[p] = VideoSource(p) if k == "video"', 'self.src[p] = self._video(p) if k == "video"')],
                             'new': 'a445f43b3410efcc8cad9c22dce83a0f103869e0eeabdc405d8025e7a3eff355'},
 'minicut/render/renderer.py': {'base': 'b23a5ef5f391076c3ef307317d8c708cbd39a603f87af5a4e03e8225f6bb8897',
                                'crlf': False,
                                'edits': [('self.pool = pool; self.lut_cache = {}\n',
                                           'self.pool = pool; self.lut_cache = {}; self.version = 0   # bumped on every project change (see '
                                           'clear_preview_cache)\n'),
                                          ('    def clear_preview_cache(self):\n        with self._cache_lock: self.preview_cache.clear()',
                                           '    def clear_preview_cache(self):\n'
                                           '        self.version += 1   # every edit calls this, so the version tells the preview when the project changed\n'
                                           '        with self._cache_lock: self.preview_cache.clear()'),
                                          ('    def render_cached(self, proj, t, q, fast=False):',
                                           '    def render_cached(self, proj, t, q, fast=False, ver=None):'),
                                          ('        try: sig = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '        except Exception: sig = id(proj)',
                                           '        sig = self.version if ver is None else ver   # no json.dumps of the whole project on every frame'),
                                          ('    def submit(self, proj, t, q, fast):\n'
                                           '        snap = _snapshot(proj)\n'
                                           '        with self.cv: self.job = (snap, t, q, fast); self.cv.notify()',
                                           '    def submit(self, proj, t, q, fast):\n'
                                           '        ver = self.r.version\n'
                                           '        # Copy the project only when it changed, not on every playback tick.\n'
                                           '        if getattr(self, "_snap_key", None) != (id(proj), ver):\n'
                                           '            self._snap = _snapshot(proj); self._snap_key = (id(proj), ver)\n'
                                           '        with self.cv: self.job = (self._snap, t, q, fast, ver); self.cv.notify()'),
                                          ('            snap, t, q, fast = job\n', '            snap, t, q, fast, ver = job\n'),
                                          ('fr = self.r.render_cached(snap, t, q, fast)', 'fr = self.r.render_cached(snap, t, q, fast, ver)')],
                                'new': 'fc232f1a426bc3bf8746fd157b67917e7d5c736b5de277b4c33c052cb00bb87a'},
 'minicut/shared/core.py': {'base': 'c55f3469398b5d8dc2ee5afcba91c6da3158f1e058fc842d59dbaad94d9bd6ad',
                            'crlf': False,
                            'edits': [('"encode_hw": "auto",', '"encode_hw": "auto", "proxy_preview": True,')],
                            'new': 'bc02961af54c514d2fcf2a8cc989b00d6631139dd2be8fbb51356ead6764bd19'},
 'minicut/shared/dialogs.py': {'base': 'b1ecf32bedbc0455150c4e1042716391e45859e712798a92e0ffa1b6997d958b',
                               'crlf': False,
                               'edits': [('        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl)\n',
                                          '        self.proxy_cb = QCheckBox("Smooth preview: use small background proxy copies (export always uses the '
                                          'original)"); self.proxy_cb.setChecked(bool(s["proxy_preview"]))\n'
                                          '        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl); '
                                          'form.addRow("", self.proxy_cb)\n'),
                                         ('s["encode_hw"] = self.enc.currentData()',
                                          's["encode_hw"] = self.enc.currentData(); s["proxy_preview"] = self.proxy_cb.isChecked()')],
                               'new': '2d78634ae1f78ac77a0a6784ec0bb56d2d8751580f4c57c2c23764c49bb74df8'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v3"
try: sys.stdout.reconfigure(errors="replace")
except Exception: pass


def norm_hash(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
def path_of(rel): return os.path.join(HERE, *rel.split("/"))
def read(rel):
    p = path_of(rel)
    return open(p, "rb").read() if os.path.exists(p) else None
def say(msg=""): print(msg, flush=True)


def edited_text(rel, raw):
    """Return the new bytes for a file, or raise ValueError if the expected text is not found exactly once."""
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
    for rel, info in EDITS.items():
        cur = read(rel)
        if cur is None:
            rows.append((rel, "missing", "file not found: install the effects patch first")); continue
        if norm_hash(cur) == info["new"]:
            rows.append((rel, "same", "already up to date")); continue
        if norm_hash(cur) != info["base"]:
            rows.append((rel, "edited", "differs from the version this patch was made for")); continue
        try:
            outputs[rel] = edited_text(rel, cur); rows.append((rel, "ok", "will be updated"))
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v3.py in the MiniCut folder (next to file.py) and run it again."); return 2
    if "--revert" in sys.argv:
        b = latest_backup()
        if not b: say("No backup found in _patch_backup/."); return 1
        revert(b); return 0
    rows, outputs = plan()
    say("MiniCut update: preview smoothness + GPU settings\n")
    for rel, st, note in rows: say("  %-36s %s" % (rel, note))
    say()
    if "--check" in sys.argv: return 0
    if all(st == "same" for _, st, _ in rows): say("Nothing to do: the update is already installed."); return 0
    bad = [rel for rel, st, _ in rows if st in ("edited", "missing")]
    if bad and "--force" not in sys.argv:
        say("STOPPED. These files are not in the state this patch expects:\n  " + "\n  ".join(bad) +
            "\nIf the previous update (apply_perf_gpu_patch_v2.py) is not installed yet, install it first.\n"
            "Otherwise your edits would be overwritten (they are backed up first). Run with --force to continue anyway.")
        return 3
    if bad and "--force" in sys.argv:
        # --force only skips the "edited" check for files that were edited; a missing file is still an error
        if any(st == "missing" for _, st, _ in rows): say("STOPPED: a required file is missing."); return 3
        for rel, st, _ in rows:
            if st == "edited" and rel in EDITS:
                try: outputs[rel] = edited_text(rel, read(rel))
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
    # check that every changed file now has exactly the expected content
    for rel, info in EDITS.items():
        if norm_hash(read(rel)) != info["new"]:
            say("ERROR: %s did not come out as expected, restoring the backup." % rel); revert(bdir); return 1
    ok, err = import_ok()
    if base_ok and not ok:
        say("The program no longer imports after the update, restoring the backup.\n" + err); revert(bdir); return 1
    for sub in ("minicut/render", "minicut/workspace", "minicut/shared"):
        shutil.rmtree(os.path.join(path_of(sub), "__pycache__"), ignore_errors=True)
    say("Done. %d file(s) updated, %d created.  Backup: %s" % (len(replaced), len(created), bdir))
    say("Start MiniCut as usual (Run_MiniCut.bat). Proxy previews are made in the background, so the first playback of a new clip can still be slower.")
    say("To undo:  python apply_perf_gpu_patch_v3.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

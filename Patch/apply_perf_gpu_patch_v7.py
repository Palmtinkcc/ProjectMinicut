#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 7: EFFECTS IN THE PREVIEW
==============================================
Install AFTER apply_perf_gpu_patch_v7.py.

Problem: after an effect was added, removed, switched off or its values changed, the preview could keep showing the
old picture. Patch 3 had made the render thread reuse a copy of the project, and the effect controls change the clip
in place, so the copy was out of date. Also the frame cache was keyed only by a version number.

Fix:
  * The render thread always takes a fresh copy of the project (it costs about 1 ms).
  * The frame cache is keyed by the project content too, so every change shows, whatever code made it.
  * While an effect slider moves, the preview is drawn small (low quality, fast) so it reacts at once; when the
    slider stops, the full-quality frame is drawn.

Files changed (originals are backed up first):
  minicut/render/renderer.py, minicut/render/preview.py, minicut/workspace/effects_panel.py

    python apply_perf_gpu_patch_v7.py            install the update
    python apply_perf_gpu_patch_v7.py --check    only show what would change
    python apply_perf_gpu_patch_v7.py --revert   undo the last install
    python apply_perf_gpu_patch_v7.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/render/effects.py': {'base': '078695788b29d9ef97418c680ff459f7d91c2e8bb1ba05aa8d855763fad0f414',
                               'crlf': False,
                               'edits': [('def fx_vignette(img, p, ctx):\n'
                                          '    a = p["amount"] / 100\n'
                                          '    if a <= 0: return img\n'
                                          '    h, w = img.shape[:2]; yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)\n'
                                          '    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 1.4142\n'
                                          '    start = 1.0 - p["softness"] / 100 * 0.95; v = np.clip((r - start) / max(1e-3, 1 - start), 0, 1) ** 2\n'
                                          '    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) * (1 - v[..., None] * a) + .5, 0, '
                                          '255).astype(np.uint8); return out\n',
                                          '_VIG = {}   # vignette factors per frame size and setting: they do not change from frame to frame\n'
                                          '\n'
                                          '\n'
                                          'def fx_vignette(img, p, ctx):\n'
                                          '    a = p["amount"] / 100\n'
                                          '    if a <= 0: return img\n'
                                          '    h, w = img.shape[:2]; key = (h, w, a, p["softness"]); k = _VIG.get(key)\n'
                                          '    if k is None:\n'
                                          '        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)\n'
                                          '        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 1.4142\n'
                                          '        start = 1.0 - p["softness"] / 100 * 0.95; v = np.clip((r - start) / max(1e-3, 1 - start), 0, 1) ** 2\n'
                                          '        k = (1 - v[..., None] * a).astype(np.float32); _VIG[key] = k\n'
                                          '        while len(_VIG) > 8: _VIG.pop(next(iter(_VIG)))\n'
                                          '    out = img.copy(); out[..., :3] = np.clip(img[..., :3].astype(np.float32) * k + .5, 0, 255).astype(np.uint8); '
                                          'return out\n')],
                               'new': 'd937eb419877945908c354434c12bf2ff13b2ec33b116853233ba9b1c8094431'},
 'minicut/render/preview.py': {'base': 'bc5d4a2299e0c39baf47d773cda281fc587b20ff8751fb30a739ea3d0468b68a',
                               'crlf': False,
                               'edits': [('    def request_render(self):\n',
                                          '    def preview_fast_for(self, sec):\n'
                                          '        """While an effect slider is moving, draw the preview small so the change shows at once."""\n'
                                          '        self._fast_until = time.monotonic() + sec\n'
                                          '    def request_render(self):\n'),
                                         ('        if w is None:\n            w = RenderWorker(self.renderer);',
                                          '        fast_now = time.monotonic() < getattr(self, "_fast_until", 0.0)\n'
                                          '        if fast_now: q = min(q, 0.25)\n'
                                          '        if w is None:\n'
                                          '            w = RenderWorker(self.renderer);'),
                                         ('w.submit(self.proj, self.t, q, self.settings["preview_interp"] == "fast")',
                                          'w.submit(self.proj, self.t, q, fast_now or self.settings["preview_interp"] == "fast")'),
                                         ('        self.request_render(); self.refresh_ui(); _follow_playhead(self)\n',
                                          '        if os.environ.get("MINICUT_PERF"):\n'
                                          '            pf = self.__dict__.setdefault("_perf", [now, 0])\n'
                                          '            pf[1] += 1\n'
                                          '            if now - pf[0] >= 1.0:\n'
                                          '                print("[perf] %d ticks/s, last render %.1f ms" % (pf[1], getattr(getattr(self, "_rworker", None), '
                                          '"last_ms", 0.0)))\n'
                                          '                pf[0] = now; pf[1] = 0\n'
                                          '        self.request_render(); self.refresh_ui(); _follow_playhead(self)\n')],
                               'new': '4ae3ab401fb000313d7d4925e5c1b46435b64431a60077af499d88f4d595b191'},
 'minicut/render/renderer.py': {'base': '2935e77e32c1835c9ccac4b014c2bdec96cdb9f13dee1b57d36afbcb25f8a232',
                                'crlf': False,
                                'edits': [('        ver = self.r.version\n'
                                           '        # Copy the project only when it changed, not on every playback tick.\n'
                                           '        if getattr(self, "_snap_key", None) != (id(proj), ver):\n'
                                           '            self._snap = _snapshot(proj); self._snap_key = (id(proj), ver)\n'
                                           '        with self.cv: self.job = (self._snap, t, q, fast, ver); self.cv.notify()',
                                           '        ver = self.r.version\n'
                                           '        # Always a fresh copy: effect and inspector edits change the clips in place, so a cached copy would be '
                                           'stale.\n'
                                           '        snap = _snapshot(proj)\n'
                                           '        with self.cv: self.job = (snap, t, q, fast, ver); self.cv.notify()'),
                                          ('        sig = self.version if ver is None else ver   # no json.dumps of the whole project on every frame',
                                           '        # The frame key is the project content (a fingerprint of everything that is drawn) plus the version.\n'
                                           '        try: fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '        except Exception: fp = id(proj)\n'
                                           '        sig = (fp, self.version if ver is None else ver)'),
                                          ('        return (np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8)',
                                           '        np.clip(canvas, 0, 1, out=canvas)\n        return cv2.convertScaleAbs(canvas, alpha=255.0, beta=0.5)')],
                                'new': '2350cd9c1099cd50fe85285102a37ab8b380afd6b56efc0fc74cf0207d752613'},
 'minicut/workspace/effects_panel.py': {'base': '74b35e006a459321e35269e7e5bc61acc31ff75e55efc65da53d2dae3953756a',
                                        'crlf': False,
                                        'edits': [('        e["p"][key] = val; self._ct.start(); self.app.request_render()',
                                                   '        e["p"][key] = val; self._ct.start(); self.app.preview_fast_for(0.2); self.app.request_render()'),
                                                  ('    def _commit(self):\n'
                                                   '        if self._before is not None: self.app.commit(self._before); self._before = None\n',
                                                   '    def _commit(self):\n'
                                                   '        if self._before is not None: self.app.commit(self._before); self._before = None\n'
                                                   '        self.app.request_render()   # the final, full-quality frame after the slider stops\n')],
                                        'new': '85e06aaf523c2cd160acb91b8e818893ede809a8a3abe0db6fc98687feb3c3dd'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v7"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v7.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v6.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v7.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

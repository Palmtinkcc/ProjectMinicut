#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 18: THE GUI THREAD NO LONGER COPIES THE PROJECT
====================================================================
Install AFTER apply_18_gui_thread_free.py.

Measured on a project with 20 compound clips and 60 clips: each preview tick copied the whole project on the GUI
thread (about 10 ms, at 60 ticks a second), so the window and the preview fought for the same thread.

  * The copy is now made by the render thread, and only when the project content changed (the frame key is made from
    the copy, so it always matches what was drawn).
  * The preview refresh is at most 30 times a second (the render itself is not faster than that on this machine).

Changed files: minicut/render/renderer.py, minicut/app.py

    python apply_18_gui_thread_free.py            install the update
    python apply_18_gui_thread_free.py --check    only show what would change
    python apply_18_gui_thread_free.py --revert   undo the last install
    python apply_18_gui_thread_free.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': 'b25e0740bd82c049221b160a049a49b1db774de56cbb30c20e3950e977ac3c04',
                    'crlf': False,
                    'edits': [("    def frame_ms(self): return max(8, int(round(1000 / max(1, int(self.settings['preview_fps'])))))\n",
                               '    def frame_ms(self):\n'
                               '        # The preview is redrawn at most 30 times a second: more than that only costs the GUI thread time.\n'
                               "        return max(33, int(round(1000 / max(1, int(self.settings['preview_fps'])))))\n")],
                    'new': 'ac8ac799199f993123e01ee2ae81b617c0429ab068dcf06695712ef9426a1610'},
 'minicut/render/renderer.py': {'base': '6e2fa445e7d529c0907dbeee48846000b0c8c0947431ed77293df10d121f229f',
                                'crlf': False,
                                'edits': [('    def submit(self, proj, t, q, fast):\n'
                                           '        ver = self.r.version\n'
                                           '        # Always a fresh copy: effect and inspector edits change the clips in place, so a cached copy would be '
                                           'stale.\n'
                                           '        snap = _snapshot(proj)\n'
                                           '        with self.cv: self.job = (snap, t, q, fast, ver); self.cv.notify()\n',
                                           '    def submit(self, proj, t, q, fast):\n'
                                           '        # Only hands the request over. The copy of the project is made by the render thread, never by the GUI '
                                           'thread.\n'
                                           '        ver = self.r.version\n'
                                           '        with self.cv: self.job = (proj, t, q, fast, ver); self.cv.notify()\n'
                                           '    def _snapshot_for(self, live):\n'
                                           '        """A copy of the live project for rendering. It is copied again only when the content changed, and the '
                                           'frame key\n'
                                           '        is computed from the copy, so the key always describes exactly what was drawn."""\n'
                                           '        for _ in range(4):\n'
                                           '            try:\n'
                                           '                fp = hash(json.dumps([live.clips, live.tracks, live.bg, live.w, live.h, getattr(live, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '                if fp == getattr(self, "_fp", None): return self._snap, self._fp\n'
                                           '                snap = _snapshot(live)\n'
                                           '                fp2 = hash(json.dumps([snap.clips, snap.tracks, snap.bg, snap.w, snap.h, getattr(snap, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '                self._snap, self._fp = snap, fp2\n'
                                           '                return snap, fp2\n'
                                           '            except RuntimeError:\n'
                                           '                continue                      # the GUI changed the project while it was read: read it again\n'
                                           '        return getattr(self, "_snap", live), getattr(self, "_fp", None)\n'),
                                          ('            snap, t, q, fast, ver = job\n',
                                           '            live, t, q, fast, ver = job\n            snap, fpv = self._snapshot_for(live)\n'),
                                          ('fr = self.r.render_cached(snap, t, q, fast, ver)', 'fr = self.r.render_cached(snap, t, q, fast, ver, fpv)'),
                                          ('    def render_cached(self, proj, t, q, fast=False, ver=None):',
                                           '    def render_cached(self, proj, t, q, fast=False, ver=None, fp=None):'),
                                          ('        try: fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '        except Exception: fp = id(proj)\n',
                                           '        if fp is None:\n'
                                           '            try: fp = hash(json.dumps([proj.clips, proj.tracks, proj.bg, proj.w, proj.h, getattr(proj, "graph", '
                                           'None)], sort_keys=True, default=str))\n'
                                           '            except Exception: fp = id(proj)\n')],
                                'new': '9b8fc5d7d863e29e867d8f5b2568037aac8013af23990a89b769b2b00b9d3aea'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "gui_thread_free"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_18_gui_thread_free.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_17_timeline_speed_ring.py) first."); return 3
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
    say("To undo:  python apply_18_gui_thread_free.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

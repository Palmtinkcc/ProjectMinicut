#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 9: MASK PREVIEW FOLLOWS THE PLAYHEAD, LAYOUT IS REMEMBERED
===============================================================================
Install AFTER apply_perf_gpu_patch_v9.py.

  * Mask tab: the picture behind the mask now changes with the playhead (it used to show only the first frame).
  * The window size and the position of every splitter in the editor are saved when you close MiniCut, and
    restored the next time you open a project.

Files changed (originals are backed up first):
  minicut/workspace/panels.py, minicut/workspace/actions.py, minicut/shared/core.py, minicut/app.py

    python apply_perf_gpu_patch_v9.py            install the update
    python apply_perf_gpu_patch_v9.py --check    only show what would change
    python apply_perf_gpu_patch_v9.py --revert   undo the last install
    python apply_perf_gpu_patch_v9.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': 'b27cb5921181181e991392affbb2b65e59628c9649dba213c4b2270756e36840',
                    'crlf': False,
                    'edits': [('    def closeEvent(self,e):\n',
                               '    def save_layout(self):\n'
                               '        """Remember the window size and the position of every splitter in the editor, so the layout is kept."""\n'
                               '        try:\n'
                               '            if not getattr(self, "editor", None) or not self.proj: return\n'
                               '            from PySide6.QtWidgets import QSplitter\n'
                               '            sps = self.editor.findChildren(QSplitter)\n'
                               '            if not sps: return\n'
                               '            self.settings["layout"] = {"geo": bytes(self.saveGeometry()).hex(), "splitters": [list(s.sizes()) for s in sps]}\n'
                               '            self.settings.save()\n'
                               '        except Exception as ex: print("layout save failed", ex)\n'
                               '    def restore_layout(self):\n'
                               '        lay = self.settings["layout"]\n'
                               '        if not lay: return\n'
                               '        try:\n'
                               '            if lay.get("geo") and not self.isVisible(): self.restoreGeometry(bytes.fromhex(lay["geo"]))\n'
                               '            if getattr(self, "editor", None) and self.proj:\n'
                               '                from PySide6.QtWidgets import QSplitter\n'
                               '                sps = self.editor.findChildren(QSplitter); saved = lay.get("splitters", [])\n'
                               '                if len(sps) == len(saved):\n'
                               '                    for s, sizes in zip(sps, saved):\n'
                               '                        if len(sizes) == s.count(): s.setSizes([int(x) for x in sizes])\n'
                               '        except Exception as ex: print("layout restore failed", ex)\n'
                               '    def closeEvent(self,e):\n'),
                              ('        e.accept()\n\n\ndef main():', '        self.save_layout()\n        e.accept()\n\n\ndef main():'),
                              ('win=MainWindow(); apply_ui(win); win.show();', 'win=MainWindow(); apply_ui(win); win.restore_layout(); win.show();')],
                    'new': '2bc21f3c670a2d3c61b9d4a6635486a23f2f4b4a7f1c5d3a87bcb58d0af0e4f6'},
 'minicut/shared/core.py': {'base': '34ec108286f37bcb9d4ce63dcdc6e548d2b2fb09112a37225f73e5d88fca43c2',
                            'crlf': False,
                            'edits': [('"proxy_height": 540, "proxy_quality": 23,', '"proxy_height": 540, "proxy_quality": 23, "layout": None,')],
                            'new': '82b88c5298aa5314a290864ea62e7671a66a4aed3f1653a9ec08ac32ae503e2f'},
 'minicut/workspace/actions.py': {'base': 'd586fe2a9a690cdf2571bdc5ad946b0b802a56ffe10fe74bfa646fecbdfcbb69',
                                  'crlf': False,
                                  'edits': [('    def _build_editor(self):\n',
                                             '    def _build_editor(self):\n'
                                             '        QTimer.singleShot(0, self.restore_layout)   # the splitters exist once the editor is built\n'),
                                            ('    def refresh_ui(self):\n        if not self.proj: return\n',
                                             '    def refresh_ui(self):\n'
                                             '        if not self.proj: return\n'
                                             '        if getattr(getattr(self, "inspector", None), "mask_panel", None) is not None: '
                                             'self.inspector.mask_panel.follow(self.t)\n')],
                                  'new': '8eaa9677cde06e2b91113039c41f1e1095e7b9c707eb314c973e6f70583207cc'},
 'minicut/workspace/panels.py': {'base': '189de3ae2ed13dd1774781cc92fef8b38a2069c1a79f720c2414f12f0e6248f2',
                                 'crlf': False,
                                 'edits': [('    def _grab_bg(self, c):\n'
                                            '        self.canvas.bg = None; pj = self.app.proj; self.src_size = (pj.w, pj.h) if pj else (16, 9)\n',
                                            '    def follow(self, t):\n'
                                            '        """The playhead moved: show the picture under the playhead in the mask editor (about every 50 ms at '
                                            'most)."""\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if not c or c["kind"] == "audio" or not self.isVisible(): return\n'
                                            '        last = getattr(self, "_bg_key", None)\n'
                                            '        if last is not None and last[0] == c["id"] and abs(last[1] - t) < 0.05: return\n'
                                            '        self._bg_key = (c["id"], t); self._grab_bg(c, t); self.canvas.update()\n'
                                            '    def _grab_bg(self, c, t=None):\n'
                                            '        t = self.app.t if t is None else t\n'
                                            '        self.canvas.bg = None; pj = self.app.proj; self.src_size = (pj.w, pj.h) if pj else (16, 9)\n'),
                                           ('                img = src.frame(c["inp"] if c["kind"] != "image" else 0, .25)',
                                            '                img = src.frame(max(0.0, c["inp"] + (t - c["start"])) if c["kind"] != "image" else 0, .25)')],
                                 'new': '65a5e7be4c9e71815ca008d50fa1d26f850bf5b89fe08bcc95c3edba577aacf9'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v9"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v9.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v8.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v9.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

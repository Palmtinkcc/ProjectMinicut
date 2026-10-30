#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 10: ZOOM IN THE CUSTOM MASK EDITOR
=======================================================
Install AFTER apply_perf_gpu_patch_v10.py.

In the Mask tab, with the shape set to Custom:
  * mouse wheel = zoom in / out, towards the mouse pointer (1x to 8x)
  * middle-button drag = pan
  * middle double-click = back to fit
Points are added, moved and removed as before; the zoom does not change the mask itself.

Files changed (originals are backed up first):
  minicut/workspace/panels.py

    python apply_perf_gpu_patch_v10.py            install the update
    python apply_perf_gpu_patch_v10.py --check    only show what would change
    python apply_perf_gpu_patch_v10.py --revert   undo the last install
    python apply_perf_gpu_patch_v10.py --force    install even if you edited this file yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/workspace/panels.py': {'base': '65a5e7be4c9e71815ca008d50fa1d26f850bf5b89fe08bcc95c3edba577aacf9',
                                 'crlf': False,
                                 'edits': [('super().__init__(); self.panel = panel; self.setMinimumHeight(170); self.bg = None; self.drag = None',
                                            'super().__init__(); self.panel = panel; self.setMinimumHeight(170); self.bg = None; self.drag = None\n'
                                            '        self.zoom = 1.0; self.pan = (0.0, 0.0)   # zoom and pan of the picture (wheel = zoom, middle drag = pan)'),
                                           ('        aw, ah = self.panel.src_size; W, H = max(10, self.width() - 16), max(10, self.height() - 16)\n'
                                            '        s = min(W / aw, H / ah); w, h = aw * s, ah * s\n'
                                            '        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)',
                                            '        aw, ah = self.panel.src_size; W, H = max(10, self.width() - 16), max(10, self.height() - 16)\n'
                                            '        s = min(W / aw, H / ah) * self.zoom; w, h = aw * s, ah * s\n'
                                            '        return QRectF((self.width() - w) / 2 + self.pan[0], (self.height() - h) / 2 + self.pan[1], w, h)'),
                                           ('        pos = e.position(); sh = self.panel.shape()\n'
                                            '        if sh == "None" or self.panel.app.sel_clip() is None: return\n',
                                            '        pos = e.position(); sh = self.panel.shape()\n'
                                            '        if e.button() == Qt.MiddleButton: self.drag = ("pan", pos.x(), pos.y()); return\n'
                                            '        if sh == "None" or self.panel.app.sel_clip() is None: return\n'),
                                           ('    def mouseMoveEvent(self, e):\n        if not self.drag: return\n',
                                            '    def mouseMoveEvent(self, e):\n'
                                            '        if not self.drag: return\n'
                                            '        if self.drag[0] == "pan":\n'
                                            '            px, py = self.pan; self.pan = (px + e.position().x() - self.drag[1], py + e.position().y() - '
                                            'self.drag[2])\n'
                                            '            self.drag = ("pan", e.position().x(), e.position().y()); self.update(); return\n'),
                                           ('    def wheelEvent(self, e):\n        e.accept()\n        if self.panel.shape() in ("None", "Custom"): return\n',
                                            '    def mouseDoubleClickEvent(self, e):\n'
                                            '        if e.button() == Qt.MiddleButton: self.zoom = 1.0; self.pan = (0.0, 0.0); self.update()\n'
                                            '    def wheelEvent(self, e):\n'
                                            '        e.accept()\n'
                                            '        if self.panel.shape() == "Custom":\n'
                                            '            # zoom towards the cursor: the point under the mouse stays where it is\n'
                                            '            p = e.position(); r0 = self.frame_rect(); nx = (p.x() - r0.left()) / r0.width(); ny = (p.y() - '
                                            'r0.top()) / r0.height()\n'
                                            '            self.zoom = min(8.0, max(1.0, self.zoom * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15)))\n'
                                            '            r1 = self.frame_rect(); self.pan = (self.pan[0] + p.x() - (r1.left() + nx * r1.width()), self.pan[1] '
                                            '+ p.y() - (r1.top() + ny * r1.height()))\n'
                                            '            if self.zoom <= 1.0: self.pan = (0.0, 0.0)\n'
                                            '            self.update(); return\n'
                                            '        if self.panel.shape() in ("None", "Custom"): return\n')],
                                 'new': '4413ed33633e39df1566d61b619deec9263d2a53d04ecf744bcfb6093a8114bd'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v10"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v10.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v9.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v10.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

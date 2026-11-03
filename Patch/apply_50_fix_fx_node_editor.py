#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut Patch 50 - Fix: the FX node editor (effect editor) did not open

* FIXED: opening the FX node editor failed with
      AttributeError: 'FxNodeItem' object has no attribute '_build_params_widget'
  FxNodeItem.__init__ called a method that does not exist. Parameters are edited in the panel on the right
  (FxParamPanel), so the call was removed. Nothing else in the node item changed.
* FIXED: clicking a node in the editor would then fail in FxParamPanel._rebuild (the old loop took two items per
  pass and called .widget() on rows/spacers, which is None). The panel now clears its layout correctly.

NOT changed on purpose: nothing else in the editor. Known and left alone: middle-mouse pan in the node view uses
QMouseEvent, which is not imported in this file (it will raise NameError on a middle click).

Files changed: minicut/workspace/fx_node_editor.py
  python Patch/apply_50_fix_fx_node_editor.py --check      (look only, change nothing)
  python Patch/apply_50_fix_fx_node_editor.py              (install)
  python Patch/apply_50_fix_fx_node_editor.py --revert     (put the file back from the backup)
Close MiniCut before installing. The MiniCut Launcher can do all of this for you.
"""
import base64, datetime, hashlib, json, os, py_compile, shutil, sys, zlib
PATCH_NAME = "patch50_fix_fx_node_editor"
REPLACE = {'minicut/workspace/fx_node_editor.py': {'base': '82cc8daa75690316919163ce485dbab88a7cfa571f1bae8899329b9fef97e4c7', 'new': '3b77e347282b2283fb07afb160249be8665645fcf8fe39840adbb146898152a6'}}
NEW_FILES = {}
PAYLOAD = {'minicut/workspace/fx_node_editor.py': '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'}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE if os.path.isfile(os.path.join(HERE, "minicut", "app.py")) else (os.path.dirname(HERE) if os.path.isfile(os.path.join(os.path.dirname(HERE), "minicut", "app.py")) else HERE)
BACKUP_ROOT = os.path.join(ROOT, "_patch_backup")


def norm_hash(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
def path_of(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    try:
        with open(path_of(rel), "rb") as f: return f.read()
    except OSError: return None
def new_bytes(rel):
    return zlib.decompress(base64.b64decode(PAYLOAD[rel]))
def latest_backup():
    found = []
    if os.path.isdir(BACKUP_ROOT):
        for d in os.listdir(BACKUP_ROOT):
            mf = os.path.join(BACKUP_ROOT, d, "MANIFEST.json")
            if os.path.isfile(mf):
                try:
                    with open(mf, encoding="utf-8") as f:
                        if json.load(f).get("patch") == PATCH_NAME: found.append(d)
                except Exception: pass
    return os.path.join(BACKUP_ROOT, sorted(found)[-1]) if found else None


def revert():
    bdir = latest_backup()
    if not bdir: print("No backup of this update was found."); return 1
    with open(os.path.join(bdir, "MANIFEST.json"), encoding="utf-8") as f: m = json.load(f)
    for rel in m.get("replaced", []): shutil.copy2(os.path.join(bdir, *rel.split("/")), path_of(rel))
    for rel in m.get("created", []):
        try: os.remove(path_of(rel))
        except OSError: pass
    os.replace(os.path.join(bdir, "MANIFEST.json"), os.path.join(bdir, "MANIFEST.undone.json"))
    print("Reverted from backup:", bdir); return 0


def main():
    if not os.path.isfile(os.path.join(ROOT, "minicut", "app.py")):
        print("ERROR: the MiniCut folder was not found. Put this file in MiniCut/Patch/ (or next to the minicut folder)."); return 2
    if "--revert" in sys.argv: return revert()
    todo_replace, todo_new, already = [], [], 0
    for rel, h in REPLACE.items():
        cur = read(rel)
        if cur is None: print("STOPPED: missing file", rel, "- no files were changed."); return 3
        c = norm_hash(cur)
        if c == h["new"]: already += 1
        elif c == h["base"]: todo_replace.append(rel)
        else:
            print("STOPPED:", rel, "is not the version this update expects (it was changed by hand or by another update).")
            print("No files were changed. This protects your own edits."); return 3
    for rel, text in NEW_FILES.items():
        cur = read(rel)
        if cur is None: todo_new.append(rel)
        elif norm_hash(cur) == norm_hash(text.encode("utf-8")): already += 1
        else: print("STOPPED:", rel, "already exists with other content. No files were changed."); return 3
    if not todo_replace and not todo_new: print("This update is already installed."); return 0
    if "--check" in sys.argv:
        print("Check passed. Would change:", ", ".join(todo_replace + todo_new)); return 0
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); bdir = os.path.join(BACKUP_ROOT, stamp); k = 1
    while os.path.exists(bdir): k += 1; bdir = os.path.join(BACKUP_ROOT, "%s_%d" % (stamp, k))      # two installs in one second
    os.makedirs(bdir, exist_ok=False)
    for rel in todo_replace:
        dst = os.path.join(bdir, *rel.split("/")); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(path_of(rel), dst)
    with open(os.path.join(bdir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump({"patch": PATCH_NAME, "created": todo_new, "replaced": todo_replace}, f, indent=2)
    try:
        for rel in todo_replace:
            cur = read(rel); data = new_bytes(rel).replace(b"\r\n", b"\n")
            if b"\r\n" in cur: data = data.replace(b"\n", b"\r\n")            # keep the file's own line endings
            with open(path_of(rel), "wb") as f: f.write(data)
            if norm_hash(read(rel)) != REPLACE[rel]["new"]: raise RuntimeError("hash mismatch after writing " + rel)
        for rel in todo_new:
            os.makedirs(os.path.dirname(path_of(rel)), exist_ok=True)
            with open(path_of(rel), "wb") as f: f.write(NEW_FILES[rel].encode("utf-8"))
        for rel in todo_replace + todo_new:
            if rel.endswith(".py"): py_compile.compile(path_of(rel), doraise=True)
    except Exception as ex:
        for rel in todo_replace: shutil.copy2(os.path.join(bdir, *rel.split("/")), path_of(rel))
        for rel in todo_new:
            try: os.remove(path_of(rel))
            except OSError: pass
        print("ERROR: the update failed and every file was put back:", repr(ex)); return 1
    print("Installed Patch 50. Changed:", ", ".join(todo_replace + todo_new)); print("Backup:", bdir); return 0


if __name__ == "__main__":
    try: code = main()
    except Exception as ex: print("Unexpected error:", repr(ex)); code = 1
    sys.exit(code)

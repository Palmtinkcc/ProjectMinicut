#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut Patch 35 — Avoid repeated full-project serialization during preview requests.

Only changes minicut/render/renderer.py. It uses the renderer's existing version counter as a fast
unchanged-project signal, while retaining the content fingerprint on edits. GPU decoding is untouched.

Run from MiniCut root or Patch folder:
  python Patch/apply_35_cpu_spike_reduction.py --check
  python Patch/apply_35_cpu_spike_reduction.py
  python Patch/apply_35_cpu_spike_reduction.py --revert
"""
import datetime, hashlib, json, os, py_compile, shutil, sys
PATCH_NAME = "patch35_cpu_spike_reduction"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(SCRIPT_DIR, "minicut", "app.py")):
    ROOT = SCRIPT_DIR
elif os.path.isfile(os.path.join(os.path.dirname(SCRIPT_DIR), "minicut", "app.py")):
    ROOT = os.path.dirname(SCRIPT_DIR)
else:
    ROOT = SCRIPT_DIR
BACKUP_ROOT = os.path.join(ROOT, "_patch_backup")
REL = "minicut/render/renderer.py"
BASE_HASH = "548cfce1ff42dcd4a28d6ae2236d00f6ed3570985bd5893b51efca7e6cb79a98"
NEW_HASH = "22c37fa23277d827c14cd2a815fca4ffc7a51ddea9702742661ff7f4e09e4568"
OLD = '    def _snapshot_for(self, live):\n        """A copy of the live project for rendering. It is copied again only when the content changed, and the frame key\n        is computed from the copy, so the key always describes exactly what was drawn."""\n        for _ in range(4):\n            try:\n                fp = hash(json.dumps([live.clips, live.tracks, live.bg, live.w, live.h, getattr(live, "graph", None)], sort_keys=True, default=str))\n                if fp == getattr(self, "_fp", None): return self._snap, self._fp\n                snap = _snapshot(live)\n                fp2 = hash(json.dumps([snap.clips, snap.tracks, snap.bg, snap.w, snap.h, getattr(snap, "graph", None)], sort_keys=True, default=str))\n                self._snap, self._fp = snap, fp2\n                return snap, fp2\n            except RuntimeError:\n                continue                      # the GUI changed the project while it was read: read it again\n        return getattr(self, "_snap", live), getattr(self, "_fp", None)\n'
NEW = '    def _snapshot_for(self, live):\n        """Reuse the render snapshot while the project\'s edit-version is unchanged.\n\n        Previously every preview request JSON-serialized the entire project (often twice) just to\n        discover that nothing changed. Timeline scrubbing can submit many requests per second, so\n        this work caused avoidable CPU spikes. Project edits call clear_preview_cache(), which\n        increments Renderer.version; use that existing dirty signal as the fast path. When the\n        version changes, retain the content fingerprint check as a safety net and copy only if needed.\n        """\n        version = self.r.version\n        if getattr(self, "_snap_version", None) == version and hasattr(self, "_snap"):\n            return self._snap, self._fp\n        for _ in range(4):\n            try:\n                version = self.r.version\n                fp = hash(json.dumps([live.clips, live.tracks, live.bg, live.w, live.h, getattr(live, "graph", None)], sort_keys=True, default=str))\n                if fp == getattr(self, "_fp", None) and hasattr(self, "_snap"):\n                    self._snap_version = version\n                    return self._snap, self._fp\n                snap = _snapshot(live)\n                fp2 = hash(json.dumps([snap.clips, snap.tracks, snap.bg, snap.w, snap.h, getattr(snap, "graph", None)], sort_keys=True, default=str))\n                # If an edit landed while the snapshot was being prepared, retry instead of marking\n                # a potentially mixed snapshot as current.\n                if self.r.version != version:\n                    continue\n                self._snap, self._fp, self._snap_version = snap, fp2, version\n                return snap, fp2\n            except RuntimeError:\n                continue                      # the GUI changed the project while it was read: read it again\n        return getattr(self, "_snap", live), getattr(self, "_fp", None)\n'
def norm_hash(data): return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
def target(): return os.path.join(ROOT, *REL.split("/"))
def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    found=[]
    for d in os.listdir(BACKUP_ROOT):
        mf=os.path.join(BACKUP_ROOT,d,"MANIFEST.json")
        if os.path.isfile(mf):
            try:
                with open(mf,encoding="utf-8") as f: m=json.load(f)
                if m.get("patch")==PATCH_NAME: found.append(d)
            except Exception: pass
    return os.path.join(BACKUP_ROOT, sorted(found)[-1]) if found else None
def main():
    p=target()
    if not os.path.isfile(p) or not os.path.isfile(os.path.join(ROOT,"minicut","app.py")):
        print("ERROR: MiniCut root not found. Place this script in MiniCut/Patch/ or run beside minicut/app.py."); return 2
    if "--revert" in sys.argv:
        bdir=latest_backup()
        if not bdir: print("No Patch 35 backup found."); return 1
        with open(os.path.join(bdir,"MANIFEST.json"),encoding="utf-8") as f: m=json.load(f)
        for rel in m.get("replaced",[]): shutil.copy2(os.path.join(bdir,*rel.split("/")),os.path.join(ROOT,*rel.split("/")))
        print("Patch 35 reverted. Backup restored:",bdir); return 0
    with open(p,"rb") as f: current=f.read()
    h=norm_hash(current)
    if h==NEW_HASH: print("Patch 35 is already installed."); return 0
    if h!=BASE_HASH:
        print("STOPPED: renderer.py does not match the expected Patch 31/32/33 base.")
        print("No files were changed. This is intentional protection against overwriting other edits."); return 3
    src=current.decode("utf-8")
    if src.count(OLD)!=1: print("STOPPED: expected source block not found exactly once; no files changed."); return 3
    output=src.replace(OLD,NEW,1).encode("utf-8")
    if norm_hash(output)!=NEW_HASH: print("STOPPED: generated hash mismatch; no files changed."); return 3
    if "--check" in sys.argv:
        print("Patch 35 check passed: minicut/render/renderer.py will change; GPU decoder untouched."); return 0
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir=os.path.join(BACKUP_ROOT,stamp); os.makedirs(bdir,exist_ok=False)
    backup=os.path.join(bdir,*REL.split("/")); os.makedirs(os.path.dirname(backup),exist_ok=True); shutil.copy2(p,backup)
    with open(os.path.join(bdir,"MANIFEST.json"),"w",encoding="utf-8") as f: json.dump({"patch":PATCH_NAME,"created":[],"replaced":[REL]},f,indent=2)
    try:
        with open(p,"wb") as f: f.write(output)
        py_compile.compile(p,doraise=True)
        with open(p,"rb") as f: written=f.read()
        if norm_hash(written)!=NEW_HASH: raise RuntimeError("post-write hash mismatch")
    except Exception as ex:
        shutil.copy2(backup,p); print("ERROR: validation failed; original restored:",repr(ex)); return 1
    print("Patch 35 installed. Changed only:",REL)
    print("Backup:",bdir)
    print("Undo with: python Patch/apply_35_cpu_spike_reduction.py --revert")
    print("Expected benefit: avoid full-project JSON fingerprinting on every preview request when no edit occurred.")
    return 0
if __name__=="__main__":
    try: code=main()
    except Exception as ex: print("Unexpected error:",repr(ex)); code=1
    sys.exit(code)

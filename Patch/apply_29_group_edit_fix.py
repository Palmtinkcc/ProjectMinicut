#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut Patch 29: SEVERAL CLIPS SELECTED - MOVE / TRIM FIX   (needs patch 28)
=============================================================================
Box-select (or Ctrl+click) several clips, then:
 * moving them: the dragged clip no longer snaps to the clips that move with it (that made it jump and "lock"
   in steps); the edges of every selected clip snap to the clips that are not selected
 * when they are dropped, a selected clip that would lie on top of a clip that was not selected is moved to a free
   track (like a single clip is), so clips never overlap
 * dragging the left or right edge of one of them trims / stretches ALL selected clips by the same amount (as far
   as the most limited clip allows: end of its file, the clip next to it ...). Before, the others were pushed
   sideways by a left trim (out of sync) and a right trim changed only one clip.
 * clips on a locked track are not touched
Roll edit (nothing selected, drag the border of two touching clips) and single-clip trimming are unchanged.

    python apply_29_group_edit_fix.py            install
    python apply_29_group_edit_fix.py --check    preview only
    python apply_29_group_edit_fix.py --revert   undo last install
    python apply_29_group_edit_fix.py --force    install over local edits
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

EDITS = {'minicut/workspace/timeline.py': {'base': 'ea593225758fa1f290745022fc31827d7ad014ecde2817b1579027c558c83725', 'new': '8a95e3526cf9716ff5ab023fa57a3f4974e8712526141132a3e15c3ac5e30e22', 'edits': [('    def snap_points(self, exclude):\n        pts = [0.0, self.app.t]\n        for c in self.app.proj.clips:\n            if c["id"] != exclude: pts += [c["start"], c["start"] + c["dur"]]\n', '    def snap_points(self, exclude):\n        ex = {exclude} | set(getattr(self.app, "multi", set()) or ())      # the selected clips move with the dragged one: they are not snap targets\n        pts = [0.0, self.app.t]\n        for c in self.app.proj.clips:\n            if c["id"] not in ex: pts += [c["start"], c["start"] + c["dur"]]\n'), ('            s1, l1 = self.snap(ns, pts); s2, l2 = self.snap(ns + c["dur"], pts)\n            if l1 is not None and (l2 is None or abs(s1 - ns) <= abs(s2 - ns - c["dur"])): ns = s1; self.snap_line = l1\n            elif l2 is not None: ns = s2 - c["dur"]; self.snap_line = l2\n            else: self.snap_line = None\n', '            edges = [0.0, c["dur"]] + [xe for o, s0 in d.get("grp", ()) for xe in (s0 - d["start"], s0 - d["start"] + o["dur"])]      # edges of every clip that moves together\n            best = None\n            for ed in edges:\n                sn, ln = self.snap(ns + ed, pts)\n                if ln is not None and (best is None or abs(sn - ns - ed) < best[0]): best = (abs(sn - ns - ed), sn - ed, ln)\n            if best: ns = best[1]; self.snap_line = best[2]\n            else: self.snap_line = None\n'), ('        if d and d.get("mode") in ("move", "trim_l"):\n            c = d["clip"]\n            if c["id"] not in app.multi: app.multi = _group_ids(app, c)\n            d["grp"] = [(o, o["start"]) for o in app.proj.clips if o["id"] in app.multi and o["id"] != c["id"]]\n', '        if d and d.get("mode") in ("move", "trim_l", "trim_r"):\n            c = d["clip"]\n            if c["id"] not in app.multi: app.multi = _group_ids(app, c)\n            others = [o for o in app.proj.clips if o["id"] in app.multi and o["id"] != c["id"] and not (app.proj.track(o["track"]) or {}).get("locked")]\n            d["grp"] = [(o, o["start"]) for o in others] if d["mode"] == "move" else []\n            if d["mode"] != "move" and others: d["gtrim"] = [self._trim_orig(o) for o in others]; d["roll"] = False      # several clips: no roll edit, they are all trimmed\n'), ('    def mouseMoveEvent(self, e):\n        self._move_core(e)\n        d = self.drag\n        if d and d.get("mode") in ("move", "trim_l") and d.get("grp"):\n            c = d["clip"]; delta = c["start"] - d["start"]; mn = min(s for _, s in d["grp"])\n            if mn + delta < 0: delta = -mn; c["start"] = d["start"] + delta\n            for o, s in d["grp"]: o["start"] = s + delta\n            self.app.request_render(); self.update()\n', '    def mouseMoveEvent(self, e):\n        self._move_core(e)\n        d = self.drag\n        if not d: return\n        if d.get("mode") == "move" and d.get("grp"):\n            c = d["clip"]; delta = c["start"] - d["start"]; mn = min(s for _, s in d["grp"])\n            if mn + delta < 0: delta = -mn; c["start"] = d["start"] + delta\n            for o, s in d["grp"]: o["start"] = s + delta\n            self.app.request_render(); self.update()\n        elif d.get("mode") in ("trim_l", "trim_r") and d.get("gtrim"): self._group_trim(d)\n    def _trim_orig(self, o):\n        """Everything needed to trim clip o from its state at the mouse press (and the clips it must not run into)."""\n        clips = self.app.proj.clips\n        def snap_of(nb): return None if nb is None else {"start": nb["start"], "dur": nb["dur"], "inp": nb["inp"], "src_dur": nb.get("src_dur", 0), "kind": nb["kind"], "props": nb["props"]}\n        return {"clip": o, "start": o["start"], "dur": o["dur"], "inp": o["inp"], "keys": copy.deepcopy(o["props"]), "src_dur": o.get("src_dur", 0), "kind": o["kind"],\n                "prev": snap_of(neighbor_before(clips, o["track"], o["id"], o["start"])), "next": snap_of(neighbor_after(clips, o["track"], o["id"], o["start"] + o["dur"]))}\n    @staticmethod\n    def _apply_trim(clip, o, left, delta):\n        """Trim `clip` (state at the press: o) by delta: the left edge moves by delta, or the right edge does."""\n        if left:\n            ns = o["start"] + delta; clip["start"] = ns; clip["dur"] = o["start"] + o["dur"] - ns\n            if clip["kind"] not in ("image", "text"): clip["inp"] = max(0.0, o["inp"] + src_delta({"kind": clip["kind"], "inp": o["inp"], "props": o["keys"]}, delta))\n            for name, pr in clip["props"].items():\n                for kf, k0 in zip(pr["k"], o["keys"][name]["k"]): kf["t"] = k0["t"] - delta\n        else: clip["dur"] = o["dur"] + delta\n    def _group_trim(self, d):\n        """Several clips selected: dragging an edge trims / stretches every one of them by the same amount, as far as\n        the most limited of them allows (end of its file, the clip next to it ...)."""\n        c = d["clip"]; fps = self.app.proj.fps; left = d["mode"] == "trim_l"\n        delta = (c["start"] - d["start"]) if left else (c["start"] + c["dur"] - d["start"] - d["dur"]); lo, hi = -1e9, 1e9\n        for g in d["gtrim"]:\n            o0 = {"start": g["start"], "dur": g["dur"], "inp": g["inp"], "src_dur": g["src_dur"], "kind": g["kind"], "props": g["keys"]}\n            if left: a, b = trim_l_bounds(o0, g["prev"], fps, False); lo, hi = max(lo, a - g["start"]), min(hi, b - g["start"])\n            else: a, b = trim_r_bounds(o0, g["next"], fps, False); e0 = g["start"] + g["dur"]; lo, hi = max(lo, a - e0), min(hi, b - e0)\n        delta = max(lo, min(hi, delta))\n        self._apply_trim(c, d, left, delta)\n        for g in d["gtrim"]: self._apply_trim(g["clip"], g, left, delta)\n        self.app.request_render(); self.update()\n'), ('                elif not app.track_free(c["track"], c["start"], c["start"] + c["dur"], c["id"]):\n                    idx = app.proj.track_index(c["track"])\n                    c["track"] = app.proj.add_track(want, idx if want == "video" else idx + 1)["id"]\n', '                elif not app.track_free(c["track"], c["start"], c["start"] + c["dur"], c["id"]):\n                    idx = app.proj.track_index(c["track"])\n                    c["track"] = app.proj.add_track(want, idx if want == "video" else idx + 1)["id"]\n                for o, _s in d.get("grp", ()):          # the others of the selection must not cover clips that were not selected\n                    if not app.track_free(o["track"], o["start"], o["start"] + o["dur"], o["id"]): app.place_free(o)\n')], 'crlf': False}}

REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "group_edit_fix"
try: sys.stdout.reconfigure(errors="replace")
except Exception: pass


def norm_hash(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
def path_of(rel): return os.path.join(HERE, *rel.split("/"))
def read(rel):
    p = path_of(rel)
    return open(p, "rb").read() if os.path.exists(p) else None
def say(msg=""): print(msg, flush=True)


def edited_text(rel, raw):
    info = EDITS[rel]
    text = raw.decode("utf-8"); crlf = "\r\n" in text; t = text.replace("\r\n", "\n")
    for old, new in info["edits"]:
        n = t.count(old)
        if n != 1: raise ValueError("%s: expected the patch text exactly once, found %d times" % (rel, n))
        t = t.replace(old, new, 1)
    return (t.replace("\n", "\r\n") if crlf else t).encode("utf-8")


def plan():
    rows, outputs = [], {}
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        cur = read(rel)
        if cur is None:
            rows.append((rel, "missing", "file not found")); continue
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
        else: rows.append((rel, "edited", "already exists and differs"))
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
        say("ERROR: minicut/app.py not found.\nPut this file in the MiniCut folder (next to file.py) and run again."); return 2
    if "--revert" in sys.argv:
        b = latest_backup()
        if not b: say("No backup found in _patch_backup/."); return 1
        revert(b); return 0
    rows, outputs = plan()
    say("MiniCut Patch 29: group edit fix\n")
    for rel, st, note in rows: say("  %-44s %s" % (rel, note))
    say()
    if "--check" in sys.argv: return 0
    if all(st == "same" for _, st, _ in rows): say("Nothing to do: already installed."); return 0
    if any(st == "missing" for _, st, _ in rows):
        say("STOPPED. File missing:\n  " + "\n  ".join(rel for rel, st, _ in rows if st == "missing")); return 3
    bad = [rel for rel, st, _ in rows if st == "edited"]
    if bad and "--force" not in sys.argv:
        say("STOPPED. Files differ from expected:\n  " + "\n  ".join(bad) +
            "\nRun with --force to continue anyway (files are backed up first).")
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
    json.dump({"patch": PATCH_NAME, "created": created, "replaced": replaced},
              open(os.path.join(bdir, "MANIFEST.json"), "w", encoding="utf-8"), indent=1)
    try:
        for rel, data in outputs.items():
            p = path_of(rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f: f.write(data)
            if rel.endswith(".py"): py_compile.compile(p, doraise=True)
    except Exception as ex:
        say("ERROR writing files: %s\nRestoring backup ..." % ex); revert(bdir); return 1
    for rel, info in list(EDITS.items()) + list(REPLACE.items()):
        if norm_hash(read(rel)) != info["new"]:
            say("ERROR: %s hash mismatch after write, restoring backup." % rel); revert(bdir); return 1
    ok, err = import_ok()
    if base_ok and not ok:
        say("Import failed after update, restoring backup.\n" + err); revert(bdir); return 1
    for sub in ("minicut/render", "minicut/workspace", "minicut/shared"):
        shutil.rmtree(os.path.join(path_of(sub), "__pycache__"), ignore_errors=True)
    say("Done. %d file(s) updated, %d created.  Backup: %s" % (len(replaced), len(created), bdir))
    say("Start MiniCut as usual.")
    say("To undo:  python apply_29_group_edit_fix.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

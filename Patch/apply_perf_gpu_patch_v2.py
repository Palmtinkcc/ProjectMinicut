#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 2: PREVIEW PLAYBACK FIX
============================================
Install this AFTER the preview / GPU update (apply_perf_gpu_patch.py).

Fixes the problems seen after the first GPU update:
  * Image got blurrier than the CPU-only version: the adaptive preview and the "halve while playing"
    setting were multiplied together (down to 1/8 of the chosen quality). They now replace each other,
    and the adaptive scale never goes below half of the chosen quality.
  * Playback stalled after a clip was reset / restarted: the first slow frames after a seek are no longer
    counted, and the render time is smoothed, so one slow frame does not lower the quality for a long time.

Only minicut/render/preview.py is changed (the original is backed up first).

    python apply_perf_gpu_patch_v2.py            install the update
    python apply_perf_gpu_patch_v2.py --check    only show what would change
    python apply_perf_gpu_patch_v2.py --revert   undo the last install
    python apply_perf_gpu_patch_v2.py --force    install even if you edited the file yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

EDITS = {'minicut/render/preview.py': {'base': '5924858e6273140873d5038d58e64327ffa27b36cb141abe0c9c364f35788e01',
                               'crlf': False,
                               'edits': [('        q = self.settings["preview_quality"]\n'
                                          '        if self.playing and self.settings["play_reduce"]: q *= .5\n'
                                          '        w = getattr(self, "_rworker", None)\n'
                                          '        # Adaptive preview: while playing, draw smaller if one frame takes longer than one frame interval.\n'
                                          '        if self.playing and self.settings["adaptive_preview"] and w is not None:\n'
                                          '            budget = self.frame_ms(); ms = getattr(w, "last_ms", 0.0); a = getattr(self, "_adapt", 1.0)\n'
                                          '            if ms > budget * 1.1: a = max(0.25, a * 0.85)\n'
                                          '            elif ms < budget * 0.6: a = min(1.0, a * 1.1)\n'
                                          '            self._adapt = a; q *= a\n'
                                          '        else: self._adapt = 1.0\n',
                                          '        q = self.settings["preview_quality"]\n'
                                          '        w = getattr(self, "_rworker", None)\n'
                                          '        # Adaptive preview replaces the fixed "half while playing" step, so the two never stack into a very blurry '
                                          'image.\n'
                                          '        adaptive = self.playing and self.settings["adaptive_preview"] and w is not None\n'
                                          '        if self.playing and self.settings["play_reduce"] and not adaptive: q *= .5\n'
                                          '        if adaptive: q *= self._adaptive_scale(w)\n'
                                          '        else: self._adapt = 1.0; self._ema = None\n'),
                                         ('        self._last_tick = time.monotonic()\n        self.request_render(); self.refresh_ui()\n',
                                          '        self._adapt_hold = time.monotonic() + 0.8; self._ema = None   # let the first frames after a seek settle\n'
                                          '        self._last_tick = time.monotonic()\n'
                                          '        self.request_render(); self.refresh_ui()\n'),
                                         ('    def request_render(self):\n',
                                          '    def _adaptive_scale(self, w):\n'
                                          '        """Scale 0.5..1.0 for the preview while playing. Uses a smoothed render time, ignores the first frames\n'
                                          '        after a seek (they are slow because the video is opened / decoded from a keyframe), and never goes below '
                                          'half."""\n'
                                          '        budget = self.frame_ms(); now = time.monotonic()\n'
                                          '        if now < getattr(self, "_adapt_hold", 0.0): return getattr(self, "_adapt", 1.0)\n'
                                          '        ms = getattr(w, "last_ms", 0.0); ema = getattr(self, "_ema", None)\n'
                                          '        ema = ms if ema is None else ema * 0.7 + ms * 0.3; self._ema = ema\n'
                                          '        a = getattr(self, "_adapt", 1.0)\n'
                                          '        if ema > budget * 1.15: a = max(0.5, a - 0.1)\n'
                                          '        elif ema < budget * 0.6: a = min(1.0, a + 0.05)\n'
                                          '        self._adapt = a; return a\n'
                                          '    def request_render(self):\n')],
                               'new': '1976a6f31a9d852974c599f2ba8bb1c15840aa7ce5c5bc10e3b67efaf60df7a1'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v2"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v2.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nIf the previous update (apply_perf_gpu_patch.py) is not installed yet, install it first.\n"
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
    say("Start MiniCut as usual (Run_MiniCut.bat).")
    say("To undo:  python apply_perf_gpu_patch_v2.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

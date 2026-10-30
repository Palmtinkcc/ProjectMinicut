#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut Patch 28: AUTO SAVE   (needs patch 27 to be installed first)
====================================================================
The open project is saved over its own file (like Ctrl+S) every N minutes, only when something changed.
Settings > General > Auto save: on / off (default on) and the number of minutes (default 1).
A project that was never saved is saved in the Project folder (Settings) under its name, like Ctrl+S does.
Nothing is shown when it works; a short message appears if it fails.

    python apply_28_autosave.py            install
    python apply_28_autosave.py --check    preview only
    python apply_28_autosave.py --revert   undo last install
    python apply_28_autosave.py --force    install over local edits
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

EDITS = {'minicut/shared/core.py': {'base': '970b2b212825bc7e3ffbdd248de2eb442db4978ddb356d7b811427fbd85b9149', 'new': '174971044da1a2c372091e077763a7d526b01e779e18c487203ac8fb94af83d2', 'edits': [('"waveform_gain": 3.0, "export_parallel": 2, "audio_input": "",', '"waveform_gain": 3.0, "export_parallel": 2, "audio_input": "", "autosave": True, "autosave_min": 1,')], 'crlf': False}, 'minicut/app.py': {'base': '191dcd6d29fa4bd2dabbd67fb3ef40b436581d244b8380956d2042d2bde754c5', 'new': 'f047b1193ae9590c7cbe5cc57b85d012a919157b5c7ad9dc14c8628a5bb5e9b4', 'edits': [('from .workspace.actions import *\n', 'from .workspace.actions import *\nfrom .project.autosave import *\n'), ('class MainWindow(MediaPreviewMixin, RecordMixin,', 'class MainWindow(AutosaveMixin, MediaPreviewMixin, RecordMixin,'), ('self.apply_shortcuts(); self.show_home()\n', 'self.apply_shortcuts(); self.show_home(); self.autosave_apply()\n'), ('            self.apply_preview_fps(); apply_perf(self.settings, self.renderer)\n', '            self.apply_preview_fps(); apply_perf(self.settings, self.renderer); self.autosave_apply()\n')], 'crlf': False}, 'minicut/project/create.py': {'base': 'd4dc043a26945ba2b13ad80fb23495e0cbfe1f75e84339db09c95a45f3d1eddd', 'new': '0c4ba674e7c0e9a766f2bb692ad6293ddf77998d1bc8f5630d04b115f62bb478', 'edits': [("            self.proj.path=path; self.settings.save(); self.refresh_recent(); self.toast.show_msg('Project saved')\n        except Exception as ex:QMessageBox.warning(self,'Save failed',str(ex))\n", "            self.proj.path=path; self.settings.save(); self.refresh_recent(); self._saved_sig=self._proj_sig()\n            if not getattr(self,'_quiet_save',False): self.toast.show_msg('Project saved')\n        except Exception as ex:\n            if getattr(self,'_quiet_save',False): self.toast.show_msg('Auto save failed: '+str(ex))\n            else: QMessageBox.warning(self,'Save failed',str(ex))\n")], 'crlf': False}, 'minicut/workspace/actions.py': {'base': '6f02689931a6eebb2a42ce3e86cb3380e5eea28b7492dac6c2934a796a3a2d91', 'new': 'bc4b01f0e9df456bc6d32d792075d0eb8dc0e592e1a4a4693f5c1ead782d88ca', 'edits': [('    def _build_editor(self):\n', '    def _build_editor(self):\n        self._saved_sig = self._proj_sig() if self.proj else None      # auto save: the project as it was opened / created\n')], 'crlf': False}, 'minicut/shared/dialogs.py': {'base': '71e2674aa1a97f32e3b84400ba9d6b03133b3a550f4644d525964426b43b143f', 'new': '25e1fb0b826f4fe6f22837d45e035964eaaa642124f9bbb1554eb75652188336', 'edits': [('        row(f5, "Microphone", self.mic)\n        vl.addWidget(c5)\n', '        row(f5, "Microphone", self.mic)\n        vl.addWidget(c5)\n\n        # ── 6. Auto save ─────────────────────────────────────────────────────\n        c6, f6 = sec("Auto save", "save")\n        self.autosave = QCheckBox("Save the project automatically"); self.autosave.setChecked(bool(s["autosave"])); row(f6, "", self.autosave)\n        self.autosave_min = QSpinBox(); self.autosave_min.setRange(1, 60); self.autosave_min.setSuffix(" min"); self.autosave_min.setValue(int(s["autosave_min"])); row(f6, "Every", self.autosave_min)\n        vl.addWidget(c6)\n'), ('        s["audio_input"] = self.mic.currentData() or ""\n', '        s["audio_input"] = self.mic.currentData() or ""; s["autosave"] = self.autosave.isChecked(); s["autosave_min"] = self.autosave_min.value()\n')], 'crlf': False}}

REPLACE = {}

NEW_FILES = {'minicut/project/autosave.py': '"""Auto save: every few minutes (Settings > General > Auto save) the open project is saved over its own file,\nexactly like Ctrl+S, but only when something changed since the last save. Nothing is shown unless it fails."""\nimport hashlib, json\nfrom ..shared.deps import *\n\n\nclass AutosaveMixin:\n    def _proj_sig(self):\n        """Fingerprint of the project\'s content (to see whether anything changed since the last save)."""\n        return hashlib.md5(json.dumps(self.proj.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()\n\n    def autosave_apply(self):\n        """(Re)start the timer from the settings. Called at start and after Settings is closed with OK."""\n        tm = getattr(self, "_autosave_timer", None)\n        if tm is None: tm = self._autosave_timer = QTimer(self); tm.timeout.connect(self.autosave_tick)\n        tm.stop()\n        if self.settings["autosave"]: tm.start(max(1, int(self.settings["autosave_min"])) * 60000)\n\n    def autosave_tick(self):\n        if not self.proj or self.stack.currentWidget() is not self.editor or getattr(self, "_rec", None): return\n        try: sig = self._proj_sig()\n        except Exception: return\n        if sig == getattr(self, "_saved_sig", None): return        # nothing changed\n        self._quiet_save = True\n        try: self.save_project()\n        finally: self._quiet_save = False\n'}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "autosave"
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
    say("MiniCut Patch 28: auto save\n")
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
    say("To undo:  python apply_28_autosave.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

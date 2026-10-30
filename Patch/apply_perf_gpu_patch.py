#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch: PREVIEW SMOOTHNESS + GPU SETTINGS
=======================================================
Needs the EFFECTS patch to be installed first (apply_effects_patch.py).

New settings (Settings window -> General):
  * Preview FPS           24 / 30 / 60.  Sets how often the preview is refreshed while playing.
  * Adaptive preview      while playing, the preview is drawn smaller automatically when the PC cannot keep up.
  * GPU video decode      experimental. Asks FFmpeg (through OpenCV) to decode video on the GPU, and falls back
                          to the CPU decoder if that is not supported.  Off by default.
  * Export encoder        Auto / CPU / NVIDIA NVENC / Intel QuickSync / AMD AMF.
  * Check GPU encoders    runs a tiny test encode for each GPU encoder and reports which ones really work.

GPU export is verified with a real test encode before it is used. If the GPU encoder does not work, the CPU
encoder (libx264 / libx265) is used, as before.

Files changed (the originals are backed up first):
  minicut/shared/core.py, minicut/shared/dialogs.py, minicut/app.py, minicut/render/media.py,
  minicut/render/preview.py, minicut/render/renderer.py, minicut/render/export.py
New file:
  minicut/shared/hwaccel.py

Run it from the MiniCut folder (the one that contains file.py and the minicut/ folder):

    python apply_perf_gpu_patch.py            install the update
    python apply_perf_gpu_patch.py --check    only show what would change
    python apply_perf_gpu_patch.py --revert   undo the last install (restores the backed-up files)
    python apply_perf_gpu_patch.py --force    install even if you edited some of the files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

EDITS = {'minicut/app.py': {'base': 'f848b2e4e99971ac0d617d57b4b91876a419d0793cac8e3b63392f994b9c4132',
                    'crlf': False,
                    'edits': [("CFG['frame_cache']=self.settings['frame_cache'];",
                               "CFG['frame_cache']=self.settings['frame_cache']; CFG['hw_decode']=self.settings['hw_decode']; "
                               "CFG['encode_hw']=self.settings['encode_hw'];"),
                              ('self.timer=QTimer(self); self.timer.setInterval(33);', 'self.timer=QTimer(self); self.timer.setInterval(self.frame_ms());'),
                              ('    def open_settings(self):\n        d=SettingsDialog(self)\n        if d.exec() and self.proj:self.request_render()',
                               "    def frame_ms(self): return max(8, int(round(1000 / max(1, int(self.settings['preview_fps'])))))\n"
                               '    def apply_preview_fps(self): self.timer.setInterval(self.frame_ms())\n'
                               '    def open_settings(self):\n'
                               '        d=SettingsDialog(self)\n'
                               '        if d.exec():\n'
                               '            self.apply_preview_fps()\n'
                               '            if self.proj:self.request_render()')],
                    'new': 'ebd5f0340e82c3ed2352540a472b23027a4c9caa6cf4ed0fe865be7a5920d9a5'},
 'minicut/render/export.py': {'base': 'baf25439733abba25f664562fe69099eb74a8fc461a51881fd05a5022a7d2c35',
                              'crlf': False,
                              'edits': [('from .renderer import *\n', 'from .renderer import *\nfrom ..shared.hwaccel import *\n'),
                                        ('                # Prefer AMD AMF hardware encoding when this FFmpeg build exposes it.\n'
                                         '                # imageio-ffmpeg builds differ, so detect capability and keep CPU fallback.\n'
                                         "                if fmt in ('mp4', 'mp4_265'):\n"
                                         '                    try:\n'
                                         "                        enc = subprocess.run([FFMPEG, '-hide_banner', '-encoders'], capture_output=True,\n"
                                         "                                             text=True, errors='ignore', creationflags=NOWIN, timeout=8).stdout\n"
                                         "                        if fmt == 'mp4' and 'h264_amf' in enc: vcodec = 'h264_amf'\n"
                                         "                        elif fmt == 'mp4_265' and 'hevc_amf' in enc: vcodec = 'hevc_amf'\n"
                                         '                    except Exception: pass\n'
                                         "                cmd += ['-c:v',vcodec]\n"
                                         "                if fmt=='mov': cmd += ['-profile:v','3']\n"
                                         "                elif fmt=='webm': cmd += ['-b:v','4M']\n"
                                         "                elif vcodec in ('h264_amf', 'hevc_amf'):\n"
                                         '                    # AMF has its own quality controls; avoid x264-only CRF/preset options.\n'
                                         "                    cmd += ['-quality','balanced','-b:v', ('8M' if ow >= 1920 else '4M'), '-pix_fmt','yuv420p']\n"
                                         "                else: cmd += ['-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p']\n",
                                         "                hwenc = pick_hw_encoder(fmt == 'mp4_265') if fmt in ('mp4', 'mp4_265') else None\n"
                                         '                if hwenc: vcodec = hwenc[1]\n'
                                         "                cmd += ['-c:v',vcodec]\n"
                                         "                if fmt=='mov': cmd += ['-profile:v','3']\n"
                                         "                elif fmt=='webm': cmd += ['-b:v','4M']\n"
                                         '                elif hwenc: cmd += hw_quality_args(hwenc[0], crf, ow)\n'
                                         "                else: cmd += ['-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p']\n")],
                              'new': '93073bf25fbb58760d99f43b7069de42463554b67133bb936732a46115663a7f'},
 'minicut/render/media.py': {'base': '1cd6c97c7c9b4870e5ae36bc9a7a1372204a991bb456af0df5e960e3ff6178e1',
                             'crlf': False,
                             'edits': [('class VideoSource:\n    def __init__(self, path):\n        self.cap = cv2.VideoCapture(safe_path(path))',
                                        'def open_capture(path):\n'
                                        '    """Open a video file. With "hw_decode" on (Settings) FFmpeg is asked to decode on the GPU; if that is not\n'
                                        '    supported on this PC, fall back to the normal CPU decoder."""\n'
                                        '    if CFG.get("hw_decode"):\n'
                                        '        try:\n'
                                        '            cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG, [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY])\n'
                                        '            if cap.isOpened() and cap.read()[0]: return cap\n'
                                        '            cap.release()\n'
                                        '        except Exception: pass\n'
                                        '    return cv2.VideoCapture(path)\n'
                                        '\n'
                                        '\n'
                                        'class VideoSource:\n'
                                        '    def __init__(self, path):\n'
                                        '        self.cap = open_capture(safe_path(path))')],
                             'new': '9557f646b3ce868f74dc1149c5c39946db8d739c9b7e97c1a322ab5f43635479'},
 'minicut/render/preview.py': {'base': '10431379ae38977fd84348da9847c8d7db58e428a15480c0b8eec25baee7df35',
                               'crlf': False,
                               'edits': [('w = getattr(self, "_rworker", None)\n',
                                          'w = getattr(self, "_rworker", None)\n'
                                          '        # Adaptive preview: while playing, draw smaller if one frame takes longer than one frame interval.\n'
                                          '        if self.playing and self.settings["adaptive_preview"] and w is not None:\n'
                                          '            budget = self.frame_ms(); ms = getattr(w, "last_ms", 0.0); a = getattr(self, "_adapt", 1.0)\n'
                                          '            if ms > budget * 1.1: a = max(0.25, a * 0.85)\n'
                                          '            elif ms < budget * 0.6: a = min(1.0, a * 1.1)\n'
                                          '            self._adapt = a; q *= a\n'
                                          '        else: self._adapt = 1.0\n')],
                               'new': '5924858e6273140873d5038d58e64327ffa27b36cb141abe0c9c364f35788e01'},
 'minicut/render/renderer.py': {'base': '3e10a8880d1425121a506c127e97c31aa3a1bba180159bbbd807309671fae072',
                                'crlf': False,
                                'edits': [('self.job = None; self.alive = True\n', 'self.job = None; self.alive = True; self.last_ms = 0.0\n'),
                                          ('with self.r._src_lock: fr = self.r.render_cached(snap, t, q, fast)',
                                           't0 = time.perf_counter()\n'
                                           '                with self.r._src_lock: fr = self.r.render_cached(snap, t, q, fast)\n'
                                           '                self.last_ms = (time.perf_counter() - t0) * 1000.0')],
                                'new': 'b23a5ef5f391076c3ef307317d8c708cbd39a603f87af5a4e03e8225f6bb8897'},
 'minicut/shared/core.py': {'base': 'db598f6cf01e8680e9af3c7768c88f092d1c3911f4c433435449724a48437e61',
                            'crlf': False,
                            'edits': [('"play_reduce": True, "frame_cache": 24,',
                                       '"play_reduce": True, "frame_cache": 24,\n'
                                       '                  "preview_fps": 30, "adaptive_preview": True, "hw_decode": False, "encode_hw": "auto",')],
                            'new': 'c55f3469398b5d8dc2ee5afcba91c6da3158f1e058fc842d59dbaad94d9bd6ad'},
 'minicut/shared/dialogs.py': {'base': '6a71b4d076fa58c4921ab20c5d4a09f1862664d1a169bcaa4d795df95189f65a',
                               'crlf': False,
                               'edits': [('from .widgets import *\n', 'from .widgets import *\nfrom .hwaccel import *\n'),
                                         ('        tabs.addTab(gen, "General")',
                                          '        self.fps = QComboBox(); [self.fps.addItem("%d fps" % v, v) for v in (24, 30, 60)]; '
                                          'self.fps.setCurrentIndex(max(0, self.fps.findData(int(s["preview_fps"]))))\n'
                                          '        self.adapt = QCheckBox("Lower preview detail automatically when playback cannot keep up"); '
                                          'self.adapt.setChecked(bool(s["adaptive_preview"]))\n'
                                          '        self.hwdec = QCheckBox("Decode video on the GPU (experimental, falls back to CPU)"); '
                                          'self.hwdec.setChecked(bool(s["hw_decode"]))\n'
                                          '        self.enc = QComboBox(); [self.enc.addItem(l, v) for l, v in ENCODE_CHOICES]; '
                                          'self.enc.setCurrentIndex(max(0, self.enc.findData(s["encode_hw"])))\n'
                                          '        self.gpu_lbl = QLabel("Not checked yet. Press the button to test which GPU encoders work on this PC."); '
                                          'self.gpu_lbl.setObjectName("Dim"); self.gpu_lbl.setWordWrap(True)\n'
                                          '        gb = QPushButton("Check GPU encoders"); gb.clicked.connect(self.check_gpu)\n'
                                          '        form.addRow("Preview FPS", self.fps); form.addRow("", self.adapt); form.addRow("", self.hwdec)\n'
                                          '        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl)\n'
                                          '        tabs.addTab(gen, "General")'),
                                         ('    def save(self):\n        s = self.app.settings',
                                          '    def check_gpu(self):\n'
                                          '        self.gpu_lbl.setText("Testing ..."); QApplication.processEvents()\n'
                                          '        found = detect_gpu_encoders()\n'
                                          '        self.gpu_lbl.setText("GPU encoders that work: " + ", ".join(found) if found else "No GPU encoder works with '
                                          'this FFmpeg / driver. The CPU encoder will be used.")\n'
                                          '    def save(self):\n'
                                          '        s = self.app.settings'),
                                         ('        os.makedirs(s["project_folder"], exist_ok=True); self._collect(); s.save(); apply_ui(self.app); '
                                          'self._applied = False; self.accept()',
                                          '        s["preview_fps"] = int(self.fps.currentData()); s["adaptive_preview"] = self.adapt.isChecked(); '
                                          's["hw_decode"] = self.hwdec.isChecked(); s["encode_hw"] = self.enc.currentData()\n'
                                          '        CFG["hw_decode"] = s["hw_decode"]; CFG["encode_hw"] = s["encode_hw"]; clear_gpu_cache()\n'
                                          '        os.makedirs(s["project_folder"], exist_ok=True); self._collect(); s.save(); apply_ui(self.app); '
                                          'self._applied = False; self.accept()')],
                               'new': 'b1ecf32bedbc0455150c4e1042716391e45859e712798a92e0ffa1b6997d958b'}}

NEW_FILES = {'minicut/shared/hwaccel.py': '"""GPU helpers: detect which hardware video encoders really work, and the matching encoder options.\n'
                              '\n'
                              'A listed encoder is not proof that it runs: FFmpeg builds often compile NVENC / QSV / AMF in even on PCs that\n'
                              'do not have that GPU.  So every candidate is checked with a tiny real encode before it is used.\n'
                              '"""\n'
                              'from .core import *\n'
                              '\n'
                              '\n'
                              'ENCODE_CHOICES = [("Auto (GPU if it works, otherwise CPU)", "auto"), ("CPU only (libx264 / libx265)", "cpu"),\n'
                              '                  ("NVIDIA NVENC", "nvenc"), ("Intel QuickSync", "qsv"), ("AMD AMF", "amf")]\n'
                              'HW_ENCODERS = {"nvenc": ("h264_nvenc", "hevc_nvenc"), "qsv": ("h264_qsv", "hevc_qsv"), "amf": ("h264_amf", "hevc_amf")}\n'
                              'HW_NAMES = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QuickSync", "amf": "AMD AMF"}\n'
                              '\n'
                              '_LISTED = {}     # ffmpeg -encoders output (fetched once)\n'
                              '_WORKS = {}      # encoder name -> True / False (test encode result)\n'
                              '\n'
                              '\n'
                              'def clear_gpu_cache():\n'
                              '    _LISTED.clear(); _WORKS.clear()\n'
                              '\n'
                              '\n'
                              'def _listed_encoders():\n'
                              '    if "text" not in _LISTED:\n'
                              '        try:\n'
                              '            _LISTED["text"] = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True,\n'
                              '                                             errors="ignore", creationflags=NOWIN, timeout=15).stdout\n'
                              '        except Exception:\n'
                              '            _LISTED["text"] = ""\n'
                              '    return _LISTED["text"]\n'
                              '\n'
                              '\n'
                              'def encoder_works(name):\n'
                              '    """Encode three black frames with the encoder. Returns True only if FFmpeg finishes without error."""\n'
                              '    if name not in _WORKS:\n'
                              '        if name not in _listed_encoders():\n'
                              '            _WORKS[name] = False\n'
                              '        else:\n'
                              '            try:\n'
                              '                r = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",\n'
                              '                                    "color=c=black:s=256x256:d=0.2", "-frames:v", "3", "-c:v", name,\n'
                              '                                    "-pix_fmt", "yuv420p", "-f", "null", "-"],\n'
                              '                                   capture_output=True, creationflags=NOWIN, timeout=25)\n'
                              '                _WORKS[name] = r.returncode == 0\n'
                              '            except Exception:\n'
                              '                _WORKS[name] = False\n'
                              '    return _WORKS[name]\n'
                              '\n'
                              '\n'
                              'def pick_hw_encoder(hevc=False, choice=None):\n'
                              '    """Return (vendor, encoder_name) for the GPU encoder to use, or None to stay on the CPU."""\n'
                              '    choice = choice or CFG.get("encode_hw", "auto")\n'
                              '    if choice == "cpu": return None\n'
                              '    vendors = [choice] if choice in HW_ENCODERS else ["nvenc", "qsv", "amf"]\n'
                              '    for vendor in vendors:\n'
                              '        name = HW_ENCODERS[vendor][1 if hevc else 0]\n'
                              '        if encoder_works(name): return vendor, name\n'
                              '    if choice in HW_ENCODERS:\n'
                              '        print("GPU encoder %s is not available here, using the CPU encoder." % HW_NAMES[choice])\n'
                              '    return None\n'
                              '\n'
                              '\n'
                              'def hw_quality_args(vendor, crf, out_w):\n'
                              '    """Quality options for each GPU encoder (they do not accept the x264 -crf / -preset options)."""\n'
                              '    if vendor == "nvenc": return ["-preset", "p4", "-rc", "vbr", "-cq", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p"]\n'
                              '    if vendor == "qsv": return ["-global_quality", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]\n'
                              '    return ["-quality", "balanced", "-b:v", ("8M" if out_w >= 1920 else "4M"), "-pix_fmt", "yuv420p"]\n'
                              '\n'
                              '\n'
                              'def detect_gpu_encoders():\n'
                              '    """For the Settings button: names of the GPU encoders that work for H.264 on this PC."""\n'
                              '    clear_gpu_cache()\n'
                              '    return [HW_NAMES[v] for v in ("nvenc", "qsv", "amf") if encoder_works(HW_ENCODERS[v][0])]\n'}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nIf the effects patch is not installed yet, install it first (apply_effects_patch.py).\n"
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
    say("Start MiniCut as usual (Run_MiniCut.bat). Open Settings -> General to set Preview FPS, adaptive preview,")
    say("GPU decode and the export encoder. Press 'Check GPU encoders' to see which GPU encoders work here.")
    say("To undo:  python apply_perf_gpu_patch.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

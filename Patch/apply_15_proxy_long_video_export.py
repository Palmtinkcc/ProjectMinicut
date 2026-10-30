#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 15: PROXY FOR LONG VIDEOS, DISK BUDGET, EXPORT CODECS
==========================================================================
Install AFTER apply_15_proxy_long_video_export.py.

  * Proxy in one pass: the whole video is converted by one ffmpeg run that writes the pieces (about 2 s each) and their
    exact timing. Before, ffmpeg was started once per piece, which is far too slow for an hour of 10 GB video.
  * Disk budget for proxies: Settings -> Proxy disk budget, 25 to 50 GB (default 40). When the folder is over the
    budget the least recently used videos are removed. Videos in use are never removed.
  * Export: AV1 added. Each format uses the GPU encoder when this PC really has one for that codec (checked with a
    short test encode). When it does not, the export says so in the progress ring: e.g. "No GPU encoder for AV1 works
    on this PC, so the CPU encoder libsvtav1 is used. It is slower." The export also shows in the progress ring.
  * The timeline's yellow bars use the exact piece times.

New files: none. Changed files: minicut/render/media.py, minicut/render/export.py, minicut/shared/hwaccel.py,
minicut/workspace/timeline.py, minicut/shared/core.py, minicut/app.py, minicut/shared/dialogs.py
(originals are backed up first)

    python apply_15_proxy_long_video_export.py            install the update
    python apply_15_proxy_long_video_export.py --check    only show what would change
    python apply_15_proxy_long_video_export.py --revert   undo the last install
    python apply_15_proxy_long_video_export.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': '45adb8f7ede62240417f3df9e26bae1a2093c3fefd8ef429d3045a89c1a2d3a2',
                    'crlf': False,
                    'edits': [("CFG['proxy_quality']=self.settings['proxy_quality'];",
                               "CFG['proxy_quality']=self.settings['proxy_quality']; CFG['proxy_budget_gb']=self.settings['proxy_budget_gb'];")],
                    'new': 'b25e0740bd82c049221b160a049a49b1db774de56cbb30c20e3950e977ac3c04'},
 'minicut/render/export.py': {'base': 'd96bb970917b2d0b52939531df88a0d1408e0195e6b76a025ad4ed6e84410d37',
                              'crlf': False,
                              'edits': [('("mp4_265", ("MP4 · H.265 / HEVC", ".mp4")), ',
                                         '("mp4_265", ("MP4 · H.265 / HEVC", ".mp4")), ("av1", ("AV1 · AV1 (GPU if this PC can, else CPU)", ".mp4")), '),
                                        ('from ..shared.hwaccel import *\n', 'from ..shared.hwaccel import *\nfrom ..shared.tasks import TASKS\n'),
                                        ('    def run(self):\n        tmpd = None; proc = None\n',
                                         '    def run(self):\n'
                                         '        self._task = TASKS.start("export", "Export  " + os.path.basename(self.o["path"]))\n'
                                         '        try: self._run()\n'
                                         '        finally: self._task.finish()\n'
                                         '    def _run(self):\n'
                                         '        tmpd = None; proc = None\n'),
                                        ('                if i%3==0: self.progress.emit((i+1)/total*100)\n',
                                         '                if i%3==0: self.progress.emit((i+1)/total*100); self._task.total = total; self._task.done = i + 1\n'),
                                        ("                vcodec='libx265' if fmt=='mp4_265' else 'libvpx-vp9' if fmt=='webm' else 'prores_ks' if fmt=='mov' "
                                         "else 'libx264'\n"
                                         "                hwenc = pick_hw_encoder(fmt == 'mp4_265') if fmt in ('mp4', 'mp4_265') else None\n"
                                         '                if hwenc: vcodec = hwenc[1]\n',
                                         '                vcodec, hwenc, _note = codec_plan(fmt)\n'
                                         '                if vcodec is None: raise RuntimeError(_note)\n'
                                         '                self._task.detail = _note\n'),
                                        ("                else: cmd += ['-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p']\n",
                                         "                elif vcodec=='libsvtav1': cmd += ['-crf',str(crf),'-preset','8','-pix_fmt','yuv420p']\n"
                                         "                elif vcodec=='libaom-av1': cmd += "
                                         "['-crf',str(crf),'-b:v','0','-cpu-used','6','-row-mt','1','-pix_fmt','yuv420p']\n"
                                         "                else: cmd += ['-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p']\n"),
                                        ("                cmd += ['-movflags','+faststart'] if fmt in ('mp4','mp4_265','mkv') else []",
                                         "                cmd += ['-movflags','+faststart'] if fmt in ('mp4','mp4_265','mkv','av1') else []")],
                              'new': '05392194245760548b102d21e0b89afbf6bd859f29e87ae3878778872a9669a4'},
 'minicut/shared/core.py': {'base': 'd3a9d8ab2a49eaef9072f3e8c61cc2403c4fc359311852415e3e17cd96629cda',
                            'crlf': False,
                            'edits': [('"layout": None, "curve_presets": {},', '"layout": None, "curve_presets": {}, "proxy_budget_gb": 40,')],
                            'new': '1e748488a8318a0ba571169a8df0b46467189bc340ccf21651ddc90154cc64c4'},
 'minicut/shared/dialogs.py': {'base': 'f4a0b926586afc1d7aefecf556cb3aaf8f2808ea7476969dbcec6a734ddc12d7',
                               'crlf': False,
                               'edits': [('        form.addRow("Proxy size", self.p_h); form.addRow("Proxy quality", self.p_q); form.addRow("Proxy cache", '
                                          'self.p_size); form.addRow("", pb)\n',
                                          '        self.p_budget = QSpinBox(); self.p_budget.setRange(25, 50); self.p_budget.setSuffix(" GB"); '
                                          'self.p_budget.setValue(int(self.app.settings["proxy_budget_gb"]))\n'
                                          '        self.p_budget.setToolTip("The proxy folder is kept under this size. The least recently used videos are '
                                          'removed first.")\n'
                                          '        form.addRow("Proxy size", self.p_h); form.addRow("Proxy quality", self.p_q); form.addRow("Proxy disk '
                                          'budget", self.p_budget); form.addRow("Proxy cache", self.p_size); form.addRow("", pb)\n'),
                                         ('CFG["proxy_quality"] = s["proxy_quality"]',
                                          'CFG["proxy_quality"] = s["proxy_quality"]; s["proxy_budget_gb"] = int(self.p_budget.value()); '
                                          'CFG["proxy_budget_gb"] = s["proxy_budget_gb"]')],
                               'new': 'dd1724545a6d221d99e4ba8d30e0287aa08fece66c4b1bfeb8e6760108d872d5'},
 'minicut/shared/hwaccel.py': {'base': 'e4cef256faf767d8d9997dc0c3dd3f29be65ed2bc7ce9d6c42f616916244dd6c',
                               'crlf': False,
                               'edits': [('def detect_gpu_encoders():',
                                          'GPU_CODECS = {"h264": {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"},\n'
                                          '              "hevc": {"nvenc": "hevc_nvenc", "qsv": "hevc_qsv", "amf": "hevc_amf"},\n'
                                          '              "av1": {"nvenc": "av1_nvenc", "qsv": "av1_qsv", "amf": "av1_amf"}}\n'
                                          'CPU_CODECS = {"h264": ["libx264"], "hevc": ["libx265"], "av1": ["libsvtav1", "libaom-av1"], "vp9": ["libvpx-vp9"], '
                                          '"prores": ["prores_ks"]}\n'
                                          'CODEC_OF_FORMAT = {"mp4": "h264", "mkv": "h264", "mp4_265": "hevc", "av1": "av1", "webm": "vp9", "mov": "prores"}\n'
                                          '\n'
                                          '\n'
                                          'def cpu_encoder_for(codec):\n'
                                          '    listed = _listed_encoders()\n'
                                          '    for name in CPU_CODECS.get(codec, []):\n'
                                          '        if name in listed: return name\n'
                                          '    return None\n'
                                          '\n'
                                          '\n'
                                          'def codec_plan(fmt):\n'
                                          '    """(encoder name, hardware tuple or None, note) for an export format, checked on this PC.\n'
                                          '    The note says what will be used and why, e.g. when the GPU has no encoder for that codec."""\n'
                                          '    codec = CODEC_OF_FORMAT.get(fmt)\n'
                                          '    if codec is None: return None, None, ""\n'
                                          '    if codec in ("vp9", "prores"):\n'
                                          '        cpu = cpu_encoder_for(codec)\n'
                                          '        if cpu is None: return None, None, "This FFmpeg build has no encoder for %s." % codec\n'
                                          '        return cpu, None, "CPU encoder %s is used (no GPU encoder for this format)." % cpu\n'
                                          '    want = CFG.get("encode_hw", "auto")\n'
                                          '    if want != "cpu":\n'
                                          '        for vendor in ("nvenc", "qsv", "amf"):\n'
                                          '            if want not in ("auto", vendor): continue\n'
                                          '            name = GPU_CODECS.get(codec, {}).get(vendor)\n'
                                          '            if name and encoder_works(name): return name, (vendor, name), "GPU encoder %s is used." % name\n'
                                          '    cpu = cpu_encoder_for(codec)\n'
                                          '    if cpu is None: return None, None, "This FFmpeg build has no encoder for %s." % codec\n'
                                          '    return cpu, None, "No GPU encoder for %s works on this PC, so the CPU encoder %s is used. It is slower." % '
                                          '(codec.upper(), cpu)\n'
                                          '\n'
                                          '\n'
                                          'def detect_gpu_encoders():')],
                               'new': '2a30e567d608410c9bdde018cd485f7d6b1c9b74f548599a21a6e4c3969eed44'},
 'minicut/workspace/timeline.py': {'base': '127b78fd63d01c4b14b1bc91e1ce98f51e3bc1167e1eae1c220269f0dd098e15',
                                   'crlf': False,
                                   'edits': [('                a = max(k * PROXY_CHUNK, inp); b = min((k + 1) * PROXY_CHUNK, inp + d)\n',
                                              '                ks, ke = pieces[k]; a = max(ks, inp); b = min(ke, inp + d)\n')],
                                   'new': '32d3fed5e930f562f605034913dc3b83f36743a85a577231b0961b7562a104e2'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {'minicut/render/media.py': {'base': '1283f6e9fc816f03b85afa86afb4931a4c0182030024e53de47e756bed9137e0',
                             'content': '"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""\n'
                                        'from ..shared.deps import *\n'
                                        'from ..shared.core import *\n'
                                        '\n'
                                        '\n'
                                        'def open_capture(path):\n'
                                        '    """Open a video file. With "hw_decode" on (Settings) FFmpeg is asked to decode on the GPU; if that is not\n'
                                        '    supported on this PC, fall back to the normal CPU decoder."""\n'
                                        '    # GPU decoding is switched off for every read. With some drivers the GPU decoder returns frames with a pink /\n'
                                        '    # magenta band at the top, which showed up in the viewport. The CPU decoder is used whatever the setting says.\n'
                                        '    return cv2.VideoCapture(path)\n'
                                        '\n'
                                        '\n'
                                        'import threading\n'
                                        'PROXY_HEIGHT = 540\n'
                                        'PROXY_CHUNK = 2.0                 # seconds per proxy piece (pieces are finished one by one, in order)\n'
                                        'PROXY_JOB_TIMEOUT = 180           # seconds one ffmpeg call may take before the job is given up\n'
                                        'PROXY_RETRY_AFTER = 20.0          # seconds before a failed video is tried again\n'
                                        '\n'
                                        '\n'
                                        'def proxy_dir(path):\n'
                                        '    """Folder with the proxy pieces of this video. The name depends on the file and on the proxy settings,\n'
                                        '    so changing the size / quality never reuses old pieces."""\n'
                                        '    import hashlib\n'
                                        '    st = os.stat(path)\n'
                                        '    key = hashlib.sha1(("%s|%d|%d|%s|%s" % (os.path.abspath(path), st.st_size, int(st.st_mtime),\n'
                                        '                                            CFG.get("proxy_height", PROXY_HEIGHT), CFG.get("proxy_quality", '
                                        '23))).encode("utf-8")).hexdigest()[:24]\n'
                                        '    d = os.path.join(APP_DIR, "proxies", key); os.makedirs(d, exist_ok=True)\n'
                                        '    return d\n'
                                        '\n'
                                        '\n'
                                        'def _piece_path(d, k): return os.path.join(d, "p%05d.mp4" % k)\n'
                                        '\n'
                                        '\n'
                                        'def proxy_index(d):\n'
                                        '    """Pieces written so far: [(file name, start second, end second)] from index.csv (ffmpeg writes a line per '
                                        'finished piece)."""\n'
                                        '    out = []\n'
                                        '    try:\n'
                                        '        with open(os.path.join(d, "index.csv"), encoding="utf-8", errors="replace") as f:\n'
                                        '            for line in f:\n'
                                        '                parts = line.strip().split(",")\n'
                                        '                if len(parts) < 3: continue\n'
                                        '                try: out.append((parts[0], float(parts[1]), float(parts[2])))\n'
                                        '                except ValueError: continue\n'
                                        '    except OSError: pass\n'
                                        '    return out\n'
                                        '\n'
                                        '\n'
                                        'def proxy_pieces(path):\n'
                                        '    """{piece number: (start, end)} of the finished proxy pieces of this video (cheap; called often)."""\n'
                                        '    try: d = proxy_dir(path)\n'
                                        '    except Exception: return {}\n'
                                        '    out = {}\n'
                                        '    for name, s, e in proxy_index(d):\n'
                                        '        m = re.match(r"p(\\d+)\\.mp4$", name)\n'
                                        '        if m and os.path.exists(os.path.join(d, name)): out[int(m.group(1))] = (s, e)\n'
                                        '    return out\n'
                                        '\n'
                                        '\n'
                                        'def video_duration(path):\n'
                                        '    cap = cv2.VideoCapture(safe_path(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 30; n = '
                                        'cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0; cap.release()\n'
                                        '    return n / fps if n > 0 else 0.0\n'
                                        '\n'
                                        '\n'
                                        'from ..shared.tasks import TASKS\n'
                                        'import bisect, heapq, math, re, shutil, threading, time, subprocess\n'
                                        '\n'
                                        '\n'
                                        'def make_proxy(path, d, alive, task=None):\n'
                                        '    """One ffmpeg run turns the whole video into proxy pieces (about 2 s each). ffmpeg writes the exact start and '
                                        'end\n'
                                        "    of every piece to index.csv, so the timing stays exact however long the video is. Returns 'done', 'failed' or "
                                        '\'cancelled\'."""\n'
                                        '    if os.path.exists(os.path.join(d, "done")): return "done"\n'
                                        '    for f in os.listdir(d):                       # an earlier run did not finish: start clean\n'
                                        '        p = os.path.join(d, f)\n'
                                        '        if os.path.isfile(p):\n'
                                        '            try: os.remove(p)\n'
                                        '            except OSError: pass\n'
                                        '    dur = video_duration(path)\n'
                                        '    if task is not None: task.total = int(math.ceil(dur / PROXY_CHUNK)) if dur else None\n'
                                        '    cmd = [FFMPEG, "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", path, "-an",\n'
                                        '           "-vf", "scale=-2:min(%d\\\\,ih)" % int(CFG.get("proxy_height", PROXY_HEIGHT)),\n'
                                        '           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(CFG.get("proxy_quality", 23))),\n'
                                        '           "-g", "1", "-pix_fmt", "yuv420p", "-f", "segment", "-segment_time", "%.3f" % PROXY_CHUNK,\n'
                                        '           "-reset_timestamps", "1", "-segment_format", "mp4", "-segment_list", os.path.join(d, "index.csv"),\n'
                                        '           "-segment_list_type", "csv", os.path.join(d, "p%05d.mp4")]\n'
                                        '    try:\n'
                                        '        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",\n'
                                        '                                creationflags=NOWIN | (0x00004000 if os.name == "nt" else 0))\n'
                                        '    except Exception as ex:\n'
                                        '        print("proxy error:", ex); return "failed"\n'
                                        '    for line in proc.stdout:\n'
                                        '        if not alive():\n'
                                        '            proc.kill(); proc.wait(); return "cancelled"\n'
                                        '        if task is not None and line.startswith("out_time_us="):\n'
                                        '            try:\n'
                                        '                secs = int(line.split("=", 1)[1]) / 1e6\n'
                                        '                task.done = int(secs / PROXY_CHUNK); task.detail = "%d s of %d s" % (int(secs), int(dur or 0))\n'
                                        '            except ValueError: pass\n'
                                        '    rc = proc.wait()\n'
                                        '    if not alive(): return "cancelled"\n'
                                        '    if rc == 0 and proxy_index(d):\n'
                                        '        open(os.path.join(d, "done"), "w").close(); return "done"\n'
                                        '    err = (proc.stderr.read() or "")[-300:]\n'
                                        '    if err: print("proxy ffmpeg:", err)\n'
                                        '    return "failed"\n'
                                        '\n'
                                        '\n'
                                        'def proxy_cleanup(budget, keep):\n'
                                        '    """Keep the proxy folder under the budget: the least recently used videos are removed first. Never removes '
                                        '\'keep\'."""\n'
                                        '    root = os.path.join(APP_DIR, "proxies")\n'
                                        '    if not os.path.isdir(root): return\n'
                                        '    dirs = []; total = 0\n'
                                        '    for name in os.listdir(root):\n'
                                        '        p = os.path.join(root, name)\n'
                                        '        if not os.path.isdir(p): continue\n'
                                        '        size = 0\n'
                                        '        for f in os.listdir(p):\n'
                                        '            try: size += os.path.getsize(os.path.join(p, f))\n'
                                        '            except OSError: pass\n'
                                        '        dirs.append((os.path.getmtime(p), size, p)); total += size\n'
                                        '    dirs.sort()\n'
                                        '    for _, size, p in dirs:\n'
                                        '        if total <= budget: break\n'
                                        '        if p in keep: continue\n'
                                        '        shutil.rmtree(p, ignore_errors=True); total -= size\n'
                                        '\n'
                                        '\n'
                                        'class ProxyManager:\n'
                                        '    """Builds the proxies in one background thread. The video nearest the playhead is built first (priority).\n'
                                        '    reset() cancels everything (settings changed, cache cleared). The folder is kept under the disk budget."""\n'
                                        '    def __init__(self):\n'
                                        '        self.gen = 0; self.state = {}; self.lock = threading.Lock(); self.cv = threading.Condition(self.lock)\n'
                                        '        self.heap = []; self.seq = 0; self.thread = None; self.pool = None\n'
                                        '    def want(self, path, prio=0.0):\n'
                                        '        d = proxy_dir(path)\n'
                                        '        with self.lock:\n'
                                        '            st = self.state.get(d)\n'
                                        '            if st is not None:\n'
                                        '                status, when = st\n'
                                        '                if status in ("queued", "running"): return\n'
                                        '                if status == "done" and proxy_pieces(path): return\n'
                                        '                if time.monotonic() - when < PROXY_RETRY_AFTER: return\n'
                                        '            self.state[d] = ("queued", time.monotonic()); self.seq += 1\n'
                                        '            heapq.heappush(self.heap, (prio, self.seq, path, d, self.gen)); self.cv.notify()\n'
                                        '            if self.thread is None:\n'
                                        '                self.thread = threading.Thread(target=self._loop, daemon=True, name="proxy-builder"); '
                                        'self.thread.start()\n'
                                        '    def _keep(self, d):\n'
                                        '        keep = {d}\n'
                                        '        try:\n'
                                        '            if self.pool is not None:\n'
                                        '                keep |= {s.dir for s in list(self.pool.src.values()) if getattr(s, "dir", None)}\n'
                                        '        except RuntimeError: pass\n'
                                        '        return keep\n'
                                        '    def _loop(self):\n'
                                        '        while True:\n'
                                        '            with self.lock:\n'
                                        '                while not self.heap: self.cv.wait()\n'
                                        '                prio, _, path, d, g = heapq.heappop(self.heap)\n'
                                        '                if g != self.gen: continue\n'
                                        '                self.state[d] = ("running", time.monotonic())\n'
                                        '            status = "failed"; task = TASKS.start("proxy", "Proxy  " + os.path.basename(path))\n'
                                        '            try: status = make_proxy(path, d, lambda: g == self.gen, task)\n'
                                        '            except Exception as ex: print("proxy error:", ex)\n'
                                        '            finally: task.finish()\n'
                                        '            try: proxy_cleanup(float(CFG.get("proxy_budget_gb", 40)) * 1e9, self._keep(d))\n'
                                        '            except Exception as ex: print("proxy cleanup:", ex)\n'
                                        '            with self.lock:\n'
                                        '                if g == self.gen: self.state[d] = (status, time.monotonic())\n'
                                        '    def reset(self):\n'
                                        '        with self.lock: self.gen += 1; self.state.clear(); self.heap = []\n'
                                        '\n'
                                        '\n'
                                        'PROXY = ProxyManager()\n'
                                        'PROXY = ProxyManager()\n'
                                        '\n'
                                        '\n'
                                        'class _Reader:\n'
                                        '    """One opened video file. Reads forward when the next frame is close, seeks otherwise."""\n'
                                        '    def __init__(self, cap):\n'
                                        '        self.cap = cap; self.pos = -10; self.raw = None; self.n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)\n'
                                        '    def read(self, idx):\n'
                                        '        if self.n > 0: idx = max(0, min(self.n - 1, idx))\n'
                                        '        if idx != self.pos or self.raw is None:\n'
                                        '            gap = idx - self.pos\n'
                                        '            if 0 < gap <= 8:\n'
                                        '                for _ in range(gap - 1): self.cap.grab()\n'
                                        '            else: self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)\n'
                                        '            ok, f = self.cap.read()\n'
                                        '            if ok: self.raw = f; self.pos = idx\n'
                                        '            else:\n'
                                        '                self.pos = -10\n'
                                        '                if self.raw is None: return None\n'
                                        '        return self.raw\n'
                                        '    def release(self):\n'
                                        '        try: self.cap.release()\n'
                                        '        except Exception: pass\n'
                                        '\n'
                                        '\n'
                                        'class VideoSource:\n'
                                        '    """Frames of a video. A finished proxy piece covering the time is used when there is one; otherwise the original\n'
                                        '    file. Size, fps and length always come from the original file."""\n'
                                        '    KEEP_PIECES = 3\n'
                                        '    def __init__(self, path, use_proxy=False):\n'
                                        '        probe = open_capture(safe_path(path))\n'
                                        '        if not probe.isOpened(): raise IOError("cannot open " + path)\n'
                                        '        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30\n'
                                        '        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)\n'
                                        '        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))\n'
                                        '        self.orig = _Reader(probe)\n'
                                        '        self.dir = proxy_dir(path) if use_proxy else None\n'
                                        '        if self.dir:\n'
                                        '            try: os.utime(self.dir)                      # used now: keep it longest in the disk budget\n'
                                        '            except OSError: pass\n'
                                        '        self.index = []; self._starts = []; self._index_mt = None\n'
                                        '        self.pieces = OrderedDict(); self.cache = OrderedDict()\n'
                                        '    def _refresh_index(self):\n'
                                        '        if self.dir is None: return\n'
                                        '        try: mt = os.path.getmtime(os.path.join(self.dir, "index.csv"))\n'
                                        '        except OSError: return\n'
                                        '        if mt != self._index_mt:\n'
                                        '            self._index_mt = mt; self.index = proxy_index(self.dir); self._starts = [s for _, s, _ in self.index]\n'
                                        '    def _piece_for(self, t):\n'
                                        '        """(piece file name, time inside the piece) of the finished piece that covers t, or None."""\n'
                                        '        self._refresh_index()\n'
                                        '        if not self._starts: return None\n'
                                        '        i = bisect.bisect_right(self._starts, t) - 1\n'
                                        '        if i < 0: return None\n'
                                        '        name, s, e = self.index[i]\n'
                                        '        if t >= e: return None\n'
                                        '        return name, t - s\n'
                                        '    def _piece(self, name):\n'
                                        '        if name in self.pieces:\n'
                                        '            if os.path.exists(os.path.join(self.dir, name)): self.pieces.move_to_end(name); return self.pieces[name]\n'
                                        '            self.pieces.pop(name).release(); self.cache.clear(); return None      # deleted: never show it again\n'
                                        '        f = os.path.join(self.dir, name)\n'
                                        '        if not os.path.exists(f): return None\n'
                                        '        cap = cv2.VideoCapture(safe_path(f))\n'
                                        '        if not cap.isOpened(): return None\n'
                                        '        self.pieces[name] = _Reader(cap)\n'
                                        '        while len(self.pieces) > self.KEEP_PIECES: self.pieces.popitem(last=False)[1].release()\n'
                                        '        return self.pieces[name]\n'
                                        '    def frame(self, t, ds=1.0):\n'
                                        '        t = max(0.0, t)\n'
                                        '        idx = int(t * self.fps + 1e-6)\n'
                                        '        if self.n > 0: idx = max(0, min(self.n - 1, idx))\n'
                                        '        pm = self._piece_for(t) if self.dir is not None else None\n'
                                        '        key = (idx, ds, pm[0] if pm else None)\n'
                                        '        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]\n'
                                        '        raw = None\n'
                                        '        if pm:\n'
                                        '            rd = self._piece(pm[0])\n'
                                        '            if rd is not None: raw = rd.read(int(pm[1] * self.fps + 1e-6))\n'
                                        '        if raw is None: raw = self.orig.read(idx)\n'
                                        '        if raw is None: raw = np.zeros((max(1, self.h), max(1, self.w), 3), np.uint8)\n'
                                        '        tw, th = max(1, int(self.w * ds)), max(1, int(self.h * ds))\n'
                                        '        if raw.shape[1] != tw or raw.shape[0] != th:\n'
                                        '            raw = cv2.resize(raw, (tw, th), interpolation=cv2.INTER_AREA if tw < raw.shape[1] else cv2.INTER_LINEAR)\n'
                                        '        img = cv2.cvtColor(raw, cv2.COLOR_BGR2BGRA)\n'
                                        '        self.cache[key] = img\n'
                                        '        while len(self.cache) > CFG["frame_cache"]: self.cache.popitem(last=False)\n'
                                        '        return img\n'
                                        '    def close(self):\n'
                                        '        for r in self.pieces.values(): r.release()\n'
                                        '        self.pieces.clear(); self.orig.release(); self.cache.clear()\n'
                                        '\n'
                                        '\n'
                                        'class ImageSource:\n'
                                        '    def __init__(self, path):\n'
                                        '        self.img = to_bgra(imread_any(path))\n'
                                        '        if self.img is None: raise IOError("cannot open " + path)\n'
                                        '        self.h, self.w = self.img.shape[:2]; self.cache = {}\n'
                                        '    def frame(self, t, ds=1.0):\n'
                                        '        if ds >= 0.999: return self.img\n'
                                        '        if ds not in self.cache:\n'
                                        '            self.cache[ds] = cv2.resize(self.img, (max(1, int(self.w * ds)), max(1, int(self.h * ds))), '
                                        'interpolation=cv2.INTER_AREA)\n'
                                        '        return self.cache[ds]\n'
                                        '\n'
                                        '\n'
                                        'class GifSource:\n'
                                        '    def __init__(self, path):\n'
                                        '        im = Image.open(path); self.frames = []; durs = []\n'
                                        '        for f in ImageSequence.Iterator(im):\n'
                                        '            self.frames.append(cv2.cvtColor(np.array(f.convert("RGBA")), cv2.COLOR_RGBA2BGRA))\n'
                                        '            durs.append(max(20, f.info.get("duration", 100) or 100) / 1000)\n'
                                        '        self.ends = np.cumsum(durs); self.dur = float(self.ends[-1])\n'
                                        '        self.h, self.w = self.frames[0].shape[:2]; self.cache = OrderedDict()\n'
                                        '    def frame(self, t, ds=1.0):\n'
                                        '        i = min(int(np.searchsorted(self.ends, t % self.dur, side="right")), len(self.frames) - 1)\n'
                                        '        if ds >= 0.999: return self.frames[i]\n'
                                        '        key = (i, ds)\n'
                                        '        if key not in self.cache:\n'
                                        '            self.cache[key] = cv2.resize(self.frames[i], (max(1, int(self.w * ds)), max(1, int(self.h * ds))), '
                                        'interpolation=cv2.INTER_AREA)\n'
                                        '            while len(self.cache) > 120: self.cache.popitem(last=False)\n'
                                        '        return self.cache[key]\n'
                                        '\n'
                                        '\n'
                                        'class MediaPool:\n'
                                        '    def __init__(self, use_proxy=False): self.src = {}; self.make_compound = None; self.use_proxy = use_proxy; '
                                        'self._proxy_jobs = set()\n'
                                        '    MAX_OPEN = 16          # open video files at most (the oldest one is closed first): keeps a long project light\n'
                                        '    def _evict(self):\n'
                                        '        while len(self.src) >= self.MAX_OPEN:\n'
                                        '            s = self.src.pop(next(iter(self.src)))\n'
                                        '            try:\n'
                                        '                if hasattr(s, "close"): s.close()\n'
                                        '            except Exception: pass\n'
                                        '    def _video(self, p):\n'
                                        '        self._evict()\n'
                                        '        if not self.use_proxy: return VideoSource(p)\n'
                                        '        PROXY.pool = self; PROXY.want(p)\n'
                                        '        return VideoSource(p, use_proxy=True)\n'
                                        '    def prepare(self, clips, t=0.0):\n'
                                        '        """Queue the proxies of every video in the project; the ones nearest the playhead first."""\n'
                                        '        if not self.use_proxy: return\n'
                                        '        best = {}\n'
                                        '        for c in clips:\n'
                                        '            if c.get("kind") == "video" and c.get("path"):\n'
                                        '                s, e = c["start"], c["start"] + c["dur"]\n'
                                        '                d = 0.0 if s <= t <= e else min(abs(s - t), abs(e - t))\n'
                                        '                best[c["path"]] = min(best.get(c["path"], 1e18), d)\n'
                                        '        for p, d in best.items(): PROXY.want(p, d)\n'
                                        '    def reset(self):\n'
                                        '        """Cancel the proxy jobs, close every open file and forget the sources (call with the render lock held)."""\n'
                                        '        PROXY.reset()\n'
                                        '        for s in self.src.values():\n'
                                        '            try: s.close()\n'
                                        '            except Exception: pass\n'
                                        '        self.src.clear()\n'
                                        '    def get(self, c):\n'
                                        '        if c.get("kind") == "compound": return self.make_compound(c) if self.make_compound else None\n'
                                        '        p = c["path"]\n'
                                        '        if p not in self.src:\n'
                                        '            try:\n'
                                        '                k = c["kind"]\n'
                                        '                self.src[p] = self._video(p) if k == "video" else GifSource(p) if k == "gif" else ImageSource(p) if k '
                                        '== "image" else None\n'
                                        '            except Exception as ex:\n'
                                        '                print("media error:", ex); self.src[p] = None\n'
                                        '        return self.src[p]\n'
                                        '\n'
                                        '\n'
                                        'class AudioStore:\n'
                                        '    def __init__(self): self.data = {}; self.peaks = {}; self.lock = threading.Lock()\n'
                                        '    def load(self, path):\n'
                                        '        with self.lock:\n'
                                        '            if path in self.data: return self.data[path]\n'
                                        '            arr = None\n'
                                        '            try:\n'
                                        '                p = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-f", "s16le", "-ac", "2", "-ar", '
                                        'str(SR), "-"],\n'
                                        '                                   capture_output=True, creationflags=NOWIN)\n'
                                        '                a = np.frombuffer(p.stdout, np.int16)\n'
                                        '                if a.size >= 2: arr = a[: a.size // 2 * 2].reshape(-1, 2)\n'
                                        '            except Exception: pass\n'
                                        '            self.data[path] = arr\n'
                                        '            if arr is not None:\n'
                                        '                hop = SR // 100; n = len(arr) // hop\n'
                                        '                self.peaks[path] = (np.abs(arr[: n * hop]).max(axis=1).reshape(n, hop).max(axis=1) / '
                                        '32768.0).astype(np.float32)\n'
                                        '            else: self.peaks[path] = np.zeros(0, np.float32)\n'
                                        '            return arr\n'
                                        '\n'
                                        '\n'
                                        'AUDIO = AudioStore()\n'
                                        '\n'
                                        '\n'
                                        'def make_thumb(path, kind, t, h):\n'
                                        '    img = None\n'
                                        '    if kind == "video":\n'
                                        '        cap = cv2.VideoCapture(safe_path(path)); cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, img = cap.read()\n'
                                        '        if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, img = cap.read()\n'
                                        '        cap.release()\n'
                                        '        if not ok: return None\n'
                                        '    elif kind == "image": img = to_bgra(imread_any(path))\n'
                                        '    elif kind == "gif":\n'
                                        '        im = Image.open(path); im.seek(0); img = cv2.cvtColor(np.array(im.convert("RGBA")), cv2.COLOR_RGBA2BGRA)\n'
                                        '    if img is None: return None\n'
                                        '    ih, iw = img.shape[:2]\n'
                                        '    img = cv2.resize(img, (max(1, int(iw * h / ih)), h), interpolation=cv2.INTER_AREA)\n'
                                        '    return np_to_qimage(img)\n'
                                        '\n'
                                        '\n'
                                        'class _Job(QRunnable):\n'
                                        '    def __init__(self, fn, cb): super().__init__(); self.fn = fn; self.cb = cb\n'
                                        '    def run(self):\n'
                                        '        try: r = self.fn()\n'
                                        '        except Exception: r = None\n'
                                        '        self.cb(r)\n'
                                        '\n'
                                        '\n'
                                        'class ThumbStore(QObject):\n'
                                        '    updated = Signal()\n'
                                        '    def __init__(self):\n'
                                        '        super().__init__(); self.cache = OrderedDict(); self.pending = set()\n'
                                        '        self.pool = QThreadPool(); self.pool.setMaxThreadCount(2)\n'
                                        '    def _run(self, key, fn):\n'
                                        '        self.pending.add(key)\n'
                                        '        def cb(r, key=key):\n'
                                        '            self.cache[key] = r; self.pending.discard(key)\n'
                                        '            while len(self.cache) > 1500: self.cache.popitem(last=False)\n'
                                        '            self.updated.emit()\n'
                                        '        self.pool.start(_Job(fn, cb))\n'
                                        '    def thumb(self, path, kind, t, h):\n'
                                        '        key = ("t", path, round(t, 1), h)\n'
                                        '        if key in self.cache: return self.cache[key]\n'
                                        '        if key not in self.pending: self._run(key, lambda: make_thumb(path, kind, t, h))\n'
                                        '        return None\n'
                                        '    def wave(self, path):\n'
                                        '        if path in AUDIO.peaks: return AUDIO.peaks[path]\n'
                                        '        key = ("w", path)\n'
                                        '        if key not in self.pending and key not in self.cache: self._run(key, lambda: (AUDIO.load(path), None)[1])\n'
                                        '        return None\n',
                             'new': '6cc33e7eb7d5b2e28ffe37fdb32c45bca4181ea82149a80cf8003efbdcde49de'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "proxy_long_video_export"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_15_proxy_long_video_export.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_14_foundation_long_projects.py) first."); return 3
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
    say("To undo:  python apply_15_proxy_long_video_export.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

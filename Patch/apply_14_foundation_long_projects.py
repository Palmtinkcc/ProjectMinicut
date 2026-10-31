#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 14: FOUNDATION FOR LONG PROJECTS
=====================================================
Install AFTER apply_14_foundation_long_projects.py.

  * Progress ring, bottom right of the window: shows the background work that is running (proxy building, audio
    effects). A ring that fills up = how far it is; "3" = three jobs. Click it for the list.
  * Proxies: built by one background thread, the video nearest the playhead first (not in the order of the project).
  * Light memory use for long projects: at most 16 video files are open at once (the oldest is closed first), and
    the processed audio kept in memory is limited to about 1.5 GB.

New files: minicut/shared/tasks.py, minicut/workspace/progress_ring.py
Changed files: minicut/render/media.py, minicut/render/afx.py, minicut/workspace/timeline.py, minicut/app.py

    python apply_14_foundation_long_projects.py            install the update
    python apply_14_foundation_long_projects.py --check    only show what would change
    python apply_14_foundation_long_projects.py --revert   undo the last install
    python apply_14_foundation_long_projects.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': '445bf216e1bf02a670aaed47f239a7a33929df0106309a1825dd7cc23b606a9b',
                    'crlf': False,
                    'edits': [('from .render.recorder import *\n', 'from .render.recorder import *\nfrom .workspace.progress_ring import install_progress\n'),
                              ('win=MainWindow(); apply_ui(win); win.restore_layout(); win.show();',
                               'win=MainWindow(); apply_ui(win); win.restore_layout(); install_progress(win); win.show();')],
                    'new': '45adb8f7ede62240417f3df9e26bae1a2093c3fefd8ef429d3045a89c1a2d3a2'},
 'minicut/render/afx.py': {'base': 'ace4ca9e4becac9d544b4bac98f729d2865d23136ea295e020e5fcc78c23f480',
                           'crlf': False,
                           'edits': [('import threading\n', 'import threading\nfrom ..shared.tasks import TASKS\n'),
                                     ('AFX_CACHE = OrderedDict()',
                                      'AFX_BUDGET = 1.5e9   # bytes kept for processed audio (about 35 minutes of stereo)\nAFX_CACHE = OrderedDict()'),
                                     ('        AFX_CACHE[key] = y\n        while len(AFX_CACHE) > 4: AFX_CACHE.popitem(last=False)\n',
                                      '        AFX_CACHE[key] = y\n'
                                      '        while len(AFX_CACHE) > 1 and sum(v.nbytes for v in AFX_CACHE.values()) > AFX_BUDGET: '
                                      'AFX_CACHE.popitem(last=False)\n'),
                                     ('    def run(self):\n'
                                      '        try: _make(*self.a)\n'
                                      '        except Exception as ex:\n'
                                      '            print("audio effects:", ex)\n'
                                      '            with _LOCK: _PENDING.discard(self.a[2])\n',
                                      '    def run(self):\n'
                                      '        task = TASKS.start("audio", "Audio effects  " + os.path.basename(self.a[0]))\n'
                                      '        try: _make(*self.a)\n'
                                      '        except Exception as ex:\n'
                                      '            print("audio effects:", ex)\n'
                                      '            with _LOCK: _PENDING.discard(self.a[2])\n'
                                      '        finally: task.finish()\n')],
                           'new': 'eb88c7369312e163e2debc7d6877e8304f3af6eadbb35c240adff60080d4830e'},
 'minicut/workspace/timeline.py': {'base': 'c6af7e5b189e407316cffcf48efe1a59eaa0fb0b583ae6a5889df1c1becaad22',
                                   'crlf': False,
                                   'edits': [('        self.app.pool.prepare(P.clips)\n', '        self.app.pool.prepare(P.clips, self.app.t)\n')],
                                   'new': '127b78fd63d01c4b14b1bc91e1ce98f51e3bc1167e1eae1c220269f0dd098e15'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {'minicut/render/media.py': {'base': '54ed2ae9e7f29e675d3a175c26f4aa1f60976a15123effd099618e0ebbb4ea53',
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
                                        'def proxy_pieces(path):\n'
                                        '    """Numbers of the finished pieces. A piece is only renamed into place when it is complete."""\n'
                                        '    try:\n'
                                        '        d = proxy_dir(path)\n'
                                        '        return {int(f[1:6]) for f in os.listdir(d) if f.startswith("p") and f.endswith(".mp4") and ".tmp" not in f '
                                        'and f[1:6].isdigit()}\n'
                                        '    except Exception: return set()\n'
                                        '\n'
                                        '\n'
                                        'def video_duration(path):\n'
                                        '    cap = cv2.VideoCapture(safe_path(path)); fps = cap.get(cv2.CAP_PROP_FPS) or 30; n = '
                                        'cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0; cap.release()\n'
                                        '    return n / fps if n > 0 else 0.0\n'
                                        '\n'
                                        '\n'
                                        'from ..shared.tasks import TASKS\n'
                                        'import heapq, math, threading, time\n'
                                        '\n'
                                        '\n'
                                        'def make_proxy(path, d, alive, task=None):\n'
                                        '    """Build the pieces in order, so piece 0 (the start of the clip) is ready first. Finished pieces are kept.\n'
                                        '    alive() is False when the job was cancelled. Returns \'done\', \'failed\' or \'cancelled\'."""\n'
                                        '    dur = video_duration(path); k = 0\n'
                                        '    total = int(math.ceil(dur / PROXY_CHUNK)) if dur else None\n'
                                        '    if task is not None: task.total = total\n'
                                        '    while True:\n'
                                        '        if not alive(): return "cancelled"\n'
                                        '        if dur and k * PROXY_CHUNK >= dur - 1e-3: return "done"\n'
                                        '        dst = _piece_path(d, k)\n'
                                        '        if not os.path.exists(dst):\n'
                                        '            tmp = os.path.join(d, "p%05d.tmp.mp4" % k)\n'
                                        '            cmd = [FFMPEG, "-y", "-v", "error", "-ss", "%.3f" % (k * PROXY_CHUNK), "-i", path, "-t", "%.3f" % '
                                        'PROXY_CHUNK, "-an",\n'
                                        '                   "-vf", "scale=-2:min(%d\\\\,ih)" % int(CFG.get("proxy_height", PROXY_HEIGHT)),\n'
                                        '                   "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(CFG.get("proxy_quality", 23))), "-g", '
                                        '"1", "-pix_fmt", "yuv420p", tmp]\n'
                                        '            try:\n'
                                        '                r = subprocess.run(cmd, capture_output=True, timeout=PROXY_JOB_TIMEOUT,\n'
                                        '                                   creationflags=NOWIN | (0x00004000 if os.name == "nt" else 0))\n'
                                        '                ok = r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 200\n'
                                        '            except Exception as ex:\n'
                                        '                print("proxy error:", ex); ok = False\n'
                                        '            if not ok:\n'
                                        '                try: os.remove(tmp)\n'
                                        '                except OSError: pass\n'
                                        '                return "done" if k > 0 else "failed"\n'
                                        '            if not alive(): return "cancelled"\n'
                                        '            os.replace(tmp, dst)\n'
                                        '        k += 1\n'
                                        '        if task is not None: task.done = k; task.detail = "piece %d%s" % (k, (" of %d" % total) if total else "")\n'
                                        '\n'
                                        '\n'
                                        'class ProxyManager:\n'
                                        '    """Builds proxy pieces in one background thread. The video nearest the playhead is built first (priority).\n'
                                        '    reset() cancels everything (settings changed, cache cleared)."""\n'
                                        '    def __init__(self):\n'
                                        '        self.gen = 0; self.state = {}; self.lock = threading.Lock(); self.cv = threading.Condition(self.lock)\n'
                                        '        self.heap = []; self.seq = 0; self.thread = None\n'
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
                                        '            with self.lock:\n'
                                        '                if g == self.gen: self.state[d] = (status, time.monotonic())\n'
                                        '    def reset(self):\n'
                                        '        with self.lock: self.gen += 1; self.state.clear(); self.heap = []\n'
                                        '\n'
                                        '\n'
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
                                        '    """Frames of a video. A finished proxy piece covering the time is used when there is one; otherwise the\n'
                                        '    original file. Size, fps and length always come from the original file."""\n'
                                        '    KEEP_PIECES = 3\n'
                                        '    def __init__(self, path, use_proxy=False):\n'
                                        '        probe = open_capture(safe_path(path))\n'
                                        '        if not probe.isOpened(): raise IOError("cannot open " + path)\n'
                                        '        self.fps = probe.get(cv2.CAP_PROP_FPS) or 30\n'
                                        '        self.n = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)\n'
                                        '        self.w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))\n'
                                        '        self.orig = _Reader(probe)\n'
                                        '        self.dir = proxy_dir(path) if use_proxy else None\n'
                                        '        self.pieces = OrderedDict(); self.cache = OrderedDict()\n'
                                        '    def _piece(self, k):\n'
                                        '        f = _piece_path(self.dir, k)\n'
                                        '        if k in self.pieces:\n'
                                        '            if os.path.exists(f): self.pieces.move_to_end(k); return self.pieces[k]\n'
                                        '            # The file was deleted (cache cleared, or removed by hand): forget the reader, never show it again.\n'
                                        '            self.pieces.pop(k).release(); self.cache.clear(); return None\n'
                                        '        if not os.path.exists(f): return None\n'
                                        '        cap = cv2.VideoCapture(safe_path(f))\n'
                                        '        if not cap.isOpened(): return None\n'
                                        '        self.pieces[k] = _Reader(cap)\n'
                                        '        while len(self.pieces) > self.KEEP_PIECES: self.pieces.popitem(last=False)[1].release()\n'
                                        '        return self.pieces[k]\n'
                                        '    def frame(self, t, ds=1.0):\n'
                                        '        t = max(0.0, t)\n'
                                        '        idx = int(t * self.fps + 1e-6)\n'
                                        '        if self.n > 0: idx = max(0, min(self.n - 1, idx))\n'
                                        '        key = (idx, ds, self.dir is not None and os.path.exists(_piece_path(self.dir, int(t // PROXY_CHUNK))))\n'
                                        '        if key in self.cache: self.cache.move_to_end(key); return self.cache[key]\n'
                                        '        raw = None\n'
                                        '        if self.dir is not None:\n'
                                        '            k = int(t // PROXY_CHUNK); rd = self._piece(k)\n'
                                        '            if rd is not None: raw = rd.read(int((t - k * PROXY_CHUNK) * self.fps + 1e-6))\n'
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
                                        '        PROXY.want(p)\n'
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
                             'new': '1283f6e9fc816f03b85afa86afb4931a4c0182030024e53de47e756bed9137e0'}}

NEW_FILES = {'minicut/shared/tasks.py': '"""Background work in progress (proxies, audio effects, export...). The progress ring at the bottom right shows it."""\n'
                            'import threading, time\n'
                            '\n'
                            '\n'
                            'class Task:\n'
                            '    def __init__(self, center, kind, title):\n'
                            '        self.center = center; self.kind = kind; self.title = title\n'
                            '        self.total = None; self.done = 0; self.detail = ""; self.t0 = time.monotonic()\n'
                            '    def fraction(self):\n'
                            '        if not self.total: return None\n'
                            '        return max(0.0, min(1.0, self.done / float(self.total)))\n'
                            '    def finish(self):\n'
                            '        self.center._remove(self)\n'
                            '\n'
                            '\n'
                            'class TaskCenter:\n'
                            '    def __init__(self):\n'
                            '        self.lock = threading.Lock(); self.tasks = []\n'
                            '    def start(self, kind, title):\n'
                            '        t = Task(self, kind, title)\n'
                            '        with self.lock: self.tasks.append(t)\n'
                            '        return t\n'
                            '    def _remove(self, t):\n'
                            '        with self.lock:\n'
                            '            if t in self.tasks: self.tasks.remove(t)\n'
                            '    def snapshot(self):\n'
                            '        with self.lock: return list(self.tasks)\n'
                            '\n'
                            '\n'
                            'TASKS = TaskCenter()\n',
 'minicut/workspace/progress_ring.py': '"""Progress ring at the bottom right of the window: shows the background work that is running."""\n'
                                       'import time\n'
                                       'from ..shared.deps import *\n'
                                       'from ..shared.tasks import TASKS\n'
                                       'from PySide6.QtCore import QEvent\n'
                                       'from PySide6.QtWidgets import QMessageBox\n'
                                       '\n'
                                       '\n'
                                       'class ProgressRing(QWidget):\n'
                                       '    def __init__(self, parent):\n'
                                       '        super().__init__(parent); self.setFixedSize(46, 46); self.setCursor(Qt.PointingHandCursor)\n'
                                       '        self.shown = []; self.hide()\n'
                                       '        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self._poll); '
                                       'self.timer.start()\n'
                                       '    def _poll(self):\n'
                                       '        self.shown = TASKS.snapshot()\n'
                                       '        self.setVisible(bool(self.shown))\n'
                                       '        if self.shown:\n'
                                       '            lines = []\n'
                                       '            for t in self.shown:\n'
                                       '                f = t.fraction()\n'
                                       '                pct = ("%d%%" % round(f * 100)) if f is not None else "…"\n'
                                       '                lines.append("%s   %s%s" % (t.title, pct, ("   " + t.detail) if t.detail else ""))\n'
                                       '            self.setToolTip("\\n".join(lines)); self.update()\n'
                                       '    def paintEvent(self, e):\n'
                                       '        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)\n'
                                       '        r = QRectF(5, 5, 36, 36)\n'
                                       '        p.setPen(QPen(QColor("#2b2f38"), 4)); p.drawEllipse(r)\n'
                                       '        if not self.shown: return\n'
                                       '        t = self.shown[-1]; f = t.fraction()\n'
                                       '        p.setPen(QPen(QColor(UI["ui_accent"]), 4))\n'
                                       '        if f is None:\n'
                                       '            start = int((time.monotonic() * 360 * 1.2) % 360); p.drawArc(r, start * 16, -100 * 16)\n'
                                       '        else:\n'
                                       '            p.drawArc(r, 90 * 16, -int(f * 360 * 16))\n'
                                       '        p.setPen(QColor("#dfe3ea")); font = QFont(p.font()); font.setPointSize(max(7, font.pointSize() - 2)); '
                                       'p.setFont(font)\n'
                                       '        label = str(len(self.shown)) if len(self.shown) > 1 else ("%d" % round(f * 100) if f is not None else "…")\n'
                                       '        p.drawText(self.rect(), Qt.AlignCenter, label)\n'
                                       '    def mousePressEvent(self, e):\n'
                                       '        if e.button() == Qt.LeftButton and self.shown:\n'
                                       '            QMessageBox.information(self.window(), "MiniCut: working on", self.toolTip())\n'
                                       '\n'
                                       '\n'
                                       'class _Placer(QObject):\n'
                                       '    def __init__(self, ring):\n'
                                       '        super().__init__(); self.ring = ring\n'
                                       '    def place(self, main):\n'
                                       '        self.ring.move(main.width() - self.ring.width() - 16, main.height() - self.ring.height() - 16); '
                                       'self.ring.raise_()\n'
                                       '    def eventFilter(self, obj, ev):\n'
                                       '        if ev.type() == QEvent.Resize: self.place(obj)\n'
                                       '        return False\n'
                                       '\n'
                                       '\n'
                                       'def install_progress(main):\n'
                                       '    ring = ProgressRing(main); pl = _Placer(ring); main._progress_placer = pl\n'
                                       '    main.installEventFilter(pl); pl.place(main); return ring\n'}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "foundation_long_projects"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_14_foundation_long_projects.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_13_mask_layers_image.py) first."); return 3
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
    say("To undo:  python apply_14_foundation_long_projects.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 6: PROXY STABILITY AND PLAYBACK HOLD
=========================================================
Install AFTER apply_perf_gpu_patch_v6.py.

Proxy:
  * Every video of the project gets its proxy, even the clips the playhead has not reached yet.
    (Before, a proxy was only started when that clip was rendered, so some proxies were never made.)
  * Jobs have a time limit, a failed video is tried again after a short wait, and one stuck job no longer blocks
    the others.
  * Changing the proxy size / quality or clearing the cache cancels running jobs and closes the open proxy files.
    Files that are still in use are reported instead of being silently kept.
  * A proxy file that is deleted is never shown again (no more old frames from a removed proxy).

Playback:
  * When the picture is more than 0.4 s behind the clock (for example while a clip's proxy is not ready), the
    clock is held until the picture catches up. This avoids the stutter that used to continue until the playback
    was paused and started again.

Files changed (originals are backed up first):
  minicut/render/media.py, minicut/render/renderer.py, minicut/render/preview.py, minicut/app.py,
  minicut/workspace/timeline.py, minicut/shared/dialogs.py

    python apply_perf_gpu_patch_v6.py            install the update
    python apply_perf_gpu_patch_v6.py --check    only show what would change
    python apply_perf_gpu_patch_v6.py --revert   undo the last install
    python apply_perf_gpu_patch_v6.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/app.py': {'base': 'a1ec3ef181c97ffdbce71dacbec083bfddbbc31cabf428a4649c61e15c6b9632',
                    'crlf': False,
                    'edits': [("self.pool.use_proxy = self.settings['proxy_preview']; self.pool.src.clear()",
                               "self.pool.use_proxy = self.settings['proxy_preview']; self.pool.reset()")],
                    'new': 'b27cb5921181181e991392affbb2b65e59628c9649dba213c4b2270756e36840'},
 'minicut/render/preview.py': {'base': '1976a6f31a9d852974c599f2ba8bb1c15840aa7ce5c5bc10e3b67efaf60df7a1',
                               'crlf': False,
                               'edits': [('        if self.audio.running: self.t = self.audio.clock()\n'
                                          '        else: self.t += min(.1, now - self._last_tick)\n'
                                          '        self._last_tick = now\n',
                                          '        # Hold the clock while the picture is behind (e.g. a clip whose proxy is not ready yet): smooth, no '
                                          'skipping.\n'
                                          '        w = getattr(self, "_rworker", None); done = getattr(w, "done_t", None)\n'
                                          '        if self.playing and done is not None and self.t - done > 0.4:\n'
                                          '            if not getattr(self, "_stalled", False): self._stalled = True; self.audio.stop()\n'
                                          '            self._last_tick = now; self.request_render(); self.refresh_ui(); return\n'
                                          '        if getattr(self, "_stalled", False):\n'
                                          '            self._stalled = False; self.audio.start(self.proj, self.t, min(90, max(0.1, self.proj.duration() - '
                                          'self.t)))\n'
                                          '        if self.audio.running: self.t = self.audio.clock()\n'
                                          '        else: self.t += min(.1, now - self._last_tick)\n'
                                          '        self._last_tick = now\n')],
                               'new': 'bc5d4a2299e0c39baf47d773cda281fc587b20ff8751fb30a739ea3d0468b68a'},
 'minicut/render/renderer.py': {'base': 'fc232f1a426bc3bf8746fd157b67917e7d5c736b5de277b4c33c052cb00bb87a',
                                'crlf': False,
                                'edits': [('self.last_ms = 0.0\n', 'self.last_ms = 0.0; self.done_t = None\n'),
                                          ('self.last_ms = (time.perf_counter() - t0) * 1000.0',
                                           'self.last_ms = (time.perf_counter() - t0) * 1000.0; self.done_t = t')],
                                'new': '2935e77e32c1835c9ccac4b014c2bdec96cdb9f13dee1b57d36afbcb25f8a232'},
 'minicut/workspace/timeline.py': {'base': 'e881885af2ed0184ac0cb8c75641858723801f31f6988fcfbe73b5088513dfe2',
                                   'crlf': False,
                                   'edits': [('from ..render.media import proxy_pieces, PROXY_CHUNK\n',
                                              'from ..render.media import proxy_pieces, PROXY_CHUNK\n'),
                                             ('        new = {}\n        for c in P.clips:\n',
                                              '        self.app.pool.prepare(P.clips)\n        new = {}\n        for c in P.clips:\n')],
                                   'new': 'c6af7e5b189e407316cffcf48efe1a59eaa0fb0b583ae6a5889df1c1becaad22'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {'minicut/render/media.py': {'base': '07a0d8061dcbd3bf86570288e79c8d6dc222c873a6eb6cd82218a174f4aeeb11',
                             'content': '"""Media sources (video / image / gif), media pool, audio decode cache, thumbnails and waveforms."""\n'
                                        'from ..shared.deps import *\n'
                                        'from ..shared.core import *\n'
                                        '\n'
                                        '\n'
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
                                        'def make_proxy(path, d, alive):\n'
                                        '    """Build the pieces in order, so piece 0 (the start of the clip) is ready first. Finished pieces are kept.\n'
                                        '    alive() is False when the job was cancelled. Returns \'done\', \'failed\' or \'cancelled\'."""\n'
                                        '    dur = video_duration(path); k = 0\n'
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
                                        '                # After at least one piece, a failure means the end of the video was reached (unknown duration).\n'
                                        '                return "done" if k > 0 else "failed"\n'
                                        '            if not alive(): return "cancelled"\n'
                                        '            os.replace(tmp, dst)\n'
                                        '        k += 1\n'
                                        '\n'
                                        '\n'
                                        'class ProxyManager:\n'
                                        '    """Decides which videos get a proxy, runs the jobs one at a time in the background, and remembers the state.\n'
                                        '    reset() cancels everything (used when the settings change or the cache is cleared)."""\n'
                                        '    def __init__(self):\n'
                                        '        self.gen = 0; self.state = {}; self.lock = threading.Lock()\n'
                                        '        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)\n'
                                        '    def want(self, path):\n'
                                        '        d = proxy_dir(path)\n'
                                        '        with self.lock:\n'
                                        '            st = self.state.get(d)\n'
                                        '            if st is not None:\n'
                                        '                status, when = st\n'
                                        '                if status in ("queued", "running"): return\n'
                                        '                if status == "done" and proxy_pieces(path): return      # finished and still on disk\n'
                                        '                if time.monotonic() - when < PROXY_RETRY_AFTER: return\n'
                                        '            self.state[d] = ("queued", time.monotonic()); g = self.gen\n'
                                        '        self.pool.start(_ProxyJob(path, d, g))\n'
                                        '    def started(self, d, gen):\n'
                                        '        with self.lock:\n'
                                        '            if gen == self.gen: self.state[d] = ("running", time.monotonic())\n'
                                        '    def finished(self, d, gen, status):\n'
                                        '        with self.lock:\n'
                                        '            if gen == self.gen: self.state[d] = (status, time.monotonic())\n'
                                        '    def reset(self):\n'
                                        '        with self.lock: self.gen += 1; self.state.clear()\n'
                                        '\n'
                                        '\n'
                                        'PROXY = ProxyManager()\n'
                                        '\n'
                                        '\n'
                                        'class _ProxyJob(QRunnable):\n'
                                        '    def __init__(self, path, d, gen):\n'
                                        '        super().__init__(); self.path = path; self.d = d; self.gen = gen; self.setAutoDelete(True)\n'
                                        '    def run(self):\n'
                                        '        status = "failed"\n'
                                        '        try:\n'
                                        '            PROXY.started(self.d, self.gen)\n'
                                        '            status = make_proxy(self.path, self.d, lambda: self.gen == PROXY.gen)\n'
                                        '        except Exception as ex:\n'
                                        '            print("proxy error:", ex); status = "failed"\n'
                                        '        PROXY.finished(self.d, self.gen, status)\n'
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
                                        '    def _video(self, p):\n'
                                        '        if not self.use_proxy: return VideoSource(p)\n'
                                        '        PROXY.want(p)\n'
                                        '        return VideoSource(p, use_proxy=True)\n'
                                        '    def prepare(self, clips):\n'
                                        '        """Make sure every video in the project gets its proxy, not only the clips the playhead reached."""\n'
                                        '        if not self.use_proxy: return\n'
                                        '        for c in clips:\n'
                                        '            if c.get("kind") == "video" and c.get("path"): PROXY.want(c["path"])\n'
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
                             'new': '97531e54d046dbfad3e3b52274b19c5b21d63a0dde38d922edcb4f4646cebd6f'},
 'minicut/shared/dialogs.py': {'base': 'e640f36ba48eda7fe25f1a386c3e3bacfc12bef72607d2a9b368798489795c19',
                               'content': '"""Settings and Shortcuts dialogs."""\n'
                                          'from .deps import *\n'
                                          'from .theme import *\n'
                                          'from .core import *\n'
                                          'from .appearance import *\n'
                                          'from .widgets import *\n'
                                          'from .hwaccel import *\n'
                                          '\n'
                                          '\n'
                                          'class SettingsDialog(AnimatedDialog):\n'
                                          '    def __init__(self, app):\n'
                                          '        super().__init__(app, "Settings", 700); s = app.settings; self.app = app; self._snap = dict(UI); '
                                          'self._applied = False\n'
                                          '        tabs = QTabWidget(); self.body.addWidget(tabs)\n'
                                          '        gen = QWidget(); form = QFormLayout(gen)\n'
                                          '        self.asset = PathEdit(s["asset_folder"]); self.projf = PathEdit(s["project_folder"]); self.expf = '
                                          'PathEdit(s["export_folder"])\n'
                                          '        self.q = QComboBox(); [self.q.addItem(l, v) for l, v in QUALITIES]; self.q.setCurrentIndex(max(0, '
                                          'self.q.findData(s["preview_quality"])))\n'
                                          '        self.interp = QComboBox(); self.interp.addItems(["Smooth (bilinear)", "Fast (nearest)"]); '
                                          'self.interp.setCurrentIndex(1 if s["preview_interp"] == "fast" else 0)\n'
                                          '        self.reduce = QCheckBox("Halve preview resolution while playing"); '
                                          'self.reduce.setChecked(s["play_reduce"])\n'
                                          '        self.cache = QSpinBox(); self.cache.setRange(4, 600); self.cache.setValue(s["frame_cache"]); '
                                          'self.cache.setSuffix(" frames / video")\n'
                                          '        for lab, w in (("Asset folder", self.asset), ("Project folder", self.projf), ("Export folder", self.expf), '
                                          '("Viewport quality", self.q),\n'
                                          '                       ("Viewport filter", self.interp), ("", self.reduce), ("Frame cache", self.cache)): '
                                          'form.addRow(lab, w)\n'
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
                                          '        self.proxy_cb = QCheckBox("Smooth preview: use small background proxy copies (export always uses the '
                                          'original)"); self.proxy_cb.setChecked(bool(s["proxy_preview"]))\n'
                                          '        self.p_h = QComboBox(); [self.p_h.addItem("%dp" % v, v) for v in (360, 540, 720)]; '
                                          'self.p_h.setCurrentIndex(max(0, self.p_h.findData(int(s["proxy_height"]))))\n'
                                          '        self.p_q = QComboBox(); [self.p_q.addItem(l, v) for l, v in (("High quality (bigger files)", 18), '
                                          '("Normal", 23), ("Small files", 28))]; self.p_q.setCurrentIndex(max(0, '
                                          'self.p_q.findData(int(s["proxy_quality"]))))\n'
                                          '        self.p_size = QLabel(""); self.p_size.setObjectName("Dim"); self.p_size.setWordWrap(True)\n'
                                          '        pb = QPushButton("Clear proxy cache"); pb.setToolTip("Delete all proxy files. They are rebuilt when '
                                          'needed."); pb.clicked.connect(self.clear_proxies)\n'
                                          '        form.addRow("Export encoder", self.enc); form.addRow("", gb); form.addRow("", self.gpu_lbl); '
                                          'form.addRow("", self.proxy_cb)\n'
                                          '        form.addRow("Proxy size", self.p_h); form.addRow("Proxy quality", self.p_q); form.addRow("Proxy cache", '
                                          'self.p_size); form.addRow("", pb)\n'
                                          '        self.refresh_proxy_size()\n'
                                          '        tabs.addTab(gen, "General")\n'
                                          '        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); '
                                          'sc.setMinimumHeight(400)\n'
                                          '        host = QWidget(); host.setObjectName("SettingsHost"); '
                                          'host.setStyleSheet("QWidget#SettingsHost{background:transparent;}")\n'
                                          '        vl = QVBoxLayout(host); vl.setContentsMargins(4, 6, 12, 6); vl.setSpacing(6)\n'
                                          '        self.th_w = {}; grp = None; f2 = None\n'
                                          '        for k, (g, lab, kind, dflt, lo, hi) in THEME_DEFS.items():\n'
                                          '            if g != grp:\n'
                                          '                grp = g; h = QLabel(g); h.setObjectName("H2"); vl.addSpacing(6); vl.addWidget(h)\n'
                                          '                f2 = QFormLayout(); f2.setLabelAlignment(Qt.AlignLeft); vl.addLayout(f2)\n'
                                          '            if kind == "int": w = QSpinBox(); w.setRange(lo, hi)\n'
                                          '            elif kind == "float": w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(1); w.setSingleStep(0.5)\n'
                                          '            elif kind == "bool": w = QCheckBox()\n'
                                          '            else: w = ColorButton(UI[k])\n'
                                          '            self.th_w[k] = w; self._set(k, UI[k]); f2.addRow(lab, w)\n'
                                          '        vl.addStretch(); sc.setWidget(host); tabs.addTab(sc, "Appearance")\n'
                                          '        row = QHBoxLayout(); r = QPushButton("Reset appearance"); r.setToolTip("Put every size and color back to '
                                          'its default"); r.clicked.connect(self.reset_theme); row.addWidget(r); row.addStretch()\n'
                                          '        a = QPushButton("Apply"); a.clicked.connect(self.apply_theme); c = QPushButton("Cancel"); '
                                          'c.clicked.connect(self.reject)\n'
                                          '        ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)\n'
                                          '        for b in (a, c, ok): row.addWidget(b)\n'
                                          '        self.body.addLayout(row)\n'
                                          '    def _set(self, k, v):\n'
                                          '        w = self.th_w[k]; kind = THEME_DEFS[k][2]\n'
                                          '        if kind in ("int", "float"): w.setValue(v)\n'
                                          '        elif kind == "bool": w.setChecked(bool(v))\n'
                                          '        else: w.set(v)\n'
                                          '    def _collect(self):\n'
                                          '        for k, w in self.th_w.items():\n'
                                          '            kind = THEME_DEFS[k][2]\n'
                                          '            UI[k] = (w.value() if kind in ("int", "float") else w.isChecked() if kind == "bool" else w.c)\n'
                                          '    def reset_theme(self):\n'
                                          '        for k, v in THEME_DEFS.items(): self._set(k, v[3])\n'
                                          '    def apply_theme(self):\n'
                                          '        self._collect(); apply_ui(self.app); self._applied = True\n'
                                          '    def reject(self):\n'
                                          '        if self._applied: UI.update(self._snap); apply_ui(self.app)\n'
                                          '        super().reject()\n'
                                          '    def refresh_proxy_size(self):\n'
                                          '        d = os.path.join(APP_DIR, "proxies"); total = 0; n = 0\n'
                                          '        if os.path.isdir(d):\n'
                                          '            for root_, dirs, files in os.walk(d):\n'
                                          '                for f in files:\n'
                                          '                    try: total += os.path.getsize(os.path.join(root_, f)); n += 1\n'
                                          '                    except OSError: pass\n'
                                          '        self.p_size.setText("%d file(s), %.1f MB" % (n, total / 1048576.0))\n'
                                          '    def clear_proxies(self):\n'
                                          '        import shutil\n'
                                          '        d = os.path.join(APP_DIR, "proxies")\n'
                                          '        with self.app.renderer._src_lock: self.app.pool.reset()   # cancels jobs and closes the open proxy files\n'
                                          '        self.app.renderer.clear_preview_cache()\n'
                                          '        failed = 0\n'
                                          '        if os.path.isdir(d):\n'
                                          '            for f in os.listdir(d):\n'
                                          '                p = os.path.join(d, f)\n'
                                          '                try: shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)\n'
                                          '                except OSError: failed += 1\n'
                                          '        self.refresh_proxy_size()\n'
                                          '        if failed and getattr(self.app, "toast", None):\n'
                                          '            self.app.toast.show_msg("%d proxy file(s) are still in use and could not be deleted. Close MiniCut and '
                                          'delete: %s" % (failed, d))\n'
                                          '    def check_gpu(self):\n'
                                          '        self.gpu_lbl.setText("Testing ..."); QApplication.processEvents()\n'
                                          '        found = detect_gpu_encoders()\n'
                                          '        self.gpu_lbl.setText("GPU encoders that work: " + ", ".join(found) if found else "No GPU encoder works with '
                                          'this FFmpeg / driver. The CPU encoder will be used.")\n'
                                          '    def save(self):\n'
                                          '        s = self.app.settings\n'
                                          '        s["asset_folder"] = self.asset.text(); s["project_folder"] = self.projf.text() or s["project_folder"]; '
                                          's["export_folder"] = self.expf.text()\n'
                                          '        s["preview_quality"] = self.q.currentData(); s["preview_interp"] = "fast" if self.interp.currentIndex() == '
                                          '1 else "smooth"\n'
                                          '        s["play_reduce"] = self.reduce.isChecked(); s["frame_cache"] = self.cache.value(); CFG["frame_cache"] = '
                                          'self.cache.value()\n'
                                          '        s["preview_fps"] = int(self.fps.currentData()); s["adaptive_preview"] = self.adapt.isChecked(); '
                                          's["hw_decode"] = self.hwdec.isChecked(); s["encode_hw"] = self.enc.currentData(); s["proxy_preview"] = '
                                          'self.proxy_cb.isChecked(); s["proxy_height"] = int(self.p_h.currentData()); s["proxy_quality"] = '
                                          'int(self.p_q.currentData()); CFG["proxy_height"] = s["proxy_height"]; CFG["proxy_quality"] = s["proxy_quality"]\n'
                                          '        CFG["hw_decode"] = s["hw_decode"]; CFG["encode_hw"] = s["encode_hw"]; clear_gpu_cache()\n'
                                          '        os.makedirs(s["project_folder"], exist_ok=True); self._collect(); s.save(); apply_ui(self.app); '
                                          'self._applied = False; self.accept()\n'
                                          '\n'
                                          '\n'
                                          'class ShortcutDialog(AnimatedDialog):\n'
                                          '    def __init__(self, app):\n'
                                          '        super().__init__(app, "Keyboard shortcuts", 520); self.app = app; sc = app.settings["shortcuts"]\n'
                                          '        self.table = QTableWidget(len(DEFAULT_SHORTCUTS), 2); self.table.setHorizontalHeaderLabels(["Action", '
                                          '"Shortcut"])\n'
                                          '        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True)\n'
                                          '        self.table.setColumnWidth(0, 220); self.table.setMinimumHeight(420); self.edits = {}\n'
                                          '        for i, k in enumerate(DEFAULT_SHORTCUTS):\n'
                                          '            it = QTableWidgetItem(ACTION_LABELS[k]); it.setFlags(Qt.ItemIsEnabled); self.table.setItem(i, 0, it)\n'
                                          '            e = QKeySequenceEdit(QKeySequence(sc.get(k, ""))); self.edits[k] = e; self.table.setCellWidget(i, 1, '
                                          'e)\n'
                                          '        self.body.addWidget(self.table)\n'
                                          '        row = QHBoxLayout(); r = QPushButton("Reset defaults"); r.clicked.connect(self.reset); row.addWidget(r); '
                                          'row.addStretch()\n'
                                          '        c = QPushButton("Cancel"); c.clicked.connect(self.reject); ok = QPushButton("Save"); '
                                          'ok.setObjectName("Accent"); ok.clicked.connect(self.save)\n'
                                          '        row.addWidget(c); row.addWidget(ok); self.body.addLayout(row)\n'
                                          '    def reset(self):\n'
                                          '        for k, e in self.edits.items(): e.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[k]))\n'
                                          '    def save(self):\n'
                                          '        seqs = {k: e.keySequence().toString(QKeySequence.PortableText) for k, e in self.edits.items()}\n'
                                          '        used = [v for v in seqs.values() if v]\n'
                                          '        dup = {v for v in used if used.count(v) > 1}\n'
                                          '        if dup: ask(self, "Duplicate shortcut", "These shortcuts are used more than once: " + ", ".join(dup), '
                                          '("OK",)); return\n'
                                          '        self.app.settings["shortcuts"].update(seqs); self.app.settings.save(); self.app.apply_shortcuts(); '
                                          'self.accept()\n',
                               'new': '3d9ad92331b6c0a531f7290b8f0e52b6d9d35f4a52a8a6fd3c8aff26f511544b'}}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v6"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v6.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v5.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v6.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

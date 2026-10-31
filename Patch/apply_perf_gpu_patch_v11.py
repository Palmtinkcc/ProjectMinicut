#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 11: AUDIO EFFECTS
======================================
Install AFTER apply_perf_gpu_patch_v11.py.

Each audio or video clip has an audio effects list in the Audio tab of the inspector. Effects, in order:
  Echo (delay, feedback, mix) · Reverb (decay, pre-delay, mix) · Low-pass · High-pass · EQ 3-band (low, mid, high)
  · Pan. Switch an effect on/off with its tick box, remove it with the X, and set its values.

The effects are computed in the background for the whole audio file, and the result is kept in memory (like the
proxies). While it is not ready the clean audio plays; the preview then switches to the processed audio by itself.
The export always waits for it, so the file contains the effects. Changing the values makes a new result.

New files: minicut/render/afx.py, minicut/workspace/afx_panel.py
Changed files: minicut/render/audio.py, minicut/render/export.py, minicut/workspace/panels.py
(originals are backed up first)

    python apply_perf_gpu_patch_v11.py            install the update
    python apply_perf_gpu_patch_v11.py --check    only show what would change
    python apply_perf_gpu_patch_v11.py --revert   undo the last install
    python apply_perf_gpu_patch_v11.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/render/audio.py': {'base': 'ba4f1aa0041c8f1956ac52aa8f002f8067263630eb29e5477ccc81bdf1b7d9c3',
                             'crlf': False,
                             'edits': [('from .nodegraph import *\n', 'from .nodegraph import *\nfrom .afx import *\n'),
                                       ('def mix_audio(proj, t0, t1, sr=SR):', 'def mix_audio(proj, t0, t1, sr=SR, wait=False):'),
                                       ('        data = AUDIO.load(c["path"])\n        if data is None: continue\n',
                                        "        data = audio_data_for(c, wait)     # clean audio, or the audio with the clip's audio effects when it is "
                                        'ready\n'
                                        '        if data is None: continue\n')],
                             'new': 'c3af394db51b2ffc9debadbddc1d38bf51623ab7783f5c5638c2f249eef1842c'},
 'minicut/render/export.py': {'base': '93073bf25fbb58760d99f43b7069de42463554b67133bb936732a46115663a7f',
                              'crlf': False,
                              'edits': [('            data = mix_audio(proj, 0, max(dur, 0.01))',
                                         '            data = mix_audio(proj, 0, max(dur, 0.01), wait=True)   # the export waits for the effects')],
                              'new': 'd96bb970917b2d0b52939531df88a0d1408e0195e6b76a025ad4ed6e84410d37'},
 'minicut/workspace/panels.py': {'base': '4413ed33633e39df1566d61b619deec9263d2a53d04ecf744bcfb6093a8114bd',
                                 'crlf': False,
                                 'edits': [('from ..render.renderer import _mask_shape\n',
                                            'from ..render.renderer import _mask_shape\nfrom .afx_panel import AudioFxPanel\n'),
                                           ('f.addWidget(r); f.addStretch()\n        self.tabs.addTab(sa, "Audio")',
                                            'f.addWidget(r); self.afx_panel = AudioFxPanel(self.app); f.addWidget(self.afx_panel); f.addStretch()\n'
                                            '        self.tabs.addTab(sa, "Audio")'),
                                           ('        self.fx_panel.load(c, force=full)\n',
                                            '        self.fx_panel.load(c, force=full)\n        self.afx_panel.load(c, force=full)\n')],
                                 'new': '7227d6d61539c001c7057ec77f8568420102b87329d8e37b3a039441f136ceec'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {'minicut/render/afx.py': '"""Audio effects for clips: echo, reverb, low-pass, high-pass, 3-band EQ and pan.\n'
                          '\n'
                          'The effects are applied to the whole audio file of a clip and the result is kept in memory (like the proxies).\n'
                          'While it is being made, playback uses the clean audio; when it is ready the preview switches to it. The export\n'
                          'waits for it, so the export always contains the effects."""\n'
                          'from ..shared.deps import *\n'
                          'from ..shared.core import *\n'
                          'from .media import AUDIO\n'
                          'import threading\n'
                          '\n'
                          '\n'
                          'AFX_FX = OrderedDict([\n'
                          '    ("echo", {"title": "Echo", "params": [("delay", "Delay (ms)", 1, 2000, 350, 1), ("feedback", "Feedback %", 0, 95, 40, 1), '
                          '("mix", "Mix %", 0, 100, 35, 1)]}),\n'
                          '    ("reverb", {"title": "Reverb", "params": [("decay", "Decay (s)", 0.2, 6, 1.8, 0.1), ("predelay", "Pre-delay (ms)", 0, 150, 20, '
                          '1), ("mix", "Mix %", 0, 100, 25, 1)]}),\n'
                          '    ("lowpass", {"title": "Low-pass", "params": [("cutoff", "Cutoff (Hz)", 80, 20000, 8000, 10)]}),\n'
                          '    ("highpass", {"title": "High-pass", "params": [("cutoff", "Cutoff (Hz)", 20, 5000, 120, 5)]}),\n'
                          '    ("eq", {"title": "EQ (3-band)", "params": [("low", "Low (dB)", -12, 12, 0, .5), ("mid", "Mid (dB)", -12, 12, 0, .5), ("high", '
                          '"High (dB)", -12, 12, 0, .5)]}),\n'
                          '    ("pan", {"title": "Pan", "params": [("pan", "Pan  (L ← 0 → R)", -100, 100, 0, 1)]}),\n'
                          '])\n'
                          '\n'
                          '\n'
                          'def afx_defaults(type_):\n'
                          '    return {k: d for k, _, _, _, d, _ in AFX_FX[type_]["params"]}\n'
                          '\n'
                          '\n'
                          'def _params(e):\n'
                          '    p = afx_defaults(e["type"]); p.update(e.get("p") or {}); return p\n'
                          '\n'
                          '\n'
                          'def _conv(x, H, B, M):\n'
                          '    """Overlap-add FFT convolution. x: (N, 2) float32. H: (B//2+1, 1 or 2) spectrum of the kernel(s). Output length N."""\n'
                          '    N = len(x); L = B - M + 1; out = np.zeros((N, 2), np.float32)\n'
                          '    for s in range(0, N, L):\n'
                          '        Y = np.fft.irfft(np.fft.rfft(x[s:s + L], B, axis=0) * H, B, axis=0)\n'
                          '        e = min(N, s + B); out[s:e] += Y[:e - s].astype(np.float32)\n'
                          '    return out\n'
                          '\n'
                          '\n'
                          'def _zero_phase_kernel(G, M=2049):\n'
                          '    """Linear-phase FIR (length M) from a magnitude curve G sampled on the rfft grid of 4096 points."""\n'
                          '    h = np.fft.irfft(G, 4096); h = np.concatenate([h[-(M // 2):], h[:M // 2 + 1]])\n'
                          '    return (h * np.hanning(M)).astype(np.float32)\n'
                          '\n'
                          '\n'
                          'def _transition(f, x0, width=1.0):\n'
                          '    """0 below x0 and 1 above it, smooth over one octave (raised cosine)."""\n'
                          '    d = (np.log2(np.maximum(f, 1.0)) - np.log2(x0) + width) / (2 * width)\n'
                          '    return 0.5 - 0.5 * np.cos(np.pi * np.clip(d, 0.0, 1.0))\n'
                          '\n'
                          '\n'
                          'def _fir(x, h):\n'
                          '    M = len(h); B = 1 << int(np.ceil(np.log2(max(4 * M, 1 << 14))))\n'
                          '    H = np.fft.rfft(h, B)[:, None]\n'
                          '    return _conv(x, H, B, M)\n'
                          '\n'
                          '\n'
                          'def fx_lowpass(x, p, sr=SR):\n'
                          '    f = np.fft.rfftfreq(4096, 1 / sr); return _fir(x, _zero_phase_kernel(1.0 - _transition(f, float(p["cutoff"]), 0.5)))\n'
                          '\n'
                          '\n'
                          'def fx_highpass(x, p, sr=SR):\n'
                          '    f = np.fft.rfftfreq(4096, 1 / sr); return _fir(x, _zero_phase_kernel(_transition(f, float(p["cutoff"]), 0.5)))\n'
                          '\n'
                          '\n'
                          'def fx_eq(x, p, sr=SR):\n'
                          '    f = np.fft.rfftfreq(4096, 1 / sr)\n'
                          '    lo, mid, hi = (10 ** (float(p[k]) / 20) for k in ("low", "mid", "high"))\n'
                          '    s1 = _transition(f, 250.0); s2 = _transition(f, 4000.0)\n'
                          '    G = lo * (1 - s1) + mid * s1 * (1 - s2) + hi * s2\n'
                          '    return _fir(x, _zero_phase_kernel(G))\n'
                          '\n'
                          '\n'
                          'def fx_echo(x, p, sr=SR):\n'
                          '    d = int(round(float(p["delay"]) / 1000 * sr)); fb = float(p["feedback"]) / 100; mix = float(p["mix"]) / 100\n'
                          '    if d <= 0 or fb <= 0 or mix <= 0: return x\n'
                          '    taps = min(40, int(np.ceil(np.log(0.001) / np.log(fb))))       # each repeat is fb times the one before\n'
                          '    wet = np.zeros_like(x)\n'
                          '    for k in range(1, taps + 1):\n'
                          '        s = k * d\n'
                          '        if s >= len(x): break\n'
                          '        wet[s:] += (fb ** k) * x[:-s]\n'
                          '    return x + mix * wet\n'
                          '\n'
                          '\n'
                          'def fx_reverb(x, p, sr=SR):\n'
                          '    mix = float(p["mix"]) / 100; decay = max(0.2, float(p["decay"])); pre = int(float(p["predelay"]) / 1000 * sr)\n'
                          '    if mix <= 0: return x\n'
                          '    n = int(decay * sr); t = np.arange(n) / sr\n'
                          '    rng = np.random.default_rng(7)                                    # the same room every time\n'
                          '    ir = rng.standard_normal((n, 2)).astype(np.float32) * np.exp(-6.91 * t / decay)[:, None].astype(np.float32)\n'
                          '    ir = np.concatenate([np.zeros((pre, 2), np.float32), ir]); ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-9\n'
                          '    M = len(ir); B = 1 << int(np.ceil(np.log2(max(4 * M, 1 << 14))))\n'
                          '    wet = _conv(x, np.fft.rfft(ir, B, axis=0), B, M)\n'
                          '    scale = (np.sqrt(np.mean(x ** 2)) + 1e-9) / (np.sqrt(np.mean(wet ** 2)) + 1e-9)\n'
                          '    return (1 - mix) * x + mix * wet * min(scale, 4.0)\n'
                          '\n'
                          '\n'
                          'def fx_pan(x, p, sr=SR):\n'
                          '    v = float(p["pan"]) / 100\n'
                          '    out = x.copy(); out[:, 0] *= 1 - max(0.0, v); out[:, 1] *= 1 - max(0.0, -v); return out\n'
                          '\n'
                          '\n'
                          'AFX_FN = {"echo": fx_echo, "reverb": fx_reverb, "lowpass": fx_lowpass, "highpass": fx_highpass, "eq": fx_eq, "pan": fx_pan}\n'
                          '\n'
                          '\n'
                          'def active_chain(c):\n'
                          '    return [e for e in (c.get("afx") or []) if e.get("on", True) and e.get("type") in AFX_FN]\n'
                          '\n'
                          '\n'
                          'def apply_chain(x, chain):\n'
                          '    for e in chain:\n'
                          '        x = AFX_FN[e["type"]](x, _params(e))\n'
                          '    return x\n'
                          '\n'
                          '\n'
                          '# ---------- cache and background work ----------\n'
                          'AFX_CACHE = OrderedDict()          # (file, chain) -> processed audio, int16 stereo like the original files\n'
                          '_PENDING = set(); _LOCK = threading.Lock()\n'
                          'AFX_POOL = QThreadPool(); AFX_POOL.setMaxThreadCount(1)\n'
                          '\n'
                          '\n'
                          'def _key(path, chain):\n'
                          '    return (path, json.dumps([[e["type"], _params(e)] for e in chain], sort_keys=True))\n'
                          '\n'
                          '\n'
                          'def _make(path, chain, key):\n'
                          '    data = AUDIO.load(path)\n'
                          '    if data is None: return None\n'
                          '    x = np.asarray(data, np.float32) / 32768.0\n'
                          '    if x.ndim == 1: x = np.stack([x, x], 1)\n'
                          '    y = (np.clip(apply_chain(x, chain), -1, 1) * 32767).astype(np.int16)\n'
                          '    with _LOCK:\n'
                          '        AFX_CACHE[key] = y\n'
                          '        while len(AFX_CACHE) > 4: AFX_CACHE.popitem(last=False)\n'
                          '        _PENDING.discard(key)\n'
                          '    return y\n'
                          '\n'
                          '\n'
                          'class _AfxJob(QRunnable):\n'
                          '    def __init__(self, path, chain, key):\n'
                          '        super().__init__(); self.a = (path, chain, key); self.setAutoDelete(True)\n'
                          '    def run(self):\n'
                          '        try: _make(*self.a)\n'
                          '        except Exception as ex:\n'
                          '            print("audio effects:", ex)\n'
                          '            with _LOCK: _PENDING.discard(self.a[2])\n'
                          '\n'
                          '\n'
                          'def processed(path, chain, wait=False):\n'
                          '    """The file with the chain applied, or None while it is being made (the caller then uses the clean audio)."""\n'
                          '    key = _key(path, chain)\n'
                          '    with _LOCK:\n'
                          '        if key in AFX_CACHE: AFX_CACHE.move_to_end(key); return AFX_CACHE[key]\n'
                          '    if wait: return _make(path, chain, key)\n'
                          '    with _LOCK:\n'
                          '        if key not in _PENDING:\n'
                          '            _PENDING.add(key); AFX_POOL.start(_AfxJob(path, chain, key))\n'
                          '    return None\n'
                          '\n'
                          '\n'
                          'def audio_data_for(c, wait=False):\n'
                          '    """What the mixer should read for this clip: the processed audio when there is a chain and it is ready."""\n'
                          '    chain = active_chain(c)\n'
                          '    if chain:\n'
                          '        d = processed(c["path"], chain, wait)\n'
                          '        if d is not None: return d\n'
                          '    return AUDIO.load(c["path"])\n',
 'minicut/workspace/afx_panel.py': '"""Audio effects list in the Audio tab of the inspector: add, switch on/off, remove and set the values."""\n'
                                   'from ..shared.deps import *\n'
                                   'from ..shared.core import *\n'
                                   'from ..render.afx import AFX_FX, afx_defaults\n'
                                   '\n'
                                   '\n'
                                   'class AudioFxPanel(QWidget):\n'
                                   '    def __init__(self, app):\n'
                                   '        super().__init__(); self.app = app; self._sig = None; self._before = None\n'
                                   '        v = QVBoxLayout(self); v.setContentsMargins(0, 6, 0, 0); v.setSpacing(6)\n'
                                   '        head = QHBoxLayout(); lab = QLabel("Audio effects"); lab.setObjectName("H2"); head.addWidget(lab); '
                                   'head.addStretch()\n'
                                   '        self.add_box = QComboBox()\n'
                                   '        for k, spec in AFX_FX.items(): self.add_box.addItem(spec["title"], k)\n'
                                   '        add = QPushButton("+ Add"); add.clicked.connect(self.add_effect)\n'
                                   '        head.addWidget(self.add_box); head.addWidget(add); v.addLayout(head)\n'
                                   '        self.cards = QVBoxLayout(); self.cards.setSpacing(6); v.addLayout(self.cards)\n'
                                   '        self.empty = QLabel("No audio effects yet. Choose one above and press Add."); self.empty.setObjectName("Dim"); '
                                   'v.addWidget(self.empty)\n'
                                   '        self._done_t = QTimer(self); self._done_t.setSingleShot(True); self._done_t.setInterval(400); '
                                   'self._done_t.timeout.connect(self._finish)\n'
                                   '\n'
                                   '    def load(self, c, force=False):\n'
                                   '        sig = (c["id"] if c else None, json.dumps(c.get("afx", []) if c else [], sort_keys=True))\n'
                                   '        if sig == self._sig and not force: return\n'
                                   '        self._sig = sig; self._rebuild(c)\n'
                                   '\n'
                                   '    def _rebuild(self, c):\n'
                                   '        while self.cards.count():\n'
                                   '            w = self.cards.takeAt(0).widget()\n'
                                   '            if w: w.deleteLater()\n'
                                   '        ch = (c.get("afx") or []) if c else []\n'
                                   '        self.empty.setVisible(not ch and c is not None and c.get("kind") in ("video", "audio"))\n'
                                   '        for idx, e in enumerate(ch): self.cards.addWidget(self._card(e, idx))\n'
                                   '\n'
                                   '    def _card(self, e, idx):\n'
                                   '        spec = AFX_FX.get(e["type"], {"title": e["type"], "params": []})\n'
                                   '        box = QFrame(); box.setFrameShape(QFrame.StyledPanel); v = QVBoxLayout(box); v.setContentsMargins(8, 6, 8, 6); '
                                   'v.setSpacing(4)\n'
                                   '        top = QHBoxLayout(); on = QCheckBox(spec["title"]); on.setChecked(bool(e.get("on", True)))\n'
                                   '        on.toggled.connect(lambda val, idx=idx: self._structural(lambda ch: ch[idx].__setitem__("on", bool(val))))\n'
                                   '        rm = QToolButton(); rm.setText("✕"); rm.setToolTip("Remove this effect")\n'
                                   '        rm.clicked.connect(lambda *_, idx=idx: self._structural(lambda ch: ch.pop(idx)))\n'
                                   '        top.addWidget(on); top.addStretch(); top.addWidget(rm); v.addLayout(top)\n'
                                   '        for key, label, lo, hi, dflt, step in spec["params"]:\n'
                                   '            r = QHBoxLayout(); l = QLabel(label); l.setMinimumWidth(120); r.addWidget(l)\n'
                                   '            sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setSingleStep(step); sp.setDecimals(0 if step >= 1 else 1)\n'
                                   '            sp.setValue(float(e.get("p", {}).get(key, dflt)))\n'
                                   '            sp.valueChanged.connect(lambda val, idx=idx, key=key: self._edit(idx, key, val))\n'
                                   '            r.addWidget(sp, 1); v.addLayout(r)\n'
                                   '        return box\n'
                                   '\n'
                                   '    def _chain(self):\n'
                                   '        c = self.app.sel_clip()\n'
                                   '        return None if c is None else c.setdefault("afx", [])\n'
                                   '\n'
                                   '    def add_effect(self):\n'
                                   '        c = self.app.sel_clip()\n'
                                   '        if c is None: return\n'
                                   '        k = self.add_box.currentData()\n'
                                   '        self.app.checkpoint(); c.setdefault("afx", []).append({"id": new_id(), "type": k, "on": True, "p": '
                                   'afx_defaults(k)})\n'
                                   '        self.app.on_changed(insp=False); self.load(c, force=True)\n'
                                   '\n'
                                   '    def _structural(self, fn):\n'
                                   '        c = self.app.sel_clip()\n'
                                   '        if c is None: return\n'
                                   '        self.app.checkpoint(); fn(c.setdefault("afx", [])); self.app.on_changed(insp=False); self.load(c, force=True)\n'
                                   '\n'
                                   '    def _edit(self, idx, key, val):\n'
                                   '        c = self.app.sel_clip()\n'
                                   '        if c is None or idx >= len(c.get("afx") or []): return\n'
                                   '        if self._before is None: self._before = self.app.begin()\n'
                                   '        c["afx"][idx].setdefault("p", {})[key] = float(val); self._done_t.start()\n'
                                   '\n'
                                   '    def _finish(self):\n'
                                   '        if self._before is not None:\n'
                                   '            self.app.commit(self._before); self._before = None\n'
                                   '        self.app.on_changed(insp=False)\n'}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "perf_gpu_v11"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_perf_gpu_patch_v11.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v10.py) first."); return 3
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
    say("To undo:  python apply_perf_gpu_patch_v11.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

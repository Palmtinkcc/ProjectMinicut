#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut update patch 13: MASK LAYERS AND IMAGE MASK
===================================================
Install AFTER apply_13_mask_layers_image.py.

  * Mask layers: a clip can have several masks. The base mask is the one you already had; "+ Layer" adds another
    one. Each extra layer is added to the masks before it, cut out of them (Subtract) or only keeps the part that
    overlaps them (Intersect). Invert, feather and the sliders work per layer.
  * Image mask: a new shape "Image". Pick an image that is in the project; the mask is its transparency (alpha) or
    its brightness. The picture is resized to the clip frame, so it lines up with the clip. Invert and feather work
    as for the other shapes.

Files changed (originals are backed up first):
  minicut/render/renderer.py, minicut/workspace/panels.py

    python apply_13_mask_layers_image.py            install the update
    python apply_13_mask_layers_image.py --check    only show what would change
    python apply_13_mask_layers_image.py --revert   undo the last install
    python apply_13_mask_layers_image.py --force    install even if you edited one of these files yourself
"""
import datetime, hashlib, json, os, py_compile, shutil, subprocess, sys

# Text edits: rel path -> {"base", "new", "edits": [(old, new), ...], "crlf"}
EDITS = {'minicut/render/renderer.py': {'base': '2350cd9c1099cd50fe85285102a37ab8b380afd6b56efc0fc74cf0207d752613',
                                'crlf': False,
                                'edits': [('MASKS = ["None", "Split", "Filmstrip", "Circle", "Rect", "Heart", "Star", "Custom"]',
                                           'MASKS = ["None", "Split", "Filmstrip", "Circle", "Rect", "Heart", "Star", "Custom", "Image"]'),
                                          ('MASK_DEFAULT = {"cx": .5, "cy": .5, "w": .6, "h": .6, "rot": 0.0, "round": 0.0, "invert": False, "pts": []}',
                                           'MASK_DEFAULT = {"cx": .5, "cy": .5, "w": .6, "h": .6, "rot": 0.0, "round": 0.0, "invert": False, "pts": [], "img": '
                                           '"", "channel": "alpha"}'),
                                          ('def mask_alpha(shape, ms, iw, ih, feather):\n    if shape in ("Split", "Filmstrip"):\n',
                                           'def mask_alpha(shape, ms, iw, ih, feather):\n'
                                           '    if shape == "Image":\n'
                                           '        m = _image_mask(ms.get("img", ""), iw, ih, ms.get("channel", "alpha"))\n'
                                           '        if m is None: return None\n'
                                           '    elif shape in ("Split", "Filmstrip"):\n'),
                                          ('        sh = c.get("mask", "None")\n'
                                           '        if sh not in CUSTOM_MASKS or img is None or img.ndim != 3 or img.shape[2] != 4: return img\n'
                                           '        ms = dict(MASK_DEFAULT, **(c.get("mask_shape") or {})); ih, iw = img.shape[:2]; fe = c.get("mask_feather", '
                                           '0)\n'
                                           '        cache = self._mask_cache\n'
                                           '        key = (sh, json.dumps(ms, sort_keys=True), iw, ih, fe); m = cache.get(key)\n'
                                           '        if m is None:\n'
                                           '            m = mask_alpha(sh, ms, iw, ih, fe); cache[key] = m\n'
                                           '            while len(cache) > 24: cache.popitem(last=False)\n'
                                           '        if m is None: return img\n',
                                           '        if img is None or img.ndim != 3 or img.shape[2] != 4 or not clip_has_mask(c): return img\n'
                                           '        ih, iw = img.shape[:2]; cache = self._mask_cache\n'
                                           '        key = (json.dumps(layer_list(c), sort_keys=True, default=str), iw, ih); m = cache.get(key)\n'
                                           '        if m is None:\n'
                                           '            m = combined_mask(c, iw, ih)\n'
                                           '            if m is None: return img\n'
                                           '            cache[key] = m\n'
                                           '            while len(cache) > 24: cache.popitem(last=False)\n'),
                                          ('def mask_alpha(shape, ms, iw, ih, feather):\n',
                                           'IMG_MASK_CACHE = OrderedDict()\n'
                                           '\n'
                                           '\n'
                                           'def _image_mask(path, iw, ih, channel="alpha"):\n'
                                           '    """Mask from an image of the project: its alpha (transparency) or its brightness, resized to the clip '
                                           'frame."""\n'
                                           '    if not path or not os.path.isfile(path): return None\n'
                                           '    key = (path, os.path.getmtime(path))\n'
                                           '    img = IMG_MASK_CACHE.get(key)\n'
                                           '    if img is None:\n'
                                           '        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)\n'
                                           '        if img is None: return None\n'
                                           '        if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)\n'
                                           '        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)\n'
                                           '        if img.dtype != np.uint8: img = (img / 256).astype(np.uint8)\n'
                                           '        IMG_MASK_CACHE[key] = img\n'
                                           '        while len(IMG_MASK_CACHE) > 6: IMG_MASK_CACHE.popitem(last=False)\n'
                                           '    src = img[..., 3] if channel == "alpha" else cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY)\n'
                                           '    return cv2.resize(src, (max(1, int(iw)), max(1, int(ih))), interpolation=cv2.INTER_LINEAR)\n'
                                           '\n'
                                           '\n'
                                           'def layer_list(c):\n'
                                           '    """The base mask of the clip followed by its extra mask layers (each: mode add / subtract / intersect)."""\n'
                                           '    base = {"mode": "add", "mask": c.get("mask", "None"), "mask_shape": c.get("mask_shape") or {}, "mask_feather": '
                                           'c.get("mask_feather", 0)}\n'
                                           '    return [base] + [L for L in (c.get("mask_layers") or []) if isinstance(L, dict)]\n'
                                           '\n'
                                           '\n'
                                           'def clip_has_mask(c):\n'
                                           '    return any(L.get("mask", "None") in CUSTOM_MASKS for L in layer_list(c))\n'
                                           '\n'
                                           '\n'
                                           'def combined_mask(c, iw, ih):\n'
                                           '    """All layers combined into one 0..255 mask (None when there is nothing to show)."""\n'
                                           '    acc = None\n'
                                           '    for L in layer_list(c):\n'
                                           '        if L.get("mask", "None") not in CUSTOM_MASKS: continue\n'
                                           '        ms = dict(MASK_DEFAULT, **(L.get("mask_shape") or {}))\n'
                                           '        m = mask_alpha(L["mask"], ms, iw, ih, L.get("mask_feather", 0))\n'
                                           '        if m is None: continue\n'
                                           '        f = m.astype(np.float32) * (1.0 / 255); mode = L.get("mode", "add")\n'
                                           '        if acc is None:\n'
                                           '            if mode != "add": continue          # nothing to subtract from yet\n'
                                           '            acc = f\n'
                                           '        elif mode == "subtract": acc = acc * (1.0 - f)\n'
                                           '        elif mode == "intersect": acc = acc * f\n'
                                           '        else: acc = acc + f - acc * f\n'
                                           '    if acc is None: return None\n'
                                           '    return np.clip(acc * 255 + .5, 0, 255).astype(np.uint8)\n'
                                           '\n'
                                           '\n'
                                           'def mask_alpha(shape, ms, iw, ih, feather):\n')],
                                'new': '6e2fa445e7d529c0907dbeee48846000b0c8c0947431ed77293df10d121f229f'},
 'minicut/workspace/panels.py': {'base': '6c0efc8a984fe27258b8eaf97e4dc30f67c24621731e976c159544e4d695f751',
                                 'crlf': False,
                                 'edits': [('        grid = QGridLayout(); grid.setSpacing(6); self.btns = {}\n',
                                            '        self.layer = 0\n'
                                            '        lr = QHBoxLayout(); lr.setSpacing(6); lay_lab = QLabel("Layer")\n'
                                            '        self.layer_box = QComboBox(); self.layer_box.currentIndexChanged.connect(self._on_layer)\n'
                                            '        self.mode_box = QComboBox()\n'
                                            '        for t, d in (("Add", "add"), ("Subtract", "subtract"), ("Intersect", "intersect")): '
                                            'self.mode_box.addItem(t, d)\n'
                                            '        self.mode_box.currentIndexChanged.connect(self._on_mode)\n'
                                            '        add_lay = QPushButton("+ Layer"); add_lay.setToolTip("Add another mask to this clip: it can add to, cut '
                                            'out of or intersect the masks before it")\n'
                                            '        add_lay.clicked.connect(self.add_layer); self.del_lay = QPushButton("Remove layer"); '
                                            'self.del_lay.clicked.connect(self.remove_layer)\n'
                                            '        lr.addWidget(lay_lab); lr.addWidget(self.layer_box, 1); lr.addWidget(self.mode_box); '
                                            'lr.addWidget(add_lay); lr.addWidget(self.del_lay)\n'
                                            '        self.layer_row = QWidget(); self.layer_row.setLayout(lr); v.addWidget(self.layer_row)\n'
                                            '        grid = QGridLayout(); grid.setSpacing(6); self.btns = {}\n'),
                                           ('        v.addLayout(grid)\n        self.canvas = MaskCanvas(self); v.addWidget(self.canvas, 1)\n',
                                            '        v.addLayout(grid)\n'
                                            '        ir = QHBoxLayout(); ir.setSpacing(6); img_lab = QLabel("Image")\n'
                                            '        self.img_box = QComboBox(); self.img_box.currentIndexChanged.connect(self._on_img)\n'
                                            '        self.chan_box = QComboBox()\n'
                                            '        for t, d in (("Transparency (alpha)", "alpha"), ("Brightness", "luma")): self.chan_box.addItem(t, d)\n'
                                            '        self.chan_box.currentIndexChanged.connect(self._on_chan)\n'
                                            '        ir.addWidget(img_lab); ir.addWidget(self.img_box, 1); ir.addWidget(self.chan_box)\n'
                                            '        self.img_row = QWidget(); self.img_row.setLayout(ir); v.addWidget(self.img_row)\n'
                                            '        self.canvas = MaskCanvas(self); v.addWidget(self.canvas, 1)\n'),
                                           ('    def _h(self, c):\n'
                                            '        """The dict that holds the mask: the clip itself (Mask tab) or e.g. the parameters of one effect (area '
                                            'blur)."""\n'
                                            '        return c if (c is None or self.holder_fn is None) else self.holder_fn(c)\n',
                                            '    def _h(self, c):\n'
                                            '        """The dict that holds the mask: the clip itself, the selected extra layer of the clip, or e.g. the '
                                            'parameters of one effect (area blur)."""\n'
                                            '        if c is None: return None\n'
                                            '        if self.holder_fn is not None: return self.holder_fn(c)\n'
                                            '        if self.layer > 0 and self.layer - 1 < len(c.get("mask_layers") or []): return '
                                            'c["mask_layers"][self.layer - 1]\n'
                                            '        return c\n'),
                                           ('        if c and h is not None: self._sync_sliders(h); self._grab_bg(c)\n        self._update_ui(self.shape())\n',
                                            '        if c and h is not None: self._sync_sliders(h); self._grab_bg(c)\n'
                                            '        self._update_ui(self.shape())\n'
                                            '        self._refresh_layers(); self._refresh_images()\n'),
                                           ('    def set_shape(self, n):\n',
                                            '    def _refresh_layers(self):\n'
                                            '        c = self.app.sel_clip(); area = self.holder_fn is not None\n'
                                            '        self.layer_row.setVisible(not area and c is not None)\n'
                                            '        if area or c is None: return\n'
                                            '        n = 1 + len(c.get("mask_layers") or []); self.layer = min(self.layer, n - 1)\n'
                                            '        self.layer_box.blockSignals(True); self.layer_box.clear(); self.layer_box.addItem("Base layer")\n'
                                            '        for i in range(1, n): self.layer_box.addItem("Layer %d" % (i + 1))\n'
                                            '        self.layer_box.setCurrentIndex(self.layer); self.layer_box.blockSignals(False)\n'
                                            '        self.mode_box.blockSignals(True)\n'
                                            '        if self.layer > 0: self.mode_box.setCurrentIndex(max(0, '
                                            'self.mode_box.findData(c["mask_layers"][self.layer - 1].get("mode", "add"))))\n'
                                            '        self.mode_box.setEnabled(self.layer > 0); self.mode_box.blockSignals(False); '
                                            'self.del_lay.setEnabled(self.layer > 0)\n'
                                            '    def _on_layer(self, i):\n'
                                            '        if self.loading: return\n'
                                            '        self.layer = max(0, i); c = self.app.sel_clip()\n'
                                            '        if c: self.load(c, force=True)\n'
                                            '    def _on_mode(self, i):\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if self.loading or c is None or self.layer <= 0 or self.holder_fn is not None: return\n'
                                            '        self.app.checkpoint(); c["mask_layers"][self.layer - 1]["mode"] = self.mode_box.currentData()\n'
                                            '        self.app.on_changed(insp=False); self.canvas.update()\n'
                                            '    def add_layer(self):\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if c is None: return\n'
                                            '        self.app.checkpoint(); c.setdefault("mask_layers", []).append({"mode": "subtract", "mask": "Circle", '
                                            '"mask_shape": {}, "mask_feather": 0})\n'
                                            '        self.layer = len(c["mask_layers"]); self.app.on_changed(insp=False); self.load(c, force=True)\n'
                                            '    def remove_layer(self):\n'
                                            '        c = self.app.sel_clip()\n'
                                            '        if c is None or self.layer <= 0: return\n'
                                            '        self.app.checkpoint(); c["mask_layers"].pop(self.layer - 1); self.layer = max(0, self.layer - 1)\n'
                                            '        self.app.on_changed(insp=False); self.load(c, force=True)\n'
                                            '    def _refresh_images(self):\n'
                                            '        c = self.app.sel_clip(); sh = self.shape()\n'
                                            '        self.img_row.setVisible(sh == "Image" and c is not None)\n'
                                            '        if sh != "Image" or c is None: return\n'
                                            '        ms = _mask_shape(self._h(c))\n'
                                            '        self.img_box.blockSignals(True); self.img_box.clear(); self.img_box.addItem("choose an image…", "")\n'
                                            '        for p in (self.app.proj.media if self.app.proj else []):\n'
                                            '            if kind_of(p) == "image": self.img_box.addItem(os.path.basename(p), p)\n'
                                            '        self.img_box.setCurrentIndex(max(0, self.img_box.findData(ms.get("img", "")))); '
                                            'self.img_box.blockSignals(False)\n'
                                            '        self.chan_box.blockSignals(True); self.chan_box.setCurrentIndex(max(0, '
                                            'self.chan_box.findData(ms.get("channel", "alpha")))); self.chan_box.blockSignals(False)\n'
                                            '    def _on_img(self, i):\n'
                                            '        if self.loading: return\n'
                                            '        path = self.img_box.currentData() or ""\n'
                                            '        self.edit(lambda ms, c: ms.update(img=path))\n'
                                            '    def _on_chan(self, i):\n'
                                            '        if self.loading: return\n'
                                            '        ch = self.chan_box.currentData() or "alpha"\n'
                                            '        self.edit(lambda ms, c: ms.update(channel=ch))\n'
                                            '    def set_shape(self, n):\n')],
                                 'new': 'cb90d417fdae04e9322febc34de59807cb9837e97f77dcba6ecaa9f06f9b2a9f'}}

# Whole-file replacements: rel path -> {"base", "new", "content"}
REPLACE = {}

NEW_FILES = {}

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(HERE, "_patch_backup")
PATCH_NAME = "mask_layers_image"
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
        say("ERROR: minicut/app.py not found next to this script.\nPut apply_13_mask_layers_image.py in the MiniCut folder (next to file.py) and run it again."); return 2
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
            "\nInstall the previous update (apply_perf_gpu_patch_v12.py) first."); return 3
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
    say("To undo:  python apply_13_mask_layers_image.py --revert")
    return 0


if __name__ == "__main__":
    code = 1
    try: code = main()
    except Exception as ex: say("Unexpected error: %r" % (ex,))
    if os.name == "nt" and "--no-pause" not in sys.argv: os.system("pause")
    sys.exit(code)

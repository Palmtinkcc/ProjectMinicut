"""Bone2D sync tools (Patch 44), kept out of bone2d_ui.py:

  * CurveBox       the Motion curve editor of the main program (shared EaseEditor + PresetTile + the same preset list), small, at the
                   bottom right next to the key sheet. It edits the curve of the selected keyframes.
  * PullSoundDialog take the sound of a part of the main video / timeline into the animation (a guide sound to animate to).
  * SyncMixin      marks (the same code as the main timeline: shared/marks.py), Auto mark, Lock to beat, the guide sound and its playback.
"""
from ..shared.deps import *
from ..shared.core import *
from ..shared.ui import *
from ..shared.widgets import *
from ..shared import marks as MK
from ..shared import marks_ui as MKU
from ..render import bone2d as B
from ..render import rigaudio as RA
from .curve_panel import PresetTile, all_presets


# ───────────────────────── the small curve panel ─────────────────────────
class _CurveEdit(EaseEditor):
    released = Signal()
    def mouseReleaseEvent(self, e): super().mouseReleaseEvent(e); self.released.emit()


class CurveBox(QFrame):
    TILE_H = 62
    def __init__(self, page):
        super().__init__(); self.page = page; self._open = False; self._sel = 0; self.setObjectName("CurveBox"); self.setMinimumWidth(240); self.setMaximumWidth(520)
        self.setStyleSheet("QFrame#CurveBox{background:#202024;border:1px solid #2c2c33;border-radius:10px}")
        v = QVBoxLayout(self); v.setContentsMargins(8, 6, 8, 8); v.setSpacing(6)
        head = QHBoxLayout(); head.setSpacing(6); t = label("Motion curve", False, 12); head.addWidget(t); self.info = label("Select keys to edit their curve", True, 11); self.info.setWordWrap(False); head.addWidget(self.info, 1)
        head.addWidget(Btn("All keys", "layers", "ghost", "Copy this curve to every keyframe of this animation", self.apply_all, h=24)); head.addWidget(Btn("Save", "save", "ghost", "Keep this curve as a preset of your own (shared with the main program)", self.save_preset, h=24)); v.addLayout(head)
        self.ed = _CurveEdit(); self.ed.setMinimumHeight(92); self.ed.changed.connect(self._edited); self.ed.released.connect(self._released); v.addWidget(self.ed, 1)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame); self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.scroll.setFixedHeight(self.TILE_H + 14)
        self.row = QWidget(); self.rl = QHBoxLayout(self.row); self.rl.setContentsMargins(0, 0, 0, 0); self.rl.setSpacing(6); self.scroll.setWidget(self.row); v.addWidget(self.scroll); self.rebuild()
    def rebuild(self):
        while self.rl.count():
            w = self.rl.takeAt(0).widget()
            if w: w.deleteLater()
        cur = [round(float(x), 3) for x in self.ed.e]
        for name, curve in all_presets(self.page.app.settings).items():
            tile = PresetTile(name, curve, selected=[round(float(x), 3) for x in curve] == cur, h=self.TILE_H); tile.setFixedWidth(78); tile.clicked.connect(self.apply_preset); self.rl.addWidget(tile)
        self.rl.addStretch()
    def show_keys(self, sel):
        if sel: self.ed.set_e(list(sel[0][0].get("e", [0, 0, 1, 1]))); self.info.setText("%d key%s selected" % (len(sel), "" if len(sel) == 1 else "s"))
        else: self.info.setText("Select keys to edit their curve")
        self.rebuild()
    def _edited(self, e):
        self.page.curve_edit(list(e), new=not self._open); self._open = True
    def _released(self): self._open = False; self.rebuild()
    def apply_preset(self, curve): self.ed.set_e(curve); self.page.curve_edit(list(curve), new=True); self._open = False; self.rebuild()
    def apply_all(self): self.page.curve_all(list(self.ed.e))
    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save curve", "Name for this curve:"); name = (name or "").strip()
        if not ok or not name: return
        S = self.page.app.settings
        if not isinstance(S["curve_presets"], dict): S["curve_presets"] = {}
        S["curve_presets"][name] = [float(v) for v in self.ed.e]; S.save(); self.rebuild()


# ───────────────────────── pull the sound of the main video ─────────────────────────
class PullSoundDialog(AnimatedDialog):
    """Pick a part of the main project (one clip, or everything on the timeline) and take its sound into the animation."""
    def __init__(self, page):
        super().__init__(page.app, "Sound from the main video", 480); self.page = page; self.P = page.app.proj; P = self.P; a = page.doc.anim
        def row(txt, *ws, sec):
            r = QHBoxLayout(); r.setSpacing(8); l = label(txt, True, 12); l.setFixedWidth(120); r.addWidget(l)
            for i, w in enumerate(ws): r.addWidget(w, 1 if i == 0 else 0)
            sec.body.addLayout(r)
        sec = Section("Take the sound of", "sound"); self.clips = sorted([c for c in (P.clips if P else []) if c["kind"] in ("video", "audio", "compound")], key=lambda c: c["start"])
        items = [("Everything on the timeline (mix)", "")] + [("%s   %.2f – %.2f s" % (c["name"], c["start"], c["start"] + c["dur"]), c["id"]) for c in self.clips]
        self.src = Dropdown(items); sel = page.app.sel_clip() if P else None
        if sel is not None and any(c["id"] == sel["id"] for c in self.clips): self.src.setCurrentIndex(self.src.findData(sel["id"]))
        self.src.changed.connect(self._fill); row("Source", self.src, sec=sec)
        self.t0 = NumberField(0.0, 0, 36000, 2, " s", "", 0.05); self.ln = NumberField(float(a["dur"]), 0.1, 3600, 2, " s", "", 0.05)
        pb = Btn("Playhead", "flag", "soft", "Start at the playhead of the main timeline", self._playhead, h=28); row("From (main timeline)", self.t0, pb, sec=sec); row("Length", self.ln, sec=sec)
        self.off = NumberField(0.0, -60, 600, 2, " s", "", 0.05); row("Starts in animation at", self.off, sec=sec); self.body.addWidget(sec)
        self.fit = Toggle("Make the animation as long as this sound", True); self.body.addWidget(self.fit)
        self.hint = label("Pick the part you want to animate to. Only this part is copied; the main project is not changed.", True, 11); self.hint.setWordWrap(True); self.body.addWidget(self.hint)
        r = QHBoxLayout(); r.addStretch(); c = QPushButton("Cancel"); c.clicked.connect(self.reject); ok = QPushButton("Pull the sound"); ok.setObjectName("Accent"); ok.clicked.connect(self._go); r.addWidget(c); r.addWidget(ok); self.body.addLayout(r)
        self._fill()
    def _clip(self): cid = self.src.currentData(); return next((c for c in self.clips if c["id"] == cid), None)
    def _playhead(self): self.t0.setValue(self.page.app.t)
    def _fill(self, *_):
        c = self._clip()
        if c is not None: self.t0.setValue(c["start"]); self.ln.setValue(c["dur"])
        else: self.t0.setValue(self.page.app.t); self.ln.setValue(max(0.1, float(self.page.doc.anim["dur"])))
    def _go(self):
        pg = self.page; c = self._clip(); t0 = float(self.t0.value()); ln = float(self.ln.value())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try: data = RA.pull_from_project(self.P, t0, ln, [c] if c is not None else None, True)
        except Exception as ex:
            QApplication.restoreOverrideCursor(); pg.toast("Could not read that sound: %s" % ex); return
        QApplication.restoreOverrideCursor()
        if data is None or not len(data) or float(np.abs(data).max()) < 1e-4: pg.toast("There is no sound in that part"); return
        rig_abs = os.path.abspath(pg.path); folder = RA.audio_folder(pg.path); fname = new_id() + ".wav"; full = os.path.join(folder, fname)
        try: RA.write_wav(full, data)
        except Exception as ex: pg.toast("Could not save the sound: %s" % ex); return
        pg.doc.checkpoint(); a = pg.doc.anim; name = c["name"] if c is not None else "Timeline mix"
        a["audio"] = {"file": os.path.relpath(full, os.path.dirname(rig_abs)), "name": name, "src_t0": t0, "dur": float(len(data) / SR), "offset": float(self.off.value()), "gain": 100.0, "mute": False}
        if self.fit.on: a["dur"] = max(0.1, round(a["audio"]["offset"] + a["audio"]["dur"], 3))
        pg.doc.touch(); pg.refresh_anims(); pg.model_dirty(); pg.toast("Sound added: %s  (%.2f s)" % (name, a["audio"]["dur"])); self.accept()


# ───────────────────────── marks + sound of the Bone2D page ─────────────────────────
class SyncMixin:
    def build_sync_row(self, bot):
        """A second row under the animation bar: marks, Auto mark, Lock to beat and the guide sound."""
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(Btn("", "chevron_left", "ghost", "Previous mark (Alt+Left)", lambda: self.goto_mark(-1), h=28)); row.addWidget(Btn("Mark", "flag", "soft", "Add or remove a mark at the playhead (Shift+M). Marks pull keys and the playhead like a magnet (hold Alt to switch it off).", self.add_mark, h=28)); row.addWidget(Btn("", "chevron_right", "ghost", "Next mark (Alt+Right)", lambda: self.goto_mark(1), h=28))
        row.addWidget(Btn("Auto mark", "auto_fix_high", "soft", "Mark the beats or hits of the sound automatically, coloured by the sound", self.auto_mark, h=28))
        self.beat_btn = Btn("Beat lock", "link", "soft", "Lock to beat: new and moved marks snap to the beat", self.toggle_beat_lock, True, 28); row.addWidget(self.beat_btn)
        row.addWidget(Btn("Keys at marks", "keyframe", "soft", "Key the selected bone at every mark (so you can pose it on the beat)", self.key_at_marks, h=28)); row.addSpacing(10)
        self.snd_btn = Btn("Sound", "sound", "soft", "Take the sound of a part of the main video as a guide to animate to", self.sound_menu, h=28); row.addWidget(self.snd_btn)
        self.mute_btn = Btn("", "mute", "ghost", "Mute the guide sound", self.toggle_mute, True, 28); row.addWidget(self.mute_btn); self.snd_lbl = label("", True, 11); row.addWidget(self.snd_lbl); row.addStretch(); bot.body.addLayout(row)
    def build_sync_shortcuts(self, sc):
        sc("Shift+M", self.add_mark); sc("Alt+Left", lambda: self.goto_mark(-1)); sc("Alt+Right", lambda: self.goto_mark(1))
    def sync_ui(self):
        """Show the state of the current animation in the sync row (Beat lock, Mute, the name of the sound) and in the curve box."""
        a = self.doc.anim; au = RA.audio_of(a); m = self.marks()
        for b, v in ((self.beat_btn, bool(m.beat_grid["on"])), (self.mute_btn, bool(au and au.get("mute")))):
            b.blockSignals(True); b.setChecked(v); b.blockSignals(False)
        self.snd_lbl.setText(("♪ %s · %.1f s" % (au["name"], au["dur"])) if au else "no sound")
    # ---- marks
    def marks(self): return MK.DictMarks(self.doc.anim, self.rig["cfg"].get("fps", 30))
    def mark_hooks(self):
        return {"checkpoint": self.doc.checkpoint, "changed": self.model_dirty, "add": self.add_mark, "rename": self.rename_mark, "auto": self.auto_mark, "grid_toggle": self.toggle_beat_lock, "key_all": self.key_at_marks}
    def add_mark(self):
        self.doc.checkpoint(); MK.toggle_mark(self.marks(), self.t, self.rig["cfg"].get("fps", 30)); self.model_dirty()
    def rename_mark(self, t):
        m = self.marks(); k = "%.3f" % t; txt, ok = QInputDialog.getText(self, "Mark", "Name of this mark:", text=m.marker_names.get(k, ""))
        if not ok: return
        self.doc.checkpoint()
        if txt.strip(): m.marker_names[k] = txt.strip()
        else: m.marker_names.pop(k, None)
        self.model_dirty()
    def goto_mark(self, d):
        t = MK.neighbour(self.marks(), self.t, d, 0.5 / max(1, self.rig["cfg"].get("fps", 30)))
        if t is not None: self.goto(t)
    def toggle_beat_lock(self):
        self.doc.checkpoint(); m = self.marks(); m.beat_grid = dict(m.beat_grid, on=not m.beat_grid["on"]); self.sync_ui(); self.model_dirty()
        self.toast("Lock to beat: %s  (%.1f BPM)" % ("ON" if m.beat_grid["on"] else "off", m.beat_grid["bpm"]))
    def auto_mark(self):
        au = RA.audio_of(self.doc.anim)
        if au is None: self.toast("Take a sound from the main video first (Sound button)"); self.pull_sound(); return
        ld = RA.load(self.path, au)
        if ld is None: self.toast("The sound file is missing - pull the sound again"); return
        d = MKU.AutoMarkDialog(self.app, self.marks(), [("Sound of this animation", lambda: (ld[0], SR, au["offset"]))], self.rig["cfg"].get("fps", 30), t_range=(0.0, float(self.doc.anim["dur"])))
        if not d.exec() or not d.result_found: return
        self.doc.checkpoint(); m = self.marks(); MK.apply_found(m, d.result_found, d.replace); m.beat_grid = d.result_grid; self.sync_ui(); self.model_dirty(); self.toast("%d marks added" % len(d.result_found))
    def key_at_marks(self):
        k, o = self._sel_obj()
        if o is None or k != "bone": self.toast("Select a bone first"); return
        ms = [t for t in self.marks().markers if 0.0 <= t <= self.doc.anim["dur"]]
        if not ms: self.toast("There are no marks yet"); return
        if self.mode != "animate": self.set_mode("animate")
        self.doc.checkpoint()
        for t in ms:
            chv = B.bone_channels(self.doc.anim, o["id"], t)
            for ch in B.CHANNELS: self.doc.set_key(o["id"], ch, t, chv[ch])
        self.doc.touch(); self.model_dirty(); self.toast("%d keys added on the marks" % len(ms))
    def mark_menu(self, t, px_per_sec, global_pos):
        m = QMenu(self); MKU.build_mark_menu(m, self.marks(), t, px_per_sec, self.mark_hooks()); m.exec(global_pos)
    # ---- the curve of the selected keys
    def curve_edit(self, e, new=True):
        sel = self.sheet.sel_keys
        if not sel:
            if new: self.toast("Select keyframes in the sheet first")
            return
        if new: self.doc.checkpoint()
        for s in sel: s[0]["e"] = list(e)
        self.doc.touch(); self.model_dirty()
    def curve_all(self, e):
        self.doc.checkpoint(); n = 0; a = self.doc.anim
        for trs in (a["tracks"], a["ptracks"]):
            for tr in trs.values():
                for ks in tr.values():
                    for k in ks: k["e"] = list(e); n += 1
        self.doc.touch(); self.model_dirty(); self.toast("Curve copied to %d keys" % n)
    # ---- the guide sound
    def sound_menu(self):
        m = QMenu(self); au = RA.audio_of(self.doc.anim)
        m.addAction("Take sound from the main video..." if not au else "Take another sound from the main video...", self.pull_sound)
        if au:
            m.addAction("Start in the animation at... (%.2f s)" % au["offset"], lambda: self._sound_num("offset", "Start in the animation at (seconds):", -60, 600, 2))
            m.addAction("Volume... (%d%%)" % au["gain"], lambda: self._sound_num("gain", "Volume (%):", 0, 300, 0)); m.addSeparator(); m.addAction("Remove the sound", self.remove_sound)
        m.exec(self.snd_btn.mapToGlobal(self.snd_btn.rect().bottomLeft()))
    def pull_sound(self):
        if not self.app.proj: return
        if not any(c["kind"] in ("video", "audio", "compound") for c in self.app.proj.clips): self.toast("Put a video or an audio clip on the main timeline first"); return
        PullSoundDialog(self).exec(); self.sync_ui(); self.sheet.update()
    def _sound_num(self, key, text, lo, hi, dec):
        au = RA.audio_of(self.doc.anim)
        if not au: return
        v, ok = QInputDialog.getDouble(self, "Sound", text, float(au[key]), lo, hi, dec)
        if ok: self.doc.checkpoint(); au[key] = float(v); self.model_dirty(); self.sync_ui()
    def remove_sound(self): self.doc.checkpoint(); self.doc.anim.pop("audio", None); self.audio.stop(); self.sync_ui(); self.model_dirty()
    def toggle_mute(self):
        au = RA.audio_of(self.doc.anim)
        if not au: self.sync_ui(); return
        self.doc.checkpoint(); au["mute"] = not au.get("mute", False); self.sync_ui(); self.model_dirty()
        if self.playing: self.audio_start()
    def audio_start(self):
        """(Re)start the guide sound at the playhead (when playing, after a jump, at the loop)."""
        self.audio.stop(); au = RA.audio_of(self.doc.anim)
        if not au or au.get("mute"): return
        ld = RA.load(self.path, au)
        if ld is not None: self.audio.start(ld[0], self.t, au["offset"], au["gain"] / 100.0)
    def cleanup_audio(self):
        """Delete the wav files of the rig's sounds that no animation uses any more (after the last save)."""
        try:
            folder = RA.audio_folder(self.path)
            if not os.path.isdir(folder): return
            used = {os.path.normcase(os.path.abspath(RA.wav_path(self.path, a["audio"]))) for a in self.rig["anims"] if RA.audio_of(a)}
            for f in os.listdir(folder):
                full = os.path.join(folder, f)
                if f.lower().endswith(".wav") and os.path.normcase(os.path.abspath(full)) not in used: RA.forget(full); os.remove(full)
            if not os.listdir(folder): os.rmdir(folder)
        except Exception as ex: print("audio cleanup:", ex)

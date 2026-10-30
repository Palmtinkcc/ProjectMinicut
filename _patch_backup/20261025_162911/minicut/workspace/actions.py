"""Editing workspace: undo / redo, selection, add / split / delete / group / compound / trim and the editor layout."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.core import _sel_clips, _shift_keys
from ..shared.ui import *
from ..shared.widgets import *
from .timeline import *
from .panels import *


def _toast(msg): QToolTip.showText(QCursor.pos(), msg)


def editor_only(fn):
    """Editor shortcuts do nothing while the node page is open."""
    def wrapper(self, *a, **k):
        if self.in_nodes(): return
        return fn(self, *a, **k)
    wrapper.__name__ = fn.__name__; return wrapper


from .timeline_ops import close_gaps as close_gaps_in


class WorkspaceMixin:
    """Editing workspace: layout, undo / redo, selection and clip editing commands."""
    def _build_editor(self):
        QTimer.singleShot(0, self.restore_layout)   # the splitters exist once the editor is built
        old=self.editor.layout()
        if old: QWidget().setLayout(old)
        root=QVBoxLayout(self.editor); root.setContentsMargins(10,8,10,10); root.setSpacing(8)
        top=QHBoxLayout(); top.setSpacing(2); logo=QLabel('MiniCut'); logo.setObjectName('Logo'); top.addWidget(logo); top.addSpacing(8); self.projlabel=QLabel(self.proj.name); self.projlabel.setObjectName('ProjTitle'); top.addWidget(self.projlabel); top.addStretch()
        icon_map = [("Projects", "Back to the project list", self.show_home, "home"), ("Save", "Save the project (Ctrl+S)", self.save_project, "save"),
                    ("Tasks", "Exports and other work in the background", self.show_tasks, "tasks"), ("Shortcuts", "Keyboard shortcuts", self.open_shortcuts, "keyboard"), ("Settings", "Settings", self.open_settings, "settings")]
        for label,tip,cb,ico in icon_map: top.addWidget(Btn(label, ico, "ghost", tip, cb, h=32))
        top.addSpacing(8); top.addWidget(Btn("Export", "export", "accent", "Save the video to a file (Ctrl+E)", self.export_dialog, h=32))
        root.addLayout(top)
        # CapCut-inspired workspace: media / player / inspector above, timeline spans the full width below.
        workspace=SmoothSplitter(Qt.Horizontal); workspace.setChildrenCollapsible(False)
        self.media=MediaPanel(self); self.preview=PreviewPanel(self); self.inspector=Inspector(self)
        workspace.addWidget(self.media); workspace.addWidget(self.preview); workspace.addWidget(self.inspector)
        workspace.setSizes([300, 800, 350]); workspace.setStretchFactor(0, 0); workspace.setStretchFactor(1, 1); workspace.setStretchFactor(2, 0)
        self.timeline_panel=TimelinePanel(self)
        vertical=SmoothSplitter(Qt.Vertical); vertical.setChildrenCollapsible(False)
        vertical.addWidget(workspace); vertical.addWidget(self.timeline_panel)
        vertical.setSizes([560, 300]); vertical.setStretchFactor(0, 1); vertical.setStretchFactor(1, 0)
        root.addWidget(vertical,1)
        self.multi=set(); self.toast=Toast(self.editor); self.refresh_ui()
        try: self.preview.time.setStyleSheet("color:#22d3ee; font-family:Consolas; font-size:12px;")
        except Exception: pass
        if not getattr(self, "_extra_actions", False):      # extra editing shortcuts (group / compound / trim)
            self._extra_actions = True
            for seq, fn in (("Ctrl+G", self.group_sel), ("Ctrl+Shift+G", self.ungroup_sel), ("Alt+G", self.make_compound),
                            ("Alt+Shift+G", self.uncompound), ("Q", self.trim_left), ("W", self.trim_right)):
                act = QAction(self); act.setShortcut(QKeySequence(seq)); act.setShortcutContext(Qt.WindowShortcut); act.triggered.connect(fn); self.addAction(act)
        if hasattr(self, "nodes_page"): self.nodes_page.reload()
    def begin(self):return copy.deepcopy(self.proj.to_dict()) if self.proj else None
    def checkpoint(self,*args):
        if self.proj:
            state=self.begin()
            if not self._undo or self._undo[-1]!=state:self._undo.append(state)
            self._undo=self._undo[-100:]; self._redo.clear()
    def commit(self,before):
        if before is not None and self.proj and before!=self.proj.to_dict():
            self._undo.append(before); self._undo=self._undo[-100:]; self._redo.clear()
    def do_undo(self):
        if not self._undo or not self.proj:return
        self._redo.append(self.begin()); d=self._undo.pop(); self.proj=Project.from_dict(d); self.sel=None; self.on_changed()
    def do_redo(self):
        if not self._redo or not self.proj:return
        self._undo.append(self.begin()); d=self._redo.pop(); self.proj=Project.from_dict(d); self.sel=None; self.on_changed()
    def sel_clip(self):return next((c for c in self.proj.clips if c['id']==self.sel),None) if self.proj else None
    def select(self,cid):
        if cid and self._mprev is not None: self.exit_media_preview(clear_selection=True)
        if cid != self.sel: self.sel_keys = set()
        self.sel=cid; self.refresh_ui()
    def set_multi(self, ids, primary=None):
        """Select several clips at once (box selection). primary = clip shown in the inspector."""
        ids = set(ids); self.sel_keys = set()
        if not ids: self.sel = None; self.multi = set()
        else:
            if primary not in ids: primary = next((c["id"] for c in reversed(self.proj.clips) if c["id"] in ids), None)
            self.sel = primary; self.multi = ids
        self.refresh_ui()
    def delete_sel_keys(self):
        c = self.sel_clip(); keys = getattr(self, "sel_keys", set())
        if not (c and keys and getattr(self, "sel_keys_clip", None) == c["id"]): return False
        self.checkpoint()
        for name, pr in c["props"].items():
            for k in [k for k in pr["k"] if round(k["t"], 3) in keys]: remove_key(c, name, k)
        self.sel_keys = set(); self.on_changed(); return True
    def on_changed(self,insp=True):
        if not self.proj:return
        if hasattr(self,'nodes_page') and self.nodes_page._pid!=id(self.proj): self.nodes_page.reload()   # undo / redo / load replaced the project
        self.renderer.clear_preview_cache()
        if hasattr(self,'projlabel'):self.projlabel.setText(self.proj.name)
        if hasattr(self,'timeline'):self.timeline.update();self.timeline.update_scroll()
        if hasattr(self,'media'):self.media.reload()
        if insp and hasattr(self,'inspector'):self.inspector.refresh(full=True)
        self.request_render(); self.refresh_ui()
    def refresh_ui(self):
        if not self.proj: return
        if getattr(getattr(self, "inspector", None), "mask_panel", None) is not None: self.inspector.mask_panel.follow(self.t)
        if hasattr(self, "timeline"): self.timeline.update(); self.timeline.update_scroll()
        if hasattr(self, "preview"):
            mp = getattr(self, "_mprev", None)
            if mp is not None: self.preview.time.setText(fmt_time(mp["t"], mp["fps"]) + " / " + fmt_time(mp["dur"], mp["fps"]))
            else: self.preview.time.setText(fmt_time(self.t, self.proj.fps) + " / " + fmt_time(self.proj.duration(), self.proj.fps))
            want = "pause" if ((mp["playing"] if mp is not None else self.playing)) else "play"
            if getattr(self, "_play_icon", None) != want: self.preview.play_btn.setIcon(app_icon(want)); self._play_icon = want
        now = time.monotonic(); busy = self.playing or bool(getattr(getattr(self, "timeline", None), "drag", None))
        if hasattr(self, "inspector") and (not busy or now - getattr(self, "_insp_t", 0) > .12):
            self._insp_t = now; self.inspector.refresh()
        if hasattr(self, "timeline_panel"):
            tp = self.timeline_panel; tp.snap_btn.setChecked(self.snap_on); tp._lock = True
            tp.zoom.setValue(max(0, min(1000, int(math.log(max(1, self.timeline.pps / 2), 1000) * 1000)))); tp._lock = False
    def sync_zoom_slider(self):self.refresh_ui()
    def toggle_snap(self):self.snap_on=not self.snap_on; self.settings['snap']=self.snap_on; self.settings.save(); self.refresh_ui()
    def import_dialog(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Import media',self.settings['asset_folder'],'Media files (*'+ ' *'.join(sorted(VIDEO_EXT|IMAGE_EXT|GIF_EXT|AUDIO_EXT))+');;All files (*)')
        if paths:self.import_files(paths)
    def import_files(self,paths):self.add_files(paths,self.t,None,only_import=True)
    def add_files(self,paths,start=None,track=None,only_import=False):
        if not self.proj:return
        if not only_import and self._mprev is not None: self.exit_media_preview(clear_selection=True)
        self.checkpoint(); start=self.t if start is None else max(0,float(start)); added=[]
        for path in paths:
            path=os.path.abspath(path); k=kind_of(path)
            if not k or not os.path.isfile(path):continue
            kind,dur=probe(path)
            if not kind:continue
            if path not in self.proj.media:self.proj.media.append(path)
            if only_import:continue
            want='audio' if kind=='audio' else 'video'; tr=self.proj.track(track) if track else None
            if not tr or tr['kind']!=want or tr.get('locked'):
                tr=next((x for x in self.proj.tracks if x['kind']==want and not x.get('locked') and self.track_free(x['id'],start,start+dur)),None)
            # Never put a newly inserted clip over another clip on the same lane.
            if tr and not self.track_free(tr['id'],start,start+dur): tr=None
            if not tr:
                insert_at = self.proj.track_index(track) if track and self.proj.track(track) else None
                tr=self.proj.add_track(want, insert_at)
            c=make_clip(kind,path,tr['id'],start,dur,dur); self.proj.clips.append(c); added.append(c)
        if added:self.sel=added[-1]['id']
        if hasattr(self,'media'):self.media.reload()
        self.on_changed()
    @editor_only
    def add_text(self):
        if not self.proj:return
        self.checkpoint(); tr=next((x for x in self.proj.tracks if x['kind']=='video' and not x['locked']),None)
        if not tr:tr=self.proj.add_track('video')
        c=make_clip('text','',tr['id'],self.t,5); c['name']='Text'; self.proj.clips.append(c); self.sel=c['id']; self.on_changed()
    def add_track(self,kind):self.checkpoint(); tr=self.proj.add_track(kind); self.on_changed(); return tr
    def track_free(self,tid,a,b,exclude=None):
        return not any(c['track']==tid and c['id']!=exclude and c['start']<b and c['start']+c['dur']>a for c in self.proj.clips)
    @editor_only
    def split(self):
        c=self.sel_clip()
        if not c or not c['start']+1e-4<self.t<c['start']+c['dur']-1e-4:return
        self.checkpoint(); cut=self.t-c['start']; right=copy.deepcopy(c); right['id']=new_id(); right['start']=self.t; right['inp']+=cut; right['dur']-=cut; c['dur']=cut
        for prop in c['props'].values():prop['k']=[k for k in prop['k'] if k['t']<=cut]
        for prop in right['props'].values():prop['k']=[dict(k,t=k['t']-cut) for k in prop['k'] if k['t']>=cut]
        self.proj.clips.append(right); self.sel=right['id']; self.on_changed()
    def delete_sel(self):
        if self.in_nodes(): self.nodes_page.delete_selected(); return
        if self.delete_sel_keys(): return
        cs = _sel_clips(self)
        if len(cs) > 1:      # several clips selected (Ctrl+click or box selection)
            ids = {c["id"] for c in cs}; self.checkpoint()
            self.proj.clips = [x for x in self.proj.clips if x["id"] not in ids]; self.sel = None; self.multi = set(); self.on_changed(); return
        c=self.sel_clip()
        if c:self.checkpoint(); self.proj.clips=[x for x in self.proj.clips if x['id']!=c['id']]; self.sel=None; self.on_changed()
    def place_free(self, c, want_track=None):
        """Put clip c on a track where it does not cover another clip: its own track when that is free at that time,
        else the nearest free track of the same kind, else a NEW track (above a video track, below an audio track)."""
        kind = "audio" if c["kind"] == "audio" else "video"; a, b = c["start"], c["start"] + c["dur"]
        tid = want_track or c["track"]; tr = self.proj.track(tid)
        if tr is not None and (tr["kind"] != kind or tr.get("locked")): tr = None
        if tr is not None and self.track_free(tr["id"], a, b, c.get("id")): c["track"] = tr["id"]; return c
        ref = self.proj.track_index(tid) if self.proj.track(tid) else 0
        free = [x for x in self.proj.tracks if x["kind"] == kind and not x.get("locked") and self.track_free(x["id"], a, b, c.get("id"))]
        if free: c["track"] = min(free, key=lambda x: abs(self.proj.track_index(x["id"]) - ref))["id"]; return c
        idx = self.proj.track_index(tid) if self.proj.track(tid) else None
        new = self.proj.add_track(kind, idx if kind == "video" else (idx + 1 if idx is not None else None)); c["track"] = new["id"]; return c
    def duplicate(self):
        if self.in_nodes(): self.nodes_page.scene.duplicate_selected(); return
        c=self.sel_clip()
        if c:
            self.checkpoint(); n=copy.deepcopy(c); n['id']=new_id(); n['start']+=n['dur']; n.pop('group',None); self.place_free(n, c['track']); self.proj.clips.append(n); self.sel=n['id']; self.multi=set(); self.on_changed()
    @editor_only
    def copy_clip(self):
        c=self.sel_clip()
        if c:self._clip_copy=copy.deepcopy(c)
    @editor_only
    def paste_clip(self):
        if self._clip_copy and self.proj:
            self.checkpoint(); c=copy.deepcopy(self._clip_copy); c['id']=new_id(); c['start']=self.t; c.pop('group',None)
            self.place_free(c, self._clip_copy.get('track')); self.proj.clips.append(c); self.sel=c['id']; self.multi=set(); self.on_changed()
    def replace_media(self):
        c=self.sel_clip()
        if not c or c.get("kind") == "text": return
        filters='Media files ('+' '.join('*'+e for e in sorted(VIDEO_EXT|IMAGE_EXT|GIF_EXT|AUDIO_EXT))+')'
        path,_=QFileDialog.getOpenFileName(self,'Replace media',os.path.dirname(c.get('path','')) or self.settings['asset_folder'],filters+';;All files (*)')
        if not path:return
        k,dur=probe(path)
        if not k:return
        if (k=='audio') != (c.get('kind')=='audio'):
            QMessageBox.information(self,'Replace media','Please choose media of the same track type (visual or audio).'); return
        self.checkpoint(); old_path=c.get('path',''); c['path']=os.path.abspath(path); c['name']=os.path.basename(path); c['src_dur']=dur
        if k in ('video','audio') and c.get('inp',0)+c.get('dur',0)>dur: c['dur']=max(1/max(1,self.proj.fps),dur-c.get('inp',0))
        if path not in self.proj.media:self.proj.media.append(os.path.abspath(path))
        self.pool.src.pop(old_path,None); self.renderer.clear_preview_cache(); self.on_changed()
    def _extract_compound_audio(self, c):
        """Mix everything inside a compound clip (nested compounds, muted sub-tracks and volumes included) to one wav
        file and put it on an audio track under the compound, like extracting the audio of a video."""
        from ..shared.tasks import TASKS
        from ..render.audio import mix_audio
        folder=os.path.join(APP_DIR,'extracted_audio'); os.makedirs(folder,exist_ok=True)
        out=os.path.join(folder, safe_name(c.get('name') or 'Compound')+'_'+c['id']+'_audio.wav')
        shim=copy.copy(self.proj); shim.clips=[copy.deepcopy(c)]; t0=c['start']; t1=c['start']+c['dur']; step=10.0
        task=TASKS.start('audio','Extract audio  '+(c.get('name') or 'Compound')); task.total=max(1,int(math.ceil((t1-t0)/step))); task.cancel_fn=lambda: None
        QApplication.setOverrideCursor(Qt.WaitCursor); peak=0.0; ok=False
        try:
            with wave.open(out,'wb') as wf:
                wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR); t=t0
                while t<t1-1e-9:
                    if getattr(task,'cancelled',False): raise RuntimeError('cancelled')
                    e=min(t1,t+step); d=mix_audio(shim,t,e,wait=True)
                    if d.size: peak=max(peak,float(np.abs(d).max()))
                    wf.writeframes((np.clip(d,-1,1)*32767).astype('<i2').tobytes()); t=e; task.done+=1; QApplication.processEvents()
            ok=True
        except Exception as ex:
            if str(ex)!='cancelled': QMessageBox.warning(self,'Extract audio failed',str(ex))
        finally:
            QApplication.restoreOverrideCursor(); task.finish()
        if not ok or getattr(task,'cancelled',False):
            try: os.remove(out)
            except OSError: pass
            return
        if peak<=1e-4:
            try: os.remove(out)
            except OSError: pass
            _toast('ไม่มีเสียงใน Compound clip นี้'); return
        dur=ffprobe_dur(out) or c['dur']
        self.checkpoint(); tr=next((x for x in self.proj.tracks if x['kind']=='audio' and not x.get('locked') and self.track_free(x['id'],c['start'],c['start']+c['dur'])),None)
        if not tr:tr=self.proj.add_track('audio')
        ac=make_clip('audio',out,tr['id'],c['start'],min(c['dur'],dur),dur); ac['name']=os.path.basename(out)
        self.proj.clips.append(ac); self.proj.media.append(out) if out not in self.proj.media else None
        self.sel=ac['id']; self.multi=set(); self.on_changed()
    def extract_audio(self):
        c=self.sel_clip()
        if c and c.get('kind')=='compound': return self._extract_compound_audio(c)
        if not c or c.get('kind')!='video' or not c.get('path'):return
        folder=os.path.join(APP_DIR,'extracted_audio'); os.makedirs(folder,exist_ok=True)
        out=os.path.join(folder, safe_name(os.path.splitext(os.path.basename(c['path']))[0]+'_audio')+'.wav')
        if not os.path.isfile(out):
            try:
                proc=subprocess.run([FFMPEG,'-y','-v','error','-i',c['path'],'-vn','-ac','2','-ar',str(SR),out],capture_output=True,creationflags=NOWIN)
                if proc.returncode!=0: raise RuntimeError(proc.stderr.decode('utf-8','ignore') if isinstance(proc.stderr,bytes) else str(proc.stderr))
            except Exception as ex:
                QMessageBox.warning(self,'Extract audio failed',str(ex)); return
        self.checkpoint(); tr=next((x for x in self.proj.tracks if x['kind']=='audio' and not x.get('locked') and self.track_free(x['id'],c['start'],c['start']+c['dur'])),None)
        if not tr:tr=self.proj.add_track('audio')
        ac=make_clip('audio',out,tr['id'],c['start'],min(c['dur'],ffprobe_dur(out) or c['dur']),ffprobe_dur(out) or c['dur'])
        ac['inp']=c.get('inp',0); ac['name']=os.path.basename(out); self.proj.clips.append(ac); self.proj.media.append(out) if out not in self.proj.media else None
        self.sel=ac['id']; self.on_changed()
    def key_all(self):
        c=self.sel_clip()
        if not c:return
        self.checkpoint(); lt=self.t-c['start']
        for k in ('x','y','sx','sy','rot','opacity','volume'):add_key(c,k,lt)
        self.on_changed()
    def rename_track(self,tr):
        name,ok=QInputDialog.getText(self,'Rename track','Track name:',text=tr['name'])
        if ok and name.strip():self.checkpoint();tr['name']=name.strip();self.on_changed()
    def delete_track(self,tr):
        if len([x for x in self.proj.tracks if x['kind']==tr['kind']])<=1:QMessageBox.information(self,'Track','Keep at least one track of each type.');return
        self.checkpoint();self.proj.tracks=[x for x in self.proj.tracks if x['id']!=tr['id']];self.proj.clips=[c for c in self.proj.clips if c['track']!=tr['id']];self.on_changed()
    def trim_left(self):
        c = self.sel_clip()
        if not c or not c["start"] + 1e-4 < self.t < c["start"] + c["dur"] - 1e-4: return
        self.checkpoint(); cut = self.t - c["start"]; c["start"] = self.t; c["dur"] -= cut
        if c["kind"] not in ("image", "text"): c["inp"] += cut
        _shift_keys(c, cut); self.on_changed()
    def trim_right(self):
        c = self.sel_clip()
        if not c or not c["start"] + 1e-4 < self.t < c["start"] + c["dur"] - 1e-4: return
        self.checkpoint(); cut = self.t - c["start"]; c["dur"] = cut
        for pr in c["props"].values(): pr["k"] = [k for k in pr["k"] if k["t"] <= cut]
        self.on_changed()
    def group_sel(self):
        cs = _sel_clips(self)
        if len(cs) < 2: _toast("Ctrl+คลิกเลือกอย่างน้อย 2 คลิปก่อน"); return
        self.checkpoint(); g = new_id()
        for c in cs: c["group"] = g
        self.on_changed()
    def ungroup_sel(self):
        gids = {c.get("group") for c in _sel_clips(self) if c.get("group")}
        if not gids: return
        self.checkpoint()
        for c in self.proj.clips:
            if c.get("group") in gids: c.pop("group", None)
        self.on_changed()
    def close_gaps(self, track_ids):
        """Remove the empty space between the clips of the given tracks (each track on its own). The first clip of a
        track stays where it is; the others move left to follow the clip before them. Locked tracks are skipped."""
        if not self.proj: return
        ids = [t for t in track_ids if not (self.proj.track(t) or {}).get("locked")]
        if not ids: return
        before = self.begin(); moved = close_gaps_in(self.proj.clips, ids, self.proj.fps)
        if not moved: return
        self.commit(before); self.on_changed()
    def close_gaps_all(self):
        """Remove the gaps in every (unlocked) track at once."""
        if self.proj: self.close_gaps([t["id"] for t in self.proj.tracks])
    def make_compound(self):
        cs = _sel_clips(self)
        if len(cs) < 2: _toast("Ctrl+คลิกเลือกอย่างน้อย 2 คลิปก่อน"); return
        used = [tr for tr in self.proj.tracks if any(c["track"] == tr["id"] for c in cs)]
        vts = [tr for tr in used if tr["kind"] == "video"]
        if not vts: _toast("ต้องมีคลิปภาพ/วิดีโออย่างน้อย 1 คลิป"); return
        self.checkpoint()
        t0 = min(c["start"] for c in cs); t1 = max(c["start"] + c["dur"] for c in cs)
        children = []
        for c in cs:
            ch = copy.deepcopy(c); ch["start"] -= t0; ch.pop("group", None); children.append(ch)
        ids = {c["id"] for c in cs}; self.proj.clips = [c for c in self.proj.clips if c["id"] not in ids]
        host = vts[0]
        if not self.track_free(host["id"], t0, t1):
            host = self.proj.add_track("video", self.proj.track_index(host["id"]))
        comp = make_clip("compound", "compound://" + new_id(), host["id"], t0, t1 - t0, src_dur=0.0, name="Compound clip")
        comp.update(children=children, subtracks=copy.deepcopy(used), cw=self.proj.w, chh=self.proj.h, cfps=self.proj.fps)
        self.proj.clips.append(comp); self.sel = comp["id"]; self.multi = set(); self.on_changed()
    def uncompound(self):
        c = self.sel_clip()
        if not c or c.get("kind") != "compound": return
        self.checkpoint(); idx = self.proj.track_index(c["track"]); tmap = {}
        for i, st in enumerate(c.get("subtracks", [])):
            nt = self.proj.add_track(st["kind"], idx + i if st["kind"] == "video" else None)
            nt["name"] = st["name"]; tmap[st["id"]] = nt["id"]
        a, b = c["start"], c["start"] + c["dur"]; off = c["start"] - c["inp"]
        for ch in c.get("children", []):
            s = ch["start"] + off; e = s + ch["dur"]; s2, e2 = max(s, a), min(e, b)
            if e2 <= s2: continue
            n = copy.deepcopy(ch); n["id"] = new_id(); n["track"] = tmap.get(ch["track"], c["track"])
            n["start"] = s2; n["dur"] = e2 - s2
            if n["kind"] not in ("image", "text"): n["inp"] = ch["inp"] + (s2 - s)
            if s2 > s: _shift_keys(n, s2 - s)
            self.proj.clips.append(n)
        self.proj.clips = [x for x in self.proj.clips if x["id"] != c["id"]]; self.sel = None; self.on_changed()
    def _sel_clips(self): return _sel_clips(self)

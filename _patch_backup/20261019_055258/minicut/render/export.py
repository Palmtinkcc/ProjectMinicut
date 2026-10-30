"""Export dialog and the background export worker."""
from ..shared.deps import *
from ..shared.core import *
from ..shared.widgets import *
from .media import *
from .audio import *
from .renderer import *
from ..shared.hwaccel import *


def letterbox(fr, ow, oh):
    h, w = fr.shape[:2]; s = min(ow / w, oh / h)
    nw, nh = min(ow, max(1, int(round(w * s)))), min(oh, max(1, int(round(h * s))))
    if (nw, nh) != (w, h): fr = cv2.resize(fr, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    out = np.zeros((oh, ow, 3), np.uint8); y, x = (oh - nh) // 2, (ow - nw) // 2
    out[y:y + nh, x:x + nw] = fr; return out


FORMATS = OrderedDict([("mp4", ("MP4 · H.264", ".mp4")), ("mp4_265", ("MP4 · H.265 / HEVC", ".mp4")), ("mov", ("MOV · ProRes 422 HQ", ".mov")),
                       ("webm", ("WebM · VP9", ".webm")), ("mkv", ("MKV · H.264", ".mkv")), ("gif", ("GIF · animated", ".gif")),
                       ("png", ("PNG sequence", "")), ("mp3", ("MP3 · audio only", ".mp3")), ("wav", ("WAV · audio only", ".wav"))])


class ExportWorker(QThread):
    progress = Signal(float)
    done_sig = Signal(bool, str)
    def __init__(self, pd, opts):
        super().__init__(); self.pd = pd; self.o = opts; self.cancel = False
    def run(self):
        tmpd = None; proc = None
        try:
            proj = Project.from_dict(self.pd); o = self.o; dur = proj.duration()
            if dur <= 0 and o['fmt'] not in ('mp3','wav'): raise RuntimeError('Timeline is empty')
            fmt, out, fps, ow, oh, crf = o['fmt'], o['path'], int(o['fps']), int(o['w']), int(o['h']), int(o['crf'])
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            tmpd = tempfile.mkdtemp(prefix='minicut_'); wav = os.path.join(tmpd, 'audio.wav')
            data = mix_audio(proj, 0, max(dur, 0.01), wait=True)   # the export waits for the effects
            with wave.open(wav, 'wb') as wf:
                wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
                wf.writeframes((np.clip(data, -1, 1)*32767).astype(np.int16).tobytes())
            if fmt in ('mp3','wav'):
                cmd=[FFMPEG,'-y','-i',wav]
                if fmt=='mp3': cmd += ['-b:a','192k']
                cmd += [out]
                r=subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
                if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace')[-1500:])
                self.progress.emit(100); self.done_sig.emit(True,out); return
            if fmt == 'png':
                os.makedirs(out, exist_ok=True); proc=None
            elif fmt == 'gif':
                cmd=[FFMPEG,'-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','bgr24','-s',f'{ow}x{oh}','-r',str(fps),'-i','-','-vf','fps=15,scale=480:-1:flags=lanczos',out]
                proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=NOWIN)
            else:
                cmd=[FFMPEG,'-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','bgr24','-s',f'{ow}x{oh}','-r',str(fps),'-i','-']
                has_audio=os.path.getsize(wav)>44
                if has_audio: cmd += ['-i',wav]
                vcodec='libx265' if fmt=='mp4_265' else 'libvpx-vp9' if fmt=='webm' else 'prores_ks' if fmt=='mov' else 'libx264'
                hwenc = pick_hw_encoder(fmt == 'mp4_265') if fmt in ('mp4', 'mp4_265') else None
                if hwenc: vcodec = hwenc[1]
                cmd += ['-c:v',vcodec]
                if fmt=='mov': cmd += ['-profile:v','3']
                elif fmt=='webm': cmd += ['-b:v','4M']
                elif hwenc: cmd += hw_quality_args(hwenc[0], crf, ow)
                else: cmd += ['-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p']
                if has_audio: cmd += ['-c:a','libopus' if fmt=='webm' else 'aac','-b:a','192k','-shortest']
                cmd += ['-movflags','+faststart'] if fmt in ('mp4','mp4_265','mkv') else []
                cmd += [out]
                proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=NOWIN)
            renderer=Renderer(MediaPool()); total=max(1,int(dur*fps))
            for i in range(total):
                if self.cancel: break
                fr=renderer.render(proj,i/fps,1.0,fast=False)
                if ow != proj.w or oh != proj.h: fr=letterbox(fr,ow,oh)
                if fmt=='png':
                    if not cv2.imwrite(os.path.join(out,f'frame_{i:06d}.png'),fr): raise RuntimeError('Could not write PNG frame')
                elif proc and proc.stdin:
                    try: proc.stdin.write(np.ascontiguousarray(fr).tobytes())
                    except (BrokenPipeError,OSError): break
                if i%3==0: self.progress.emit((i+1)/total*100)
            if proc:
                if proc.stdin: proc.stdin.close()
                err=proc.stderr.read().decode(errors='replace') if proc.stderr else ''
                code=proc.wait()
                if code and not self.cancel: raise RuntimeError(err[-1800:] or f'FFmpeg exited with code {code}')
            if self.cancel: self.done_sig.emit(False,'Export cancelled')
            else: self.progress.emit(100); self.done_sig.emit(True,out)
        except Exception as ex: self.done_sig.emit(False,str(ex))
        finally:
            if tmpd:
                import shutil; shutil.rmtree(tmpd,ignore_errors=True)


class ExportDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app,'Export video',500); self.app=app
        form=QFormLayout(); self.fmt=QComboBox()
        for k,(label,ext) in FORMATS.items(): self.fmt.addItem(label,k)
        self.fmt.currentIndexChanged.connect(self.update_ext)
        self.path=PathEdit(app.settings['export_folder']); self.filename=QLineEdit(safe_name(app.proj.name)+'.mp4')
        self.fps=QComboBox(); [self.fps.addItem(f'{v} fps',v) for v in (24,25,30,50,60)]
        self.fps.setCurrentIndex(max(0,self.fps.findData(app.proj.fps)))
        self.size=QComboBox()
        for label,w,h in SIZE_PRESETS: self.size.addItem(label,(w,h))
        idx=next((i for i,(_,w,h) in enumerate(SIZE_PRESETS) if (w,h)==(app.proj.w,app.proj.h)),0); self.size.setCurrentIndex(idx)
        self.crf=QSpinBox(); self.crf.setRange(12,35); self.crf.setValue(20)
        form.addRow('Format',self.fmt); form.addRow('Output folder',self.path); form.addRow('File name',self.filename); form.addRow('Resolution',self.size); form.addRow('Frame rate',self.fps); form.addRow('Quality (lower = better)',self.crf)
        self.body.addLayout(form); self.prog=QProgressBar(); self.prog.setValue(0); self.body.addWidget(self.prog)
        self.status=QLabel('Ready'); self.body.addWidget(self.status)
        row=QHBoxLayout(); row.addStretch(); cancel=QPushButton('Close'); cancel.clicked.connect(self.reject); self.go=QPushButton('Export'); self.go.setObjectName('Accent'); self.go.clicked.connect(self.start_export); row.addWidget(cancel); row.addWidget(self.go); self.body.addLayout(row)
    def update_ext(self):
        k=self.fmt.currentData(); ext=FORMATS[k][1]
        base=os.path.splitext(self.filename.text())[0] or safe_name(self.app.proj.name)
        if ext: self.filename.setText(base+ext)
    def start_export(self):
        folder=self.path.text() or self.app.settings['export_folder']; os.makedirs(folder,exist_ok=True)
        name=self.filename.text().strip() or safe_name(self.app.proj.name)+FORMATS[self.fmt.currentData()][1]
        out=os.path.join(folder,name); w,h=self.size.currentData()
        self.app.settings['export_folder']=folder; self.app.settings.save(); self.go.setEnabled(False); self.status.setText('Rendering…')
        self.worker=ExportWorker(self.app.proj.to_dict(),{'fmt':self.fmt.currentData(),'path':out,'fps':self.fps.currentData(),'w':w,'h':h,'crf':self.crf.value()})
        self.worker.progress.connect(lambda v:self.prog.setValue(int(v)))
        self.worker.done_sig.connect(self.finished_export); self.worker.start()
    def finished_export(self,ok,msg):
        self.go.setEnabled(True); self.status.setText(('Exported: ' if ok else 'Error: ')+msg)
        if ok: QMessageBox.information(self,'Export complete','Saved to:\n'+msg)
        else: QMessageBox.warning(self,'Export failed',msg)

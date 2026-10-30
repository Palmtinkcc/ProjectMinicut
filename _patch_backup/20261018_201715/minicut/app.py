"""MiniCut main window and application entry point."""
from .shared.deps import *
from .shared.theme import *
from .shared.core import *
from .shared.appearance import *
from .render.media import *
from .render.audio import *
from .render.renderer import *
from .render.preview import *
from .render.export import *
from .shared.dialogs import *
from .project.create import *
from .workspace.node_editor import *
from .workspace.actions import *


class MainWindow(ProjectMixin, WorkspaceMixin, PlaybackMixin, NodesMixin, QMainWindow):
    """Main window: owns the project, the renderer and the pages (home / workspace / node editor)."""
    def __init__(self):
        super().__init__(); self.setWindowTitle('MiniCut'); self.resize(1440,900); self.setMinimumSize(900,600)
        self.settings=Settings(); CFG['frame_cache']=self.settings['frame_cache']; CFG['hw_decode']=self.settings['hw_decode']; CFG['encode_hw']=self.settings['encode_hw']; self.proj=None; self.t=0.0; self.sel=None; self.snap_on=self.settings['snap']; self.playing=False; self._undo=[]; self._redo=[]; self._last_state=None; self._clip_copy=None
        self.thumbs=ThumbStore(); self.pool=MediaPool(use_proxy=self.settings['proxy_preview']); self.renderer=Renderer(self.pool); self.audio=AudioPlayer(); self.timer=QTimer(self); self.timer.setInterval(self.frame_ms()); self.timer.timeout.connect(self.tick); self._last_tick=time.monotonic(); self.audio_seek_timer=QTimer(self); self.audio_seek_timer.setSingleShot(True); self.audio_seek_timer.setInterval(60); self.audio_seek_timer.timeout.connect(self._restart_audio_after_seek)
        self.stack=QStackedWidget(); self.setCentralWidget(self.stack); self.home=QWidget(); self.stack.addWidget(self.home); self._build_home(); self.editor=QWidget(); self.stack.addWidget(self.editor); self.apply_shortcuts(); self.show_home()
    def frame_ms(self): return max(8, int(round(1000 / max(1, int(self.settings['preview_fps'])))))
    def apply_preview_fps(self): self.timer.setInterval(self.frame_ms())
    def open_settings(self):
        d=SettingsDialog(self)
        if d.exec():
            self.apply_preview_fps()
            if self.pool.use_proxy != self.settings['proxy_preview']:
                with self.renderer._src_lock: self.pool.use_proxy = self.settings['proxy_preview']; self.pool.src.clear()
                self.renderer.clear_preview_cache()
            if self.proj:self.request_render()
    def open_shortcuts(self): ShortcutDialog(self).exec()
    def export_dialog(self):
        if self.proj:ExportDialog(self).exec()
    def apply_shortcuts(self):
        if not hasattr(self,'editor'):return
        for a in getattr(self,'_actions',[]):self.removeAction(a)
        self._actions=[]
        mapping={'play':self.toggle_play,'split':self.split,'delete':self.delete_sel,'undo':self.do_undo,'redo':self.do_redo,'copy':self.copy_clip,'paste':self.paste_clip,'duplicate':self.duplicate,'save':self.save_project,'export':self.export_dialog,'import':self.import_dialog,'add_text':self.add_text,'keyframe':self.key_all,'prev_frame':lambda:self.step(-1),'next_frame':lambda:self.step(1),'go_start':lambda:self.seek(0),'go_end':lambda:self.seek(self.proj.duration() if self.proj else 0),'zoom_in':lambda:self.timeline.set_zoom(self.timeline.pps*1.25) if hasattr(self,'timeline') else None,'zoom_out':lambda:self.timeline.set_zoom(self.timeline.pps/1.25) if hasattr(self,'timeline') else None,'zoom_fit':lambda:self.timeline.zoom_fit() if hasattr(self,'timeline') else None,'snap':self.toggle_snap,'home':self.show_home}
        for key,fn in mapping.items():
            seq=self.settings['shortcuts'].get(key,'')
            if seq:
                act=QAction(self); act.setShortcut(QKeySequence(seq)); act.setShortcutContext(Qt.ApplicationShortcut); act.triggered.connect(fn); self.addAction(act); self._actions.append(act)
    def closeEvent(self,e):
        self.stop_play()
        if self.proj and self.stack.currentWidget()==self.editor:
            ans=QMessageBox.question(self,'MiniCut','Save this project before exiting?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
            if ans==QMessageBox.Cancel:e.ignore();return
            if ans==QMessageBox.Save:self.save_project()
        e.accept()


def main():
    app=QApplication(sys.argv); app.setApplicationName('MiniCut'); app.setStyle('Fusion'); app.setStyleSheet(QSS)
    win=MainWindow(); apply_ui(win); win.show(); sys.exit(app.exec())


if __name__ == '__main__':
    main()

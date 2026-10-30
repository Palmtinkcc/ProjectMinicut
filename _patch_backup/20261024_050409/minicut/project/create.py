"""Project creation: new-project dialog, home screen, open / load / save of project files."""
from ..shared.deps import *
from ..shared.icons import *
from ..shared.core import *
from ..shared.widgets import *
from ..render.media import *
from ..render.renderer import *


class NewProjectDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "New project"); form = QFormLayout()
        self.name = QLineEdit(f"Project {datetime.datetime.now():%Y-%m-%d %H%M}")
        self.preset = QComboBox(); [self.preset.addItem(n, (w, h)) for n, w, h in SIZE_PRESETS]
        idx = next((i for i, (_, w, h) in enumerate(SIZE_PRESETS) if (w, h) == (app.settings["default_w"], app.settings["default_h"])), 0)
        self.preset.setCurrentIndex(idx)
        self.fps = QComboBox(); [self.fps.addItem(f"{f} fps", f) for f in (24, 25, 30, 50, 60)]
        self.fps.setCurrentIndex(max(0, self.fps.findData(app.settings["default_fps"])))
        form.addRow("Name", self.name); form.addRow("Canvas", self.preset); form.addRow("Frame rate", self.fps); self.body.addLayout(form)
        row = QHBoxLayout(); row.addStretch(); c = QPushButton("Cancel"); c.clicked.connect(self.reject)
        ok = QPushButton("Create"); ok.setObjectName("Accent"); ok.clicked.connect(self.accept); row.addWidget(c); row.addWidget(ok); self.body.addLayout(row)
    def data(self):
        w, h = self.preset.currentData(); return self.name.text().strip() or "Untitled", w, h, self.fps.currentData()


class ProjectMixin:
    """Project creation / opening / saving and the home screen."""
    def _build_home(self):
        l=QVBoxLayout(self.home); l.setContentsMargins(42,32,42,32); title=QLabel('MiniCut'); title.setObjectName('H1'); sub=QLabel('Lightweight video editor'); sub.setObjectName('Dim'); l.addWidget(title); l.addWidget(sub)
        row=QHBoxLayout(); b=QPushButton('New project'); b.setIcon(app_icon('import')); b.setObjectName('Accent'); b.clicked.connect(self.new_project); row.addWidget(b); b=QPushButton('Open project…'); b.setIcon(app_icon('folder_open')); b.clicked.connect(self.open_dialog); row.addWidget(b); b=QPushButton('Settings'); b.setIcon(app_icon('settings')); b.clicked.connect(self.open_settings); row.addWidget(b); row.addStretch(); l.addLayout(row)
        l.addWidget(QLabel('Recent projects'))
        self.recent=QListWidget(); self.recent.itemDoubleClicked.connect(lambda it:self.load_project(it.data(Qt.UserRole))); l.addWidget(self.recent,1)
    def show_home(self):
        self.stop_play(); self.refresh_recent(); self.stack.setCurrentWidget(self.home)
    def refresh_recent(self):
        self.recent.clear(); folder=self.settings['project_folder']; os.makedirs(folder,exist_ok=True)
        for p in sorted([os.path.join(folder,f) for f in os.listdir(folder) if f.lower().endswith('.minicut')],key=os.path.getmtime,reverse=True):
            it=QListWidgetItem(app_icon('project'), os.path.basename(p)+'   ·   '+datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')); it.setData(Qt.UserRole,p); self.recent.addItem(it)
    def new_project(self):
        d=NewProjectDialog(self)
        if d.exec()!=QDialog.Accepted:return
        name,w,h,fps=d.data(); self.proj=Project(name,w,h,fps); self.proj.path=None; self.t=0; self.sel=None; self._undo=[]; self._redo=[]; self._build_editor(); self.stack.setCurrentWidget(self.editor); self.request_render()
    def open_dialog(self):
        p,_=QFileDialog.getOpenFileName(self,'Open MiniCut project',self.settings['project_folder'],'MiniCut project (*.minicut *.json)')
        if p:self.load_project(p)
    def load_project(self,p):
        try:
            with open(p,'r',encoding='utf-8') as f:d=json.load(f)
            self.proj=Project.from_dict(d); self.proj.path=p; self.t=0; self.sel=None; self._undo=[]; self._redo=[]; self.pool=MediaPool(); self.renderer=Renderer(self.pool); self._build_editor(); self.stack.setCurrentWidget(self.editor); self.request_render()
        except Exception as ex: QMessageBox.warning(self,'Open failed',str(ex))
    def save_project(self):
        if not self.proj:return
        path=self.proj.path
        if not path:
            folder=self.settings['project_folder']; os.makedirs(folder,exist_ok=True); path=os.path.join(folder,safe_name(self.proj.name)+'.minicut')
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True)
            with open(path,'w',encoding='utf-8') as f:json.dump(self.proj.to_dict(),f,ensure_ascii=False,indent=2)
            self.proj.path=path; self.settings.save(); self.refresh_recent(); self.toast.show_msg('Project saved')
        except Exception as ex:QMessageBox.warning(self,'Save failed',str(ex))

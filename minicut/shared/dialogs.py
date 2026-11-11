"""Settings and Shortcuts dialogs."""
from .deps import *
from .theme import *
from .core import *
from .appearance import *
from .widgets import *
from .hwaccel import *
from .ui import *
QSpinBox = SpinBox; QDoubleSpinBox = DoubleSpinBox; QComboBox = ComboBox; QCheckBox = CheckBox


from .settings_dialog import SettingsDialog      # Patch 37: the Settings window lives in settings_dialog.py


class ShortcutDialog(AnimatedDialog):
    def __init__(self, app):
        super().__init__(app, "Keyboard shortcuts", 520); self.app = app; sc = app.settings["shortcuts"]
        self.table = QTableWidget(len(DEFAULT_SHORTCUTS), 2); self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220); self.table.setMinimumHeight(420); self.edits = {}
        for i, k in enumerate(DEFAULT_SHORTCUTS):
            it = QTableWidgetItem(ACTION_LABELS[k]); it.setFlags(Qt.ItemIsEnabled); self.table.setItem(i, 0, it)
            e = QKeySequenceEdit(QKeySequence(sc.get(k, ""))); self.edits[k] = e; self.table.setCellWidget(i, 1, e)
        self.body.addWidget(self.table)
        row = QHBoxLayout(); r = QPushButton("Reset defaults"); r.clicked.connect(self.reset); row.addWidget(r); row.addStretch()
        c = QPushButton("Cancel"); c.clicked.connect(self.reject); ok = QPushButton("Save"); ok.setObjectName("Accent"); ok.clicked.connect(self.save)
        row.addWidget(c); row.addWidget(ok); self.body.addLayout(row)
    def reset(self):
        for k, e in self.edits.items(): e.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[k]))
    def save(self):
        seqs = {k: e.keySequence().toString(QKeySequence.PortableText) for k, e in self.edits.items()}
        used = [v for v in seqs.values() if v]
        dup = {v for v in used if used.count(v) > 1}
        if dup: ask(self, "Duplicate shortcut", "These shortcuts are used more than once: " + ", ".join(dup), ("OK",)); return
        self.app.settings["shortcuts"].update(seqs); self.app.settings.save(); self.app.apply_shortcuts(); self.accept()

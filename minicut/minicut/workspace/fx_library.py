"""FX Library Manager — Patch 50
Manage, organise, import and export custom effects.
Built-in effects are shown read-only; only custom effects can be edited/deleted.
"""
from ..shared.deps import *
from ..shared.widgets import *
from ..render.effects import FX
from ..render.fxpack.custom import (
    CUSTOM_REGISTRY, CUSTOM_FX_DIR, delete_effect, export_effect,
    import_effect, load_all as reload_custom_fx,
    get_categories, save_categories, _mcfx_path,
)
import os, json, shutil, zipfile


class FxLibraryPanel(QWidget):
    """Side panel showing all effects with search, category filter, edit/delete for custom ones."""

    open_editor = Signal(str)   # emit effect id (without "custom:" prefix) to open in FxNodeEditor

    def __init__(self, app):
        super().__init__(); self.app = app
        self.setMinimumWidth(320)
        self.setStyleSheet("background:#0d1f1f; color:#d0fff6;")
        root = QVBoxLayout(self); root.setContentsMargins(10,10,10,10); root.setSpacing(8)

        # ── Header ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Effect Library"); title.setStyleSheet("font-size:15px;font-weight:bold;color:#80ffe8;")
        hdr.addWidget(title); hdr.addStretch()

        new_btn = QPushButton("+ New")
        new_btn.setToolTip("Create a new custom effect with the node editor")
        new_btn.setStyleSheet("QPushButton{background:#006655;color:#d0fff6;border:none;border-radius:4px;padding:4px 12px;}"
                              "QPushButton:hover{background:#00896e;}")
        new_btn.clicked.connect(lambda: self.open_editor.emit(""))

        imp_btn = QPushButton("Import .mcfx")
        imp_btn.setStyleSheet("QPushButton{background:#112828;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:4px 10px;}"
                              "QPushButton:hover{background:#1a4040;}")
        imp_btn.clicked.connect(self._on_import)

        cat_btn = QPushButton("Categories…")
        cat_btn.setStyleSheet("QPushButton{background:#112828;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:4px 10px;}"
                              "QPushButton:hover{background:#1a4040;}")
        cat_btn.clicked.connect(self._on_manage_cats)

        for b in (new_btn, imp_btn, cat_btn): hdr.addWidget(b)
        root.addLayout(hdr)

        # ── Search + filter ────────────────────────────────────────────────
        sf = QHBoxLayout(); sf.setSpacing(6)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search effects…")
        self.search.setStyleSheet("QLineEdit{background:#112828;color:#d0fff6;border:1px solid #1a4040;border-radius:4px;padding:4px 8px;}")
        self.search.textChanged.connect(self._refresh)

        self.cat_filter = QComboBox()
        self.cat_filter.setStyleSheet("QComboBox{background:#112828;color:#d0fff6;border:1px solid #1a4040;border-radius:4px;padding:3px 6px;min-width:100px;}")
        self.cat_filter.currentTextChanged.connect(self._refresh)

        self.show_builtin = QCheckBox("Built-in")
        self.show_builtin.setChecked(True)
        self.show_builtin.setStyleSheet("color:#8ab8b0;")
        self.show_builtin.toggled.connect(self._refresh)

        sf.addWidget(self.search,1); sf.addWidget(self.cat_filter); sf.addWidget(self.show_builtin)
        root.addLayout(sf)

        # ── Effect list ────────────────────────────────────────────────────
        self.list_w = QListWidget()
        self.list_w.setStyleSheet("""
            QListWidget{background:#0a1a1a;border:1px solid #1a4040;border-radius:4px;}
            QListWidget::item{padding:6px 8px;border-bottom:1px solid #0d2525;}
            QListWidget::item:selected{background:#006655;}
            QListWidget::item:hover{background:#112828;}
        """)
        self.list_w.itemDoubleClicked.connect(self._on_dbl_click)
        root.addWidget(self.list_w, 1)

        # ── Action bar ─────────────────────────────────────────────────────
        act = QHBoxLayout(); act.setSpacing(6)
        self.edit_btn = QPushButton("Edit in node editor")
        self.edit_btn.setEnabled(False)
        self.edit_btn.setStyleSheet("QPushButton{background:#004a40;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:5px 10px;}"
                                    "QPushButton:enabled:hover{background:#006655;}"
                                    "QPushButton:disabled{color:#3a5a55;border-color:#1a3030;}")
        self.edit_btn.clicked.connect(self._on_edit)

        self.exp_btn = QPushButton("Export .mcfx")
        self.exp_btn.setEnabled(False)
        self.exp_btn.setStyleSheet("QPushButton{background:#112828;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:5px 10px;}"
                                   "QPushButton:enabled:hover{background:#1a4040;}"
                                   "QPushButton:disabled{color:#3a5a55;border-color:#1a3030;}")
        self.exp_btn.clicked.connect(self._on_export)

        self.del_btn = QPushButton("Delete")
        self.del_btn.setEnabled(False)
        self.del_btn.setStyleSheet("QPushButton{background:#3a0d0d;color:#ff8060;border:1px solid #5a1a1a;border-radius:4px;padding:5px 10px;}"
                                   "QPushButton:enabled:hover{background:#5a1a1a;}"
                                   "QPushButton:disabled{color:#3a2020;border-color:#2a1010;}")
        self.del_btn.clicked.connect(self._on_delete)

        exp_cat_btn = QPushButton("Export category…")
        exp_cat_btn.setStyleSheet("QPushButton{background:#112828;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:5px 10px;}"
                                  "QPushButton:hover{background:#1a4040;}")
        exp_cat_btn.clicked.connect(self._on_export_category)

        for b in (self.edit_btn, self.exp_btn, self.del_btn, exp_cat_btn): act.addWidget(b)
        root.addLayout(act)

        self.list_w.currentItemChanged.connect(self._on_sel_changed)
        self.reload()

    # ── Data ───────────────────────────────────────────────────────────────
    def reload(self):
        reload_custom_fx()
        # Rebuild category filter
        cats = sorted(set(
            [FX[k].get("cat","") for k in FX] +
            [CUSTOM_REGISTRY[k]["meta"].get("category","Custom") for k in CUSTOM_REGISTRY if CUSTOM_REGISTRY[k]["fn"]]
        ))
        cur = self.cat_filter.currentText()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear(); self.cat_filter.addItem("All categories")
        for c in cats: self.cat_filter.addItem(c)
        idx = self.cat_filter.findText(cur)
        self.cat_filter.setCurrentIndex(max(0, idx))
        self.cat_filter.blockSignals(False)
        self._refresh()

    def _refresh(self):
        q = self.search.text().lower(); cat_f = self.cat_filter.currentText(); show_bi = self.show_builtin.isChecked()
        self.list_w.clear()

        # Built-in effects
        if show_bi:
            for eid, spec in FX.items():
                if eid.startswith("custom:"): continue
                cat = spec.get("cat","")
                if cat_f != "All categories" and cat != cat_f: continue
                if q and q not in spec.get("title","").lower() and q not in cat.lower(): continue
                item = QListWidgetItem("  %s" % spec.get("title", eid))
                item.setData(Qt.UserRole, ("builtin", eid))
                item.setForeground(QColor("#8ab8b0"))
                item.setToolTip("Built-in effect · %s" % cat)
                self.list_w.addItem(item)

        # Custom effects
        for eid, reg in CUSTOM_REGISTRY.items():
            meta = reg.get("meta", {}); err = reg.get("error")
            cat = meta.get("category", "Custom")
            if cat_f != "All categories" and cat != cat_f: continue
            name = meta.get("name", eid)
            if q and q not in name.lower() and q not in cat.lower(): continue
            icon = "⚠ " if err else "✦ "
            item = QListWidgetItem("  %s%s" % (icon, name))
            item.setData(Qt.UserRole, ("custom", meta.get("id", eid)))
            item.setForeground(QColor("#ff8060") if err else QColor("#00c4a0"))
            item.setToolTip(("ERROR: " + err) if err else "%s · %s" % (cat, meta.get("description","")))
            self.list_w.addItem(item)

    def _current_entry(self):
        it = self.list_w.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _on_sel_changed(self):
        e = self._current_entry()
        is_custom = e and e[0] == "custom"
        self.edit_btn.setEnabled(bool(is_custom))
        self.exp_btn.setEnabled(bool(is_custom))
        self.del_btn.setEnabled(bool(is_custom))

    def _on_dbl_click(self, item):
        e = item.data(Qt.UserRole)
        if e and e[0] == "custom": self.open_editor.emit(e[1])

    def _on_edit(self):
        e = self._current_entry()
        if e and e[0] == "custom": self.open_editor.emit(e[1])

    def _on_delete(self):
        e = self._current_entry()
        if not e or e[0] != "custom": return
        eid = e[1]
        name = CUSTOM_REGISTRY.get("custom:"+eid, {}).get("meta",{}).get("name", eid)
        if QMessageBox.question(self, "Delete effect",
                                "Delete \"%s\"? This cannot be undone." % name,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        delete_effect(eid); self.reload()
        if hasattr(self.app, "on_changed"): self.app.on_changed()

    def _on_export(self):
        e = self._current_entry()
        if not e or e[0] != "custom": return
        eid = e[1]
        name = CUSTOM_REGISTRY.get("custom:"+eid, {}).get("meta",{}).get("name", eid)
        path, _ = QFileDialog.getSaveFileName(self, "Export effect", name+".mcfx", "MiniCut Effect (*.mcfx)")
        if path:
            try: export_effect(eid, path); QMessageBox.information(self,"Exported","Saved to "+path)
            except Exception as ex: QMessageBox.warning(self,"Export failed",str(ex))

    def _on_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import effects", "", "MiniCut Effect (*.mcfx);;ZIP bundle (*.zip)")
        imported = []
        for p in paths:
            if p.endswith(".zip"):
                imported += self._import_zip(p)
            else:
                eid = import_effect(p)
                if eid: imported.append(eid)
        if imported:
            self.reload()
            if hasattr(self.app, "on_changed"): self.app.on_changed()
            QMessageBox.information(self, "Imported", "Imported %d effect(s)." % len(imported))
        else:
            QMessageBox.warning(self, "Import failed", "No valid effects found.")

    def _import_zip(self, path: str) -> list:
        imported = []
        import tempfile
        with zipfile.ZipFile(path) as z:
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                for fname in os.listdir(tmp):
                    if fname.endswith(".mcfx"):
                        eid = import_effect(os.path.join(tmp, fname))
                        if eid: imported.append(eid)
        return imported

    def _on_export_category(self):
        cats = sorted(set(CUSTOM_REGISTRY[k]["meta"].get("category","Custom")
                          for k in CUSTOM_REGISTRY if CUSTOM_REGISTRY[k]["fn"]))
        if not cats: QMessageBox.information(self,"No custom effects","No custom effects to export."); return
        cat, ok = QInputDialog.getItem(self, "Export category", "Select category to export as ZIP:", cats, 0, False)
        if not ok: return
        ids = [CUSTOM_REGISTRY[k]["meta"]["id"] for k in CUSTOM_REGISTRY
               if CUSTOM_REGISTRY[k]["fn"] and CUSTOM_REGISTRY[k]["meta"].get("category")==cat]
        if not ids: return
        safe = re.sub(r"[^a-z0-9_]","_", cat.lower())
        path, _ = QFileDialog.getSaveFileName(self,"Export category",safe+".zip","ZIP bundle (*.zip)")
        if not path: return
        try:
            with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
                for eid in ids: z.write(_mcfx_path(eid), eid+".mcfx")
            QMessageBox.information(self,"Exported","%d effect(s) saved to %s"%(len(ids),path))
        except Exception as ex: QMessageBox.warning(self,"Export failed",str(ex))

    def _on_manage_cats(self):
        dlg = CategoryDialog(self)
        dlg.exec()
        self.reload()


class CategoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Manage Categories")
        self.setMinimumSize(320, 280)
        self.setStyleSheet("background:#0d1f1f;color:#d0fff6;")
        lay = QVBoxLayout(self); lay.setSpacing(8)
        lay.addWidget(QLabel("User-defined categories (built-in categories cannot be removed):"))
        self.lst = QListWidget()
        self.lst.setStyleSheet("QListWidget{background:#0a1a1a;border:1px solid #1a4040;}")
        for cat in get_categories(): self.lst.addItem(cat)
        lay.addWidget(self.lst, 1)
        row = QHBoxLayout(); self.new_edit = QLineEdit(); self.new_edit.setPlaceholderText("New category name…")
        self.new_edit.setStyleSheet("QLineEdit{background:#112828;color:#d0fff6;border:1px solid #1a4040;border-radius:3px;padding:3px 6px;}")
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("QPushButton{background:#006655;color:#d0fff6;border:none;border-radius:4px;padding:4px 12px;}")
        add_btn.clicked.connect(self._add)
        del_btn = QPushButton("Remove selected")
        del_btn.setStyleSheet("QPushButton{background:#3a0d0d;color:#ff8060;border:1px solid #5a1a1a;border-radius:4px;padding:4px 10px;}")
        del_btn.clicked.connect(self._remove)
        row.addWidget(self.new_edit,1); row.addWidget(add_btn); row.addWidget(del_btn)
        lay.addLayout(row)
        ok = QPushButton("Done")
        ok.setStyleSheet("QPushButton{background:#004a40;color:#80ffe8;border:1px solid #1a4040;border-radius:4px;padding:5px 16px;}")
        ok.clicked.connect(self.accept); lay.addWidget(ok, 0, Qt.AlignRight)

    def _add(self):
        name = self.new_edit.text().strip()
        if name and not self.lst.findItems(name, Qt.MatchExactly):
            self.lst.addItem(name); self.new_edit.clear(); self._save()

    def _remove(self):
        r = self.lst.currentRow()
        if r >= 0: self.lst.takeItem(r); self._save()

    def _save(self):
        save_categories([self.lst.item(i).text() for i in range(self.lst.count())])

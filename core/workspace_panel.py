"""Editable work checkpoints and explicit desktop-only reopening review."""
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QCheckBox, QPushButton, QFileDialog, QMessageBox, QInputDialog,
    QTableWidgetItem)
from core.productivity_panel import AsyncPanel, _table
from core.workspaces import WorkspaceStore, APPS


class WorkspacePanel(AsyncPanel):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or WorkspaceStore()
        self.row, self.rows, self.dirty, self.loading = {}, [], False, False
        layout = QVBoxLayout(self)
        intro = QLabel('Continue my work: save where you stopped, then review what to reopen.\n'
                       'Only selected folders, apps and HTTPS pages are reopened. Unsaved editor text is not captured.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = _table(['Workspace', 'Last checkpoint'])
        self.table.setMaximumHeight(140)
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.name, self.folder = QLineEdit(), QLineEdit()
        pick = QPushButton('Choose folder')
        pick.clicked.connect(self.choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder)
        folder_row.addWidget(pick)
        self.notes, self.steps, self.urls = QPlainTextEdit(), QPlainTextEdit(), QPlainTextEdit()
        self.notes.setPlaceholderText('What you completed, decisions, and where you stopped')
        self.steps.setPlaceholderText('Next steps, one per line')
        self.urls.setPlaceholderText('Optional HTTPS pages, one per line (maximum 8)')
        for widget in (self.notes, self.steps, self.urls):
            widget.setMaximumHeight(78)
        self.apps = {}
        app_row = QHBoxLayout()
        for name in APPS:
            box = QCheckBox(name)
            box.toggled.connect(self.changed)
            self.apps[name] = box
            app_row.addWidget(box)
        form.addRow('Workspace name', self.name)
        form.addRow('Project folder', folder_row)
        form.addRow('Where I stopped', self.notes)
        form.addRow('Next steps', self.steps)
        form.addRow('Apps to reopen', app_row)
        form.addRow('Web pages', self.urls)
        layout.addLayout(form)
        for widget in (self.name, self.folder, self.notes, self.steps, self.urls):
            widget.textChanged.connect(self.changed)
        buttons = QHBoxLayout()
        for text, callback in (('New', self.new), ('Import project', self.import_project),
                               ('Save checkpoint', self.save), ('Continue my work', self.resume),
                               ('Delete', self.remove), ('Refresh', self.refresh)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(110)
        layout.addWidget(self.summary)
        self.status = QLabel('Choose a saved workspace or create a checkpoint.')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def changed(self, *_args):
        if not self.loading:
            self.dirty = True

    def question(self, title, text):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def discard(self):
        return not self.dirty or self.question('Unsaved checkpoint', 'Discard the unsaved edits?')

    def values(self):
        return {'id': self.row.get('id'), 'name': self.name.text(), 'folder': self.folder.text(),
                'notes': self.notes.toPlainText(), 'next_steps': self.steps.toPlainText(),
                'apps': [name for name, box in self.apps.items() if box.isChecked()],
                'urls': [line.strip() for line in self.urls.toPlainText().splitlines() if line.strip()]}

    def load(self, row):
        self.loading = True
        self.row = row
        self.name.setText(row.get('name', ''))
        self.folder.setText(row.get('folder', ''))
        self.notes.setPlainText(row.get('notes', ''))
        self.steps.setPlainText(row.get('next_steps', ''))
        self.urls.setPlainText('\n'.join(row.get('urls', [])))
        for name, box in self.apps.items():
            box.setChecked(name in row.get('apps', []))
        self.loading, self.dirty = False, False
        self.summary.setPlainText(('Where you stopped:\n' + row.get('notes', '') + '\n\nNext steps:\n' + row.get('next_steps', '')) if row else '')
        if row.get('id'):
            try:
                last = self.store.latest_run(row['id'])
                if last:
                    self.summary.appendPlainText('\nLast reopening: ' + last['status'] + '\n' + self.results(last))
            except (OSError, ValueError, PermissionError) as exc:
                self.status.setText(str(exc))

    def populate(self, rows, selected=None):
        self.rows = rows
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate((row['name'], datetime.fromtimestamp(row['updated']).strftime('%Y-%m-%d %H:%M'))):
                self.table.setItem(index, column, QTableWidgetItem(value))
        index = next((i for i, row in enumerate(rows) if row['id'] == selected), 0 if rows else -1)
        if index >= 0:
            self.table.selectRow(index)
        self.table.blockSignals(False)
        self.load(rows[index] if index >= 0 else {})

    def refresh(self):
        if self.busy or not self.discard():
            return
        selected = self.row.get('id')
        self.background(self.store.list, lambda rows: self.populate(rows, selected))

    def select(self):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            return
        if not self.discard():
            self.table.blockSignals(True)
            old = next((i for i, row in enumerate(self.rows) if row['id'] == self.row.get('id')), -1)
            if old >= 0:
                self.table.selectRow(old)
            else:
                self.table.clearSelection()
            self.table.blockSignals(False)
            return
        self.load(self.rows[index])

    def new(self):
        if self.discard():
            self.table.clearSelection()
            self.load({})

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose a project folder')
        if folder:
            self.folder.setText(folder)

    def import_project(self):
        if not self.discard():
            return
        try:
            self.store.permitted()
            from core.project_memory import projects
            rows = projects.list()
            if not rows:
                self.status.setText('No saved projects. Choose a folder to create a workspace.')
                return
            names = [f"{i + 1}. {row['name']}" for i, row in enumerate(rows)]
            name, accepted = QInputDialog.getItem(self, 'Import project context', 'Project', names, 0, False)
            if not accepted:
                return
            row = rows[names.index(name)]
            self.load({'name': row['name'], 'folder': row['path'], 'notes': str(row.get('notes', '')),
                       'next_steps': '\n'.join(map(str, row.get('pending_tasks', [])))})
            self.dirty = True
            self.status.setText('Imported into an unsaved checkpoint. Review and save; the original project record is unchanged.')
        except Exception as exc:
            self.status.setText(str(exc))

    def save(self):
        value, revision = self.values(), self.row.get('revision', 0)
        def operation():
            row = self.store.save(value, revision)
            return self.store.list(), row['id']
        def done(result):
            self.populate(*result)
            self.status.setText('Checkpoint saved locally. Nothing was opened or run.')
        self.background(operation, done)

    @staticmethod
    def results(result):
        return '\n'.join(f"{item['kind']}: {item['value']} — {item['status']}\n{item['result']}" for item in result.get('outcomes', []))

    def resume(self):
        if self.dirty or not self.row.get('id'):
            self.status.setText('Save this checkpoint before continuing.')
            return
        try:
            plan = self.store.preview(self.row['id'])
            if not plan['items']:
                self.status.setText('Your notes and next steps are shown below. No apps, folder or pages are selected to reopen.')
                return
            detail = '\n'.join(f"{item['kind']}: {item['value']}" for item in plan['items'])
            if not self.question('Continue this workspace?', 'Open these saved items?\n\n' + detail + '\n\nThe folder opens in your file manager. Apps use their own saved session. Unsaved editor buffers are not restored.'):
                return
            def done(result):
                self.status.setText(result['status'] + '. See the results below.')
                self.summary.appendPlainText('\nReopening results:\n' + self.results(result))
            self.background(lambda: self.store.restore_reviewed(plan), done)
        except Exception as exc:
            self.status.setText(str(exc))

    def remove(self):
        if not self.row.get('id') or not self.question('Delete checkpoint?', 'Delete this saved workspace and its reopening history? Project files and browser data are not deleted.'):
            return
        ident, revision = self.row['id'], self.row['revision']
        def operation():
            self.store.delete(ident, revision)
            return self.store.list()
        def done(rows):
            self.dirty = False
            self.populate(rows)
            self.status.setText('Checkpoint deleted. Project files were not changed.')
        self.background(operation, done)

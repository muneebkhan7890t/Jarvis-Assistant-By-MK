"""Native Qt task/note/reminder management. All storage and scheduler I/O is off-thread."""
import re
from datetime import datetime
from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QComboBox, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QSpinBox)

class _Signals(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

class _Worker(QRunnable):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.callback())
        except Exception as exc:
            self.signals.error.emit(str(exc))

class AsyncPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._workers = set()

    def background(self, operation, done):
        if self.busy:
            return
        self.busy = True
        self.setEnabled(False)
        worker = _Worker(operation)
        self._workers.add(worker)
        def finish(value, failed=False):
            self.busy = False
            self._workers.discard(worker)
            if sip.isdeleted(self):
                return
            self.setEnabled(True)
            if failed:
                self.status.setText('Failed: ' + value)
            else:
                done(value)
        worker.signals.done.connect(finish)
        worker.signals.error.connect(lambda text: finish(text, True))
        QThreadPool.globalInstance().start(worker)


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table

class ProductivityPanel(AsyncPanel):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind, self.rows, self.selected = kind, [], None
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search titles, content, projects and tags')
        self.filter = QComboBox()
        self.filter.addItems(['open','completed','archived','all'] if kind == 'task' else ['active','archived','all'])
        filters.addWidget(self.search)
        filters.addWidget(self.filter)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.table = _table(['ID', 'Title', 'Priority' if kind == 'task' else 'Category', 'Due' if kind == 'task' else 'Pinned', 'Project / tags'])
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.title = QLineEdit()
        self.body = QTextEdit()
        self.body.setMaximumHeight(110)
        self.project = QLineEdit()
        self.tags = QLineEdit()
        self.tags.setPlaceholderText('Comma-separated tags')
        self.category = QLineEdit()
        self.due = QLineEdit()
        self.due.setPlaceholderText('YYYY-MM-DD, or blank (does not schedule a reminder)')
        self.priority = QComboBox()
        self.priority.addItems(['low','normal','high','urgent'])
        self.priority.setCurrentText('normal')
        form.addRow('Title', self.title)
        form.addRow('Details' if kind == 'task' else 'Note', self.body)
        if kind == 'task':
            form.addRow('Priority', self.priority)
            form.addRow('Due date', self.due)
        else:
            form.addRow('Category', self.category)
        form.addRow('Project', self.project)
        form.addRow('Tags', self.tags)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for label, callback in [('New', self.new), ('Save', self.save),
                                ('Archive / restore', self.archive), ('Pin / unpin', self.pin)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        if kind == 'task':
            button = QPushButton('Complete / reopen')
            button.clicked.connect(self.complete)
            buttons.addWidget(button)
        self.undo_button = QPushButton('Undo last change')
        self.undo_button.clicked.connect(self.undo)
        buttons.addWidget(self.undo_button)
        layout.addLayout(buttons)
        self.status = QLabel('Loading...')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(250)
        self.debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.debounce.start())
        self.filter.currentTextChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self.select)
        self.refresh()

    def refresh(self, *args):
        from core.productivity_store import query_items
        query, status = self.search.text(), self.filter.currentText()
        self.background(lambda: query_items(self.kind, query, status), self.populate)

    def populate(self, rows):
        from core.undo import peek
        selected_id = getattr(self, '_select_id', None) or (self.selected['id'] if self.selected else None)
        self._select_id = None
        self.rows = rows
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [str(row['id']), row['title'], row['priority'] if self.kind == 'task' else row['category'],
                      row['due'] if self.kind == 'task' else ('Yes' if row['pinned'] else ''),
                      row['project'] + ' | ' + ', '.join(row['tags'])]
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.selected = None
        self.undo_button.setToolTip(peek() or 'Nothing to undo')
        self.status.setText(f'{len(rows)} {self.kind}s. Select a row to edit, or click New.')
        for index, row in enumerate(rows):
            if row['id'] == selected_id:
                self.table.setCurrentCell(index, 0)
                self.select()
                break
        else:
            if selected_id is not None:
                self.new()

    def select(self):
        index = self.table.currentRow()
        if not self.table.selectedItems() or not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        self.selected = dict(row)
        self.title.setText(row['title'])
        self.body.setPlainText(row['body'])
        self.project.setText(row['project'])
        self.tags.setText(', '.join(row['tags']))
        self.category.setText(row['category'])
        self.due.setText(row['due'])
        self.priority.setCurrentText(row['priority'])
        self.status.setText(f"Editing #{row['id']}; created {row['created'][:10]}, revision {row['version']}.")

    def new(self):
        self.selected = None
        self.table.clearSelection()
        for field in (self.title, self.project, self.tags, self.category, self.due):
            field.clear()
        self.body.clear()
        self.priority.setCurrentText('normal')
        self.status.setText('New item. Save when ready.')

    def apply(self, parameters):
        from core.productivity_store import operate
        def finished(result):
            self.status.setText(result)
            if result.startswith('Saved') or result.endswith('applied.'):
                match = re.search(r'#(\d+)', result)
                self._select_id = int(match[1]) if match else None
                self.refresh()
        self.background(lambda: operate(self.kind, parameters), finished)

    def save(self):
        p = {'action': 'edit' if self.selected else 'add', 'title': self.title.text(),
             'body': self.body.toPlainText(), 'project': self.project.text(), 'tags': self.tags.text()}
        if self.kind == 'task':
            p.update(due=self.due.text(), priority=self.priority.currentText())
        else:
            p['category'] = self.category.text()
        if self.selected:
            p.update(id=self.selected['id'], version=self.selected['version'])
        self.apply(p)

    def action(self, name):
        if not self.selected:
            self.status.setText('Select an item first.')
            return
        self.apply({'action': name, 'id': self.selected['id'], 'version': self.selected['version']})

    def archive(self):
        self.action('restore' if self.selected and self.selected['archived'] else 'archive')

    def pin(self):
        self.action('unpin' if self.selected and self.selected['pinned'] else 'pin')

    def complete(self):
        self.action('reopen' if self.selected and self.selected['done'] else 'complete')

    def undo(self):
        from core.undo import undo_last
        def finished(result):
            self.status.setText(result)
            if result.startswith('Undone:'):
                self.refresh()
        self.background(undo_last, finished)

class ReminderPanel(AsyncPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.selected = [], None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Native scheduled reminders run even while JARVIS is closed. Times below use the local computer timezone.'))
        self.filter = QComboBox()
        self.filter.addItems(['pending','completed','cancelled','failed','all'])
        layout.addWidget(self.filter)
        self.table = _table(['Message','Local time','Repeat','State','ID'])
        layout.addWidget(self.table, 1)
        self.message = QLineEdit()
        self.date = QLineEdit()
        self.date.setPlaceholderText('YYYY-MM-DD')
        self.time = QLineEdit()
        self.time.setPlaceholderText('HH:MM')
        self.repeat = QComboBox()
        self.repeat.addItems(['none','daily','weekly','weekdays'])
        self.minutes = QSpinBox()
        self.minutes.setRange(1,10080)
        self.minutes.setValue(20)
        form = QFormLayout()
        for label, widget in [('Message',self.message),('Date',self.date),('Time',self.time),('Repeat',self.repeat),('Snooze minutes',self.minutes)]:
            form.addRow(label,widget)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for label, callback in [('New',self.new),('Save',self.save),('Snooze',lambda:self.action('snooze')),('Cancel reminder',lambda:self.action('cancel')),('Complete',lambda:self.action('complete')),('Refresh',self.refresh),('History',self.history)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel('Loading...')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(100)
        layout.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self.select)
        self.filter.currentTextChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        from core.reminders import list_reminders
        status = self.filter.currentText()
        self.background(lambda:list_reminders(status), self.populate)

    def populate(self, rows):
        selected_id = getattr(self, '_select_id', None) or (self.selected['id'] if self.selected else None)
        self._select_id = None
        self.rows = rows
        self.selected = None
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            local = datetime.fromisoformat(row['due_at']).astimezone().strftime('%Y-%m-%d %H:%M')
            for j,value in enumerate((row['message'],local,row['recurrence'],row['state'],row['id'])):
                self.table.setItem(i,j,QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.status.setText(f'{len(rows)} reminders. Select a row to manage it.')
        for index, row in enumerate(rows):
            if row['id'] == selected_id:
                self.table.setCurrentCell(index, 0)
                self.select()
                break
        else:
            if selected_id is not None:
                self.new()

    def select(self):
        i = self.table.currentRow()
        if not self.table.selectedItems() or not 0 <= i < len(self.rows):
            return
        row = self.rows[i]
        self.selected = dict(row)
        due = datetime.fromisoformat(row['due_at']).astimezone()
        self.message.setText(row['message'])
        self.date.setText(due.strftime('%Y-%m-%d'))
        self.time.setText(due.strftime('%H:%M'))
        self.repeat.setCurrentText(row['recurrence'])
        self.details.setPlainText(row['error'] or 'Native job: '+row['native_id'])

    def new(self):
        self.selected = None
        self.table.clearSelection()
        self.message.clear()
        self.date.clear()
        self.time.clear()
        self.repeat.setCurrentText('none')
        self.status.setText('New reminder; choose a future local date and time.')

    def send(self, parameters):
        from actions.reminder import reminder
        def finished(result):
            self.status.setText(result)
            self.details.setPlainText(result)
            if not result.startswith('Reminder action failed:'):
                match = re.search(r'(?:ID: |Reminder )([0-9a-f]{32})', result)
                self._select_id = match[1] if match else None
                self.refresh()
        self.background(lambda:reminder(parameters), finished)

    def save(self):
        p = {'action':'edit' if self.selected else 'add', 'message':self.message.text(),
             'date':self.date.text(), 'time':self.time.text(), 'repeat':self.repeat.currentText()}
        if self.selected:
            p.update(id=self.selected['id'], generation=self.selected['generation'])
        self.send(p)

    def action(self, action):
        if not self.selected:
            self.status.setText('Select a reminder first.')
            return
        self.send({'action':action,'id':self.selected['id'],'generation':self.selected['generation'],'minutes':self.minutes.value()})

    def history(self):
        from core.reminders import history
        ident = self.selected['id'] if self.selected else ''
        self.background(lambda:history(ident), lambda rows:self.details.setPlainText('\n'.join(f"{r['at'][:19]} {r['event']} {r['detail']}" for r in rows) or 'No reminder history.'))

"""Desktop review of fixed project commands. Phone clients cannot write profiles."""
import subprocess
import sys
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton, QFileDialog,
    QMessageBox, QTableWidgetItem)
from core.productivity_panel import AsyncPanel, _table
from core.remote_store import remote_store


class RemoteProjectPanel(AsyncPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = remote_store()
        self.row, self.rows = {}, []
        layout = QVBoxLayout(self)
        note = QLabel("Approve a fixed build, test or server command for trusted phones.\n"
                      "Project code runs with your Windows account access, including its scripts and dependencies.\n"
                      "Cancellation stops its process tree; it does not undo files the command changed.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = _table(["Command", "Type", "Approved", "Revision"])
        self.table.setMaximumHeight(180)
        self.table.itemSelectionChanged.connect(self.load_selected)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.name = QLineEdit()
        self.cwd = QLineEdit()
        choose_folder = QPushButton("Choose project folder")
        choose_folder.clicked.connect(self.choose_folder)
        folder = QHBoxLayout()
        folder.addWidget(self.cwd)
        folder.addWidget(choose_folder)
        self.exe = QLineEdit(sys.executable)
        choose_exe = QPushButton("Choose executable")
        choose_exe.clicked.connect(self.choose_executable)
        executable = QHBoxLayout()
        executable.addWidget(self.exe)
        executable.addWidget(choose_exe)
        self.args = QPlainTextEdit()
        self.args.setPlaceholderText("One argument per line, without added quotes.\nExample Python tests:\n-m\npytest")
        self.args.setMaximumHeight(100)
        self.kind = QComboBox()
        self.kind.addItems(["task", "server"])
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 86400)
        self.timeout.setValue(300)
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("Not a server")
        self.approved = QCheckBox("Allow trusted phones with Projects permission to run this fixed command")
        form.addRow("Name", self.name)
        form.addRow("Project folder", folder)
        form.addRow("Executable", executable)
        form.addRow("Arguments (one per line)", self.args)
        form.addRow("Type", self.kind)
        form.addRow("Maximum seconds", self.timeout)
        form.addRow("Server port (loopback health check)", self.port)
        form.addRow(self.approved)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for label, callback in (("New", self.new), ("Review and save", self.save), ("Remove", self.remove), ("Refresh", self.refresh)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel("Task limit: 1 hour. Server limit: 24 hours. Bind development servers to 127.0.0.1.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the project directory")
        if folder:
            self.cwd.setText(folder)

    def choose_executable(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose an executable", "", "Executables (*.exe)")
        if path:
            self.exe.setText(path)

    def refresh(self):
        self.rows = self.store.profiles()
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            for column, value in enumerate((row["name"], row["kind"], "Yes" if row["enabled"] else "No", row["revision"])):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def load_selected(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.rows):
            return
        self.row = self.rows[index]
        row = self.row
        self.name.setText(row["name"])
        self.cwd.setText(row["cwd"])
        self.exe.setText(row["argv"][0])
        self.args.setPlainText("\n".join(row["argv"][1:]))
        self.kind.setCurrentText(row["kind"])
        self.timeout.setValue(row["timeout"])
        self.port.setValue(row["port"])
        self.approved.setChecked(row["enabled"])

    def new(self):
        self.row = {}
        self.table.clearSelection()
        self.name.clear()
        self.cwd.clear()
        self.exe.setText(sys.executable)
        self.args.clear()
        self.kind.setCurrentText("task")
        self.timeout.setValue(300)
        self.port.setValue(0)
        self.approved.setChecked(False)

    def save(self):
        row = {"name": self.name.text(), "cwd": self.cwd.text(),
               "argv": [self.exe.text(), *self.args.toPlainText().splitlines()],
               "kind": self.kind.currentText(), "timeout": self.timeout.value(),
               "port": self.port.value(), "enabled": self.approved.isChecked()}
        if self.row:
            row["id"] = self.row["id"]
        revision = self.row.get("revision", 0)
        if row["enabled"]:
            detail = (f"Folder: {row['cwd']}\nCommand: {subprocess.list2cmdline(row['argv'])}\n"
                      f"Limit: {row['timeout']} seconds\n\nTrusted phones may run this command without another prompt. "
                      "It runs project code with your account permissions. Terminal Deny still blocks it. "
                      "Only approve project code and dependencies you trust.")
            if QMessageBox.question(self, "Approve this fixed project command", detail) != QMessageBox.StandardButton.Yes:
                return
        def saved(value):
            self.refresh()
            index = next(i for i, r in enumerate(self.rows) if r["id"] == value["id"])
            self.table.selectRow(index)
            self.load_selected()
            self.status.setText("Saved. Approved for trusted phones." if value["enabled"] else "Saved without execution approval.")
        self.background(lambda: self.store.save_profile(row, revision), saved)

    def remove(self):
        if not self.row:
            return
        if QMessageBox.question(self, "Remove project command", "Remove this saved command? A running job using it will be stopped.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_profile(self.row["id"], self.row["revision"])
            self.new()
            self.refresh()
            self.status.setText("Project command removed.")
        except ValueError as exc:
            self.status.setText(str(exc))

"""Local-only approval surface for remote device trust and scopes."""
from pathlib import Path
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QCheckBox, QListWidget,
                            QPushButton, QMessageBox, QFileDialog, QHBoxLayout, QLineEdit, QGridLayout)
from memory.config_manager import load_api_keys, _patch_config
from core.remote_store import remote_store, CAPABILITIES


class RemotePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = remote_store()
        layout = QVBoxLayout(self)
        help_text = QLabel("Remote Command Center: open /remote on the phone.\n"
                           "Pair with the PC code, compare the full fingerprint, then trust below.\n"
                           "For access away from home, use a private network; do not forward router ports.\n"
                           "Screen sharing is capture-on-request. Camera and remote keyboard are unavailable.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        cfg = load_api_keys()
        self.address = QLineEdit(cfg.get("remote_private_url", ""))
        self.address.setPlaceholderText("Private HTTPS address, e.g. https://my-pc.tailnet.ts.net")
        layout.addWidget(self.address)
        save_address = QPushButton("Save private address for the pairing QR")
        save_address.clicked.connect(self.save_address)
        layout.addWidget(save_address)
        master = QCheckBox("Remote access master switch (start server requires restart)")
        master.setChecked(bool(cfg.get("remote_control_enabled", False)))
        master.toggled.connect(lambda v: _patch_config(remote_control_enabled=v))
        layout.addWidget(master)
        pairing = QCheckBox("Allow new pairing requests with a PC code")
        pairing.setChecked(bool(cfg.get("allow_device_pairing", False)))
        pairing.toggled.connect(lambda v: _patch_config(allow_device_pairing=v))
        layout.addWidget(pairing)
        layout.addWidget(QLabel("PC-wide feature switches (also require individual device permission):"))
        switches = QGridLayout()
        for index, cap in enumerate(CAPABILITIES):
            box = QCheckBox(cap.title())
            box.setChecked(bool(cfg.get("remote_features", {}).get(cap, False)))
            box.toggled.connect(lambda v, c=cap: self.feature(c, v))
            switches.addWidget(box, index // 5, index % 5)
        layout.addLayout(switches)
        self.devices = QListWidget()
        self.devices.currentRowChanged.connect(self.selected)
        layout.addWidget(self.devices)
        self.detail = QLabel("Select a device to review its fingerprint and permissions.")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        scopes = QGridLayout()
        self.scopes = {}
        for index, cap in enumerate(CAPABILITIES):
            box = QCheckBox(cap.title())
            scopes.addWidget(box, index // 5, index % 5)
            self.scopes[cap] = box
        layout.addLayout(scopes)
        buttons = QHBoxLayout()
        for label, callback in (("Trust / update permissions", self.trust), ("Revoke", self.revoke), ("Remove", self.remove), ("Refresh", self.refresh)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        layout.addWidget(self.folders)
        folders = QHBoxLayout()
        for label, callback in (("Share a folder for reading", self.add_folder), ("Stop sharing all folders", self.clear_folders)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            folders.addWidget(button)
        layout.addLayout(folders)
        self.refresh()

    def feature(self, cap, value):
        values = load_api_keys().get("remote_features", {})
        values[cap] = value
        _patch_config(remote_features=values)

    def save_address(self):
        from urllib.parse import urlsplit
        value = self.address.text().strip().rstrip("/")
        parsed = urlsplit(value)
        if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            QMessageBox.warning(self, "Invalid address", "Enter an HTTPS origin without a path, password, query or fragment.")
            return
        _patch_config(remote_private_url=value)

    def refresh(self):
        self.rows = self.store.devices()
        self.devices.clear()
        for row in self.rows:
            self.devices.addItem(f"{'TRUSTED' if row['trusted'] else 'NOT TRUSTED'} | {row['name']} | {row['platform']}")
        self.folders.setText("Shared folders: " + "; ".join(load_api_keys().get("remote_file_roots", [])))

    def current(self):
        index = self.devices.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def selected(self, _index):
        row = self.current()
        for cap, box in self.scopes.items():
            box.setChecked(bool(row and cap in row["capabilities"]))
        last_seen = datetime.fromtimestamp(row["last_seen"]).strftime("%Y-%m-%d %H:%M:%S") if row and row["last_seen"] else "Never"
        self.detail.setText((f"{row['name']}\nSHA-256: {row['fingerprint']}\nLast seen: {last_seen}") if row else "Select a device.")

    def trust(self):
        row = self.current()
        if not row:
            return
        caps = [c for c, box in self.scopes.items() if box.isChecked()]
        if QMessageBox.question(self, "Trust owner device", f"Did you compare this fingerprint on your phone?\n{row['fingerprint']}\n\nGrant: {', '.join(caps) or 'no capabilities'}\nAnyone who can unlock this browser profile can use these permissions.") != QMessageBox.StandardButton.Yes:
            return
        self.store.trust(row["id"], caps)
        self.refresh()

    def revoke(self):
        if self.current():
            self.store.revoke(self.current()["id"])
            self.refresh()

    def remove(self):
        if self.current():
            self.store.remove(self.current()["id"])
            self.refresh()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select a folder the trusted phone may read")
        if folder:
            roots = load_api_keys().get("remote_file_roots", [])
            resolved = str(Path(folder).resolve())
            if resolved not in roots:
                _patch_config(remote_file_roots=roots + [resolved])
            self.refresh()

    def clear_folders(self):
        _patch_config(remote_file_roots=[])
        self.refresh()

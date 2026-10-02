"""Qt control pages extracted from the legacy HUD."""
import json
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QWidget, QFormLayout,
    QComboBox, QLabel, QScrollArea, QTextEdit, QPushButton, QCheckBox, QMessageBox)
from memory.config_manager import load_api_keys, _patch_config
from core.permission_manager import manager, STATES
from core.diagnostics import history

class ControlPanel(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MARK LIV | Permissions, Privacy & Activity")
        self.resize(900, 650)
        self.setStyleSheet("""
            QDialog, QWidget { background: #0c1420; color: #d6e8f5; font-size: 13px; }
            QTabBar::tab { padding: 9px; background: #142237; }
            QTabBar::tab:selected { color: #63dcff; border-bottom: 2px solid #63dcff; }
            QComboBox, QTextEdit { background: #142237; border: 1px solid #30465e; padding: 5px; }
            QPushButton { background: #17354a; border: 1px solid #3584a4; padding: 7px; }
            QPushButton:hover { background: #245069; }
            QLabel { padding: 3px; }
        """)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.tabs = tabs
        from core.workspace_panel import WorkspacePanel
        try:
            workspace_area = QScrollArea()
            workspace_area.setWidgetResizable(True)
            self.workspaces = WorkspacePanel(tabs)
            workspace_area.setWidget(self.workspaces)
        except (OSError, ValueError):
            self.workspaces = None
            workspace_area = QLabel('Workspace storage is locked or unavailable for this Windows account.')
        tabs.addTab(workspace_area, 'Continue Work')
        permissions = QWidget()
        form = QFormLayout(permissions)
        form.addRow(QLabel("Voice codes can approve eligible local actions. Destructive/critical actions still require desktop confirmation."))
        for permission, state in manager.settings().items():
            combo = QComboBox()
            combo.addItems(STATES)
            combo.setCurrentText(state)
            combo.currentTextChanged.connect(lambda value, key=permission: manager.set(key, value))
            form.addRow(permission.replace("_", " ").title(), combo)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(permissions)
        tabs.addTab(scroll, "Permissions")
        privacy = QWidget()
        form = QFormLayout(privacy)
        cfg = load_api_keys()
        form.addRow(QLabel("Microphone audio uses cloud Gemini Live when connected.\nScreen/camera vision goes to cloud only after its permission gate.\nRemote and language changes require restart."))
        for key, label, default in (
            ("remote_control_enabled", "Remote control", False),
            ("lan_access_enabled", "Allow LAN clients (HTTPS)", False),
            ("allow_device_pairing", "Allow new device pairing", False),
            ("voice_confirmation_enabled", "Local voice confirmation codes (not speaker verification)", False),
            ("store_conversation_history", "Store session summaries", True),
            ("clipboard_monitoring", "Clipboard suggestions (local until sent)", False),
            ("automatic_memory", "Allow model to save memories", True),
            ("background_monitoring", "Background/proactive monitoring", False)):
            box = QCheckBox(label)
            box.setChecked(bool(cfg.get(key, default)))
            box.toggled.connect(lambda value, k=key: _patch_config(**{k: value}))
            form.addRow(box)
        mode = QComboBox()
        mode.addItems(["auto", "online", "offline"])
        mode.setCurrentText(cfg.get("assistant_mode", "auto"))
        mode.currentTextChanged.connect(lambda value: _patch_config(assistant_mode=value))
        form.addRow("Assistant mode (restart)", mode)
        language = QComboBox()
        language.addItems(["auto", "english", "urdu", "mixed"])
        language.setCurrentText(cfg.get("language", "auto"))
        language.currentTextChanged.connect(lambda value: _patch_config(language=value))
        form.addRow("Conversation language", language)
        tabs.addTab(privacy, "Privacy and Mode")
        from core.remote_panel import RemotePanel
        try:
            remote_panel = RemotePanel(tabs)
        except OSError:
            remote_panel = QLabel("Remote storage is locked for this Windows account.\nRun MARK LIV normally under the account that created it.")
        tabs.addTab(remote_panel, "Remote Devices")
        from core.remote_project_panel import RemoteProjectPanel
        try:
            remote_projects = QScrollArea()
            remote_projects.setWidgetResizable(True)
            remote_projects.setWidget(RemoteProjectPanel(tabs))
        except (OSError, ValueError):
            remote_projects = QLabel("Remote project storage is unavailable for this Windows account.")
        tabs.addTab(remote_projects, "Remote Projects")
        registry = getattr(parent, "action_registry", None)
        if registry is not None:
            skills = QWidget()
            form = QFormLayout(skills)
            form.addRow(QLabel("Changes apply to dispatch immediately. Reconnect Live to refresh its tool list."))
            for row in registry.list_for_ui():
                box = QCheckBox(row["name"])
                box.setChecked(row["enabled"])
                box.setToolTip(row["description"])
                def toggle(enabled, name=row["name"]):
                    values = load_api_keys().get("skills_enabled", {})
                    values[name] = enabled
                    _patch_config(skills_enabled=values)
                box.toggled.connect(toggle)
                form.addRow(box, QLabel(str(row["policy"]["risk"].value)))
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(skills)
            tabs.addTab(area, "Skills")
        from core.productivity_panel import ProductivityPanel, ReminderPanel
        tabs.addTab(ProductivityPanel('task', tabs), 'Tasks')
        tabs.addTab(ProductivityPanel('note', tabs), 'Notes')
        tabs.addTab(ReminderPanel(tabs), 'Reminders')
        self.add_editors(tabs)
        from core.automation_panel import AutomationPanel
        tabs.addTab(AutomationPanel(tabs), 'Automations')
        self.activity = QTextEdit()
        self.activity.setReadOnly(True)
        tabs.addTab(self.activity, "Activity and Latency")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def add_editors(self, tabs):
        from core.project_memory import projects
        from core.workflows import workflows
        definitions = [
            ("Projects", projects.list, projects.save,
             {"name": "My project", "path": "", "tech_stack": [], "pending_tasks": [], "notes": ""}),
            ("Workflows", workflows.list, workflows.save,
             {"name": "Open calculator", "steps": [{"name": "open_app", "parameters": {"app_name": "calculator"}}]})]
        for title, listing, saving, sample in definitions:
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.addWidget(QLabel("Select a record to edit, or clear its id to create a new record."))
            picker = QComboBox()
            layout.addWidget(picker)
            editor = QTextEdit()
            editor.setPlainText(json.dumps(sample, indent=2))
            layout.addWidget(editor)
            status = QLabel()
            def refresh(picker=picker, listing=listing, status=status):
                try:
                    picker.clear()
                    picker.addItem("New record", None)
                    for row in listing():
                        picker.addItem(row["name"], row)
                except Exception as exc:
                    status.setText(str(exc))
            picker.currentIndexChanged.connect(lambda index, p=picker, e=editor, default=sample: e.setPlainText(json.dumps(p.currentData() or default, indent=2)))
            def save(checked=False, e=editor, fn=saving, label=status, reload=refresh):
                try:
                    saved = fn(json.loads(e.toPlainText()))
                    e.setPlainText(json.dumps(saved, indent=2))
                    label.setText("Saved.")
                    reload()
                except Exception as exc:
                    label.setText(str(exc))
            button = QPushButton("Save record")
            button.clicked.connect(save)
            layout.addWidget(button)
            if title == "Workflows":
                run_button = QPushButton("Run selected workflow")
                def start(checked=False, p=picker, label=status):
                    try:
                        label.setText(workflows.run((p.currentData() or {})["id"]))
                    except Exception as exc:
                        label.setText(str(exc))
                run_button.clicked.connect(start)
                layout.addWidget(run_button)
                for command in ("pause", "resume", "stop"):
                    b = QPushButton(command.title())
                    b.clicked.connect(lambda checked=False, c=command, label=status: label.setText(workflows.control(c)))
                    layout.addWidget(b)
            if title == "Workflows":
                delete_button = QPushButton("Delete selected record")
                target = workflows
                def delete(checked=False, p=picker, t=target, label=status, reload=refresh):
                    row = p.currentData()
                    if row:
                        try:
                            t.delete(row["id"])
                            reload()
                            label.setText("Deleted.")
                        except Exception as exc:
                            label.setText(str(exc))
                delete_button.clicked.connect(delete)
                layout.addWidget(delete_button)
            layout.addWidget(status)
            refresh()
            tabs.addTab(widget, title)

    def open_tab(self, title):
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                self.tabs.setCurrentIndex(index)
                break

    def closeEvent(self, event):
        if self.workspaces and self.workspaces.dirty and not self.workspaces.discard():
            event.ignore()
            return
        super().closeEvent(event)

    def refresh(self):
        lines = [f"{r['timestamp'][11:19]}  {r['event']}  {r['action']}  {r['risk']}  {r['duration_ms']} ms  {r['status']}" for r in history()[-100:]]
        self.activity.setPlainText("\n".join(lines) or "No action metrics recorded yet.")

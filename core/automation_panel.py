"""Visual editor for the existing local automation engine."""
from copy import deepcopy
from datetime import datetime
import json
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QCheckBox, QComboBox, QDoubleSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QScrollArea, QStackedWidget, QTextEdit)
from core.automation import automations, NUMERIC
from core.productivity_panel import AsyncPanel, _table
from core.intent_router import APPS

FIELDS = {'battery_percent':'Battery (%)', 'charging':'Charger connected',
          'cpu_percent':'CPU (%)', 'ram_percent':'RAM (%)',
          'network_connected':'Network interface connected', 'process_name':'Foreground process'}
SETTINGS = ['volume_up', 'volume_down', 'mute', 'unmute', 'brightness_up',
            'brightness_down', 'lock_screen', 'show_desktop', 'pause_video']

def local_time(value):
    return datetime.fromisoformat(value).astimezone().strftime('%H:%M:%S') if value else '-'

class AutomationPanel(AsyncPanel):
    def __init__(self, parent=None, engine=None):
        super().__init__(parent)
        self.engine = engine or automations
        self.rows, self.states, self.selected = [], {}, None
        self._select_id, self._reload_editor = None, False
        layout = QVBoxLayout(self)
        self.monitor = QLabel()
        self.monitor.setWordWrap(True)
        layout.addWidget(self.monitor)
        self.table = _table(['Name', 'Enabled', 'Trigger', 'Last run', 'Next check', 'Status'])
        self.table.setMinimumHeight(110)
        layout.addWidget(self.table, 1)
        self.details = QLabel('Select an automation, or create a new one.')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        editor = QWidget()
        form = QFormLayout(editor)
        self.name = QLineEdit()
        self.enabled = QCheckBox('Enable automatic checks when background monitoring is on')
        form.addRow('Name', self.name)
        form.addRow(self.enabled)
        self.conditions = QTableWidget(0, 3)
        self.conditions.setHorizontalHeaderLabels(['State', 'Comparison', 'Value'])
        self.conditions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conditions.setMinimumHeight(100)
        self.conditions.setMaximumHeight(145)
        form.addRow('Trigger + conditions', self.conditions)
        buttons = QHBoxLayout()
        add = QPushButton('Add condition')
        add.clicked.connect(lambda:self.add_condition())
        remove = QPushButton('Remove selected condition')
        remove.clicked.connect(self.remove_condition)
        buttons.addWidget(add); buttons.addWidget(remove)
        form.addRow(buttons)
        self.duration, self.cooldown = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.duration, self.cooldown):
            spin.setRange(0, 86400)
            spin.setDecimals(1)
            spin.setSuffix(' seconds')
        form.addRow('Hold trigger for', self.duration)
        form.addRow('Minimum time between runs', self.cooldown)
        self.action = QComboBox()
        for label, key in [('Show notification','notify'),('Open application','open_app'),
                           ('Read computer status','computer_context'),('Computer setting','computer_settings'),
                           ('Advanced action','advanced')]:
            self.action.addItem(label, key)
        form.addRow('Action', self.action)
        self.options = QStackedWidget()
        self.message, self.app, self.setting = QLineEdit(), QComboBox(), QComboBox()
        self.message.setPlaceholderText('Text shown in the JARVIS activity log')
        self.app.addItems(sorted(set(APPS.values())))
        self.setting.addItems(SETTINGS)
        for widget in (self.message, self.app, QLabel('Read the current system status.'), self.setting):
            self.options.addWidget(widget)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        self.action_name, self.parameters = QLineEdit(), QTextEdit()
        self.parameters.setMaximumHeight(80)
        advanced_form.addRow('Tool name', self.action_name)
        advanced_form.addRow('Parameters JSON', self.parameters)
        self.options.addWidget(advanced)
        self.action.currentIndexChanged.connect(self.options.setCurrentIndex)
        form.addRow('Action details', self.options)
        scroll.setWidget(editor)
        layout.addWidget(scroll, 2)
        buttons = QHBoxLayout()
        for label, callback in [('New', self.new), ('Save', self.save), ('Enable / disable', self.toggle),
                                ('Run now', self.run_now), ('Delete', self.delete), ('Refresh', self.reload)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        hint = QLabel('Run now uses the saved action and skips trigger/duration. Enabled, cooldown and permission checks still apply.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table.itemSelectionChanged.connect(self.select)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(lambda:self.refresh() if self.isVisible() and not self.busy else None)
        self.timer.start()
        self.new()
        self.refresh()

    def add_condition(self, condition=None):
        if self.conditions.rowCount() >= 11:
            self.status.setText('At most ten additional conditions are supported.')
            return
        c = condition or {'field':'charging', 'op':'eq', 'value':False}
        index = self.conditions.rowCount()
        self.conditions.insertRow(index)
        field, comparison, value = QComboBox(), QComboBox(), QLineEdit()
        for key, label in FIELDS.items():
            field.addItem(label, key)
        field.setCurrentIndex(field.findData(c['field']))
        for label, key in [('Less than','lt'),('Greater than','gt'),('Equals','eq')]:
            comparison.addItem(label, key)
        comparison.setCurrentIndex(comparison.findData(c['op']))
        value.setText(str(c['value']).lower() if type(c['value']) is bool else str(c['value']))
        value.setPlaceholderText('Number, true/false, or process name')
        for column, widget in enumerate((field, comparison, value)):
            self.conditions.setCellWidget(index, column, widget)
        self.conditions.setVerticalHeaderItem(index, QTableWidgetItem('WHEN' if index == 0 else 'AND'))

    def remove_condition(self):
        row = self.conditions.currentRow()
        if row > 0:
            self.conditions.removeRow(row)
        else:
            self.status.setText('The first trigger cannot be removed. Select an additional condition.')

    def new(self):
        self.selected = None
        self.table.clearSelection()
        self.name.clear()
        self.enabled.setChecked(False)
        self.conditions.setRowCount(0)
        self.add_condition({'field':'battery_percent','op':'lt','value':20})
        self.duration.setValue(0); self.cooldown.setValue(60)
        self.action.setCurrentIndex(0); self.message.clear()
        self.parameters.setPlainText('{}'); self.action_name.clear()
        self.status.setText('New rule. Save it before enabling or running it.')

    def select(self):
        i = self.table.currentRow()
        if self.table.selectedItems() and 0 <= i < len(self.rows):
            self.load_editor(self.rows[i])

    def load_editor(self, row):
        self.selected = deepcopy(row)
        self.name.setText(row['name']); self.enabled.setChecked(row['enabled'])
        self.conditions.setRowCount(0)
        for condition in [row['trigger']] + row['conditions']:
            self.add_condition(condition)
        self.duration.setValue(row['duration']); self.cooldown.setValue(row['cooldown'])
        action, parameters = row['action']['name'], row['action']['parameters']
        simple = (action == 'notify' and set(parameters) <= {'text'} or
                  action == 'open_app' and set(parameters) <= {'app_name'} and parameters.get('app_name') in set(APPS.values()) or
                  action == 'computer_context' and not parameters or
                  action == 'computer_settings' and set(parameters) <= {'action'} and parameters.get('action') in SETTINGS)
        index = self.action.findData(action) if simple else self.action.findData('advanced')
        self.action.setCurrentIndex(index)
        self.message.setText(parameters.get('text', 'Automation triggered') if action == 'notify' else '')
        self.app.setCurrentText(str(parameters.get('app_name', 'calculator')))
        self.setting.setCurrentText(str(parameters.get('action', 'volume_down')))
        self.action_name.setText(action); self.parameters.setPlainText(json.dumps(parameters, indent=2))
        self.show_details(row['id'])
        self.status.setText('Editing a saved rule. Save changes before using Run now.')

    def show_details(self, ident):
        state = self.states.get(ident, {})
        self.details.setText('Trigger: ' + state.get('trigger_state', 'waiting') + ' | ' +
                             (state.get('error') or state.get('result') or 'No runs in this session.'))

    def definition(self):
        conditions = []
        for row in range(self.conditions.rowCount()):
            field = self.conditions.cellWidget(row, 0).currentData()
            op = self.conditions.cellWidget(row, 1).currentData()
            raw = self.conditions.cellWidget(row, 2).text().strip()
            if field in NUMERIC:
                try:
                    value = float(raw)
                except ValueError:
                    raise ValueError('Percentage conditions require a number.') from None
            elif field in ('charging','network_connected'):
                if raw.casefold() not in ('true','false'):
                    raise ValueError('Use true or false for charging/network conditions.')
                value = raw.casefold() == 'true'
            else:
                value = raw
            conditions.append({'field':field,'op':op,'value':value})
        key = self.action.currentData()
        if key == 'notify':
            parameters = {'text':self.message.text()}
        elif key == 'open_app':
            parameters = {'app_name':self.app.currentText()}
        elif key == 'computer_settings':
            parameters = {'action':self.setting.currentText()}
        elif key == 'computer_context':
            parameters = {}
        else:
            key, parameters = self.action_name.text().strip(), json.loads(self.parameters.toPlainText())
        result = {'name':self.name.text(), 'enabled':self.enabled.isChecked(),
                  'trigger':conditions[0], 'conditions':conditions[1:],
                  'duration':self.duration.value(), 'cooldown':self.cooldown.value(),
                  'action':{'name':key, 'parameters':parameters}}
        if self.selected:
            result.update(id=self.selected['id'], revision=self.selected['revision'])
        return result

    def refresh(self):
        self.background(self.engine.describe, self.populate)

    def reload(self):
        self._reload_editor = True
        self.refresh()

    def populate(self, snapshot):
        selected_id = self._select_id or (self.selected['id'] if self.selected else None)
        self._select_id = None
        self.rows, self.states = snapshot['rules'], snapshot['status']
        self.monitor.setText(('Background checks enabled (about every 5 seconds).' if snapshot['monitoring'] else
                              'Background checks paused. Enable Background monitoring in Privacy; Run now remains available.') +
                             (' ' + snapshot['monitor_error'] if snapshot['monitor_error'] else ''))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            state, trigger = self.states[row['id']], row['trigger']
            values = [row['name'], 'Yes' if row['enabled'] else 'No',
                      f"{FIELDS[trigger['field']]} {trigger['op']} {trigger['value']}",
                      local_time(state['last_run_at']), local_time(state['next_check']), state['status']]
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
            if row['id'] == selected_id:
                self.table.setCurrentCell(i, 0)
        self.table.blockSignals(False)
        found = next((r for r in self.rows if r['id'] == selected_id), None)
        if found and self._reload_editor:
            self.load_editor(found)
        elif selected_id and not found:
            self.new()
        if found:
            self.show_details(found['id'])
        self._reload_editor = False

    def save(self):
        try:
            definition = self.definition()
        except (ValueError, TypeError) as exc:
            self.status.setText(str(exc))
            return
        def done(row):
            self._select_id, self._reload_editor = row['id'], True
            self.status.setText('Saved.')
            self.refresh()
        self.background(lambda:self.engine.save(definition), done)

    def operation(self, action):
        if not self.selected:
            self.status.setText('Select a saved automation first.')
            return
        row = deepcopy(self.selected)
        def perform():
            if action == 'toggle':
                return self.engine.set_enabled(row['id'], not row['enabled'], row['revision'])
            if action == 'delete':
                return self.engine.delete(row['id'], row['revision'])
            return self.engine.run_now(row['id'], row['revision'])
        def done(result):
            self.status.setText(json.dumps(result) if action == 'run' else ('Deleted.' if action == 'delete' else 'Updated.'))
            self._reload_editor = True
            self.refresh()
        self.background(perform, done)

    def toggle(self):
        self.operation('toggle')

    def delete(self):
        self.operation('delete')

    def run_now(self):
        self.operation('run')

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from core.automation import AutomationEngine
from core.action_loader import ActionRecord, ActionRegistry
from core.permission_manager import PermissionManager
from actions import automation_manager
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool
from core.automation_panel import AutomationPanel

def definition(**changes):
    return {'name':'Low battery', 'trigger':{'field':'battery_percent','op':'lt','value':20},
            'conditions':[{'field':'charging','op':'eq','value':False}],
            'action':{'name':'notify','parameters':{'text':'Battery is low'}},
            'duration':0, 'cooldown':60, 'enabled':True, **changes}

class AutomationUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'rules.json'
        self.clock = 100
        self.engine = AutomationEngine(self.path, lambda:self.clock)
        self.engine.dispatch = Mock(return_value='Notification shown.')

    def test_legacy_definition_loads_and_gains_revision_on_edit(self):
        row = definition(id='a'*32)
        self.path.write_text(json.dumps([row]))
        loaded = self.engine.list()[0]
        self.assertEqual(loaded['revision'], 0)
        saved = self.engine.save({**loaded,'name':'Battery warning'})
        self.assertEqual(saved['revision'], 1)
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            self.engine.save(loaded)
        self.assertEqual(self.engine.get(row['id'])['name'], 'Battery warning')

    def test_invalid_definitions_do_not_replace_existing_file(self):
        self.engine.save(definition())
        before = self.path.read_bytes()
        for changes in ({'duration':True}, {'cooldown':float('inf')}, {'enabled':'false'},
                        {'conditions':'invalid'}, {'trigger':{'field':'cpu_percent','op':'gt','value':'90'}},
                        {'trigger':{'field':'charging','op':'gt','value':True}},
                        {'action':{'name':'notify','parameters':{'text':''}}},
                        {'action':{'name':'computer_settings','parameters':{'action':'shutdown'}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.engine.save(definition(**changes))
            self.assertEqual(self.path.read_bytes(), before)

    def test_tampered_persisted_action_is_revalidated_before_execution(self):
        row = self.engine.save(definition())
        row['action'] = {'name':'dev_agent','parameters':{}}
        self.path.write_text(json.dumps([row]))
        with self.assertRaises(ValueError):
            self.engine.run_now(row['id'])
        self.engine.dispatch.assert_not_called()

    def test_size_limit_preserves_readable_existing_rules(self):
        row = self.engine.save(definition())
        before = self.path.read_bytes()
        with patch('core.automation.MAX_FILE_BYTES', len(before) + 10):
            with self.assertRaisesRegex(ValueError, 'exceed'):
                self.engine.save(definition(name='Another rule'))
            self.assertEqual(self.engine.get(row['id'])['name'], row['name'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_run_now_skips_conditions_but_honors_enabled_cooldown_revision(self):
        row = self.engine.save(definition(duration=300))
        self.assertEqual(self.engine.run_now(row['id'])['status'], 'returned')
        with self.assertRaisesRegex(ValueError, 'cooling'):
            self.engine.run_now(row['id'])
        disabled = self.engine.set_enabled(row['id'], False, row['revision'])
        self.clock += 100
        with self.assertRaisesRegex(ValueError, 'Enable'):
            self.engine.run_now(row['id'])
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            self.engine.run_now(row['id'], row['revision'])
        self.engine.set_enabled(row['id'], True, disabled['revision'])
        self.engine.run_now(row['id'])
        self.assertEqual(self.engine.dispatch.call_count, 2)

    def test_runtime_snapshot_is_detached_and_shows_monitoring(self):
        row = self.engine.save(definition())
        self.engine.set_monitoring(True)
        snapshot = self.engine.describe()
        self.assertIsNotNone(snapshot['status'][row['id']]['next_check'])
        snapshot['status'][row['id']]['running'] = True
        snapshot['rules'][0]['enabled'] = False
        self.assertFalse(self.engine.runtime[row['id']]['running'])
        self.assertTrue(self.engine.get(row['id'])['enabled'])
        self.engine.set_monitoring(False)
        self.assertIsNone(self.engine.describe()['status'][row['id']]['next_check'])

    def test_paused_monitoring_discards_accumulated_duration(self):
        row = self.engine.save(definition(duration=30))
        state = {'battery_percent':10, 'charging':False}
        self.engine.tick(state)
        self.clock += 20
        self.engine.set_monitoring(False)
        self.clock += 100
        self.engine.set_monitoring(True)
        self.engine.tick(state)
        self.engine.dispatch.assert_not_called()
        self.clock += 31
        self.engine.tick(state)
        self.engine.dispatch.assert_called_once()
        self.assertEqual(self.engine.runtime[row['id']]['source'], 'trigger')

    def test_concurrent_manual_and_tick_calls_cannot_overlap(self):
        row = self.engine.save(definition(cooldown=0))
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def action(*args):
            entered.set()
            release.wait(5)
            return 'Done'
        self.engine.dispatch.side_effect = action
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.engine.run_now, row['id'])
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(ValueError, 'already running'):
                self.engine.run_now(row['id'])
            with self.assertRaisesRegex(ValueError, 'running'):
                self.engine.delete(row['id'])
            self.engine.tick({'battery_percent':10,'charging':False})
            release.set()
            self.assertEqual(future.result(timeout=2)['status'], 'returned')
        self.engine.dispatch.assert_called_once()

    def test_failures_and_confirmation_are_visible_without_retry_storm(self):
        row = self.engine.save(definition())
        self.engine.dispatch.side_effect = OSError('backend unavailable')
        state = {'battery_percent':10,'charging':False}
        self.engine.tick(state)
        self.clock += 100
        self.engine.tick(state)
        self.engine.dispatch.assert_called_once()
        self.assertEqual(self.engine.runtime[row['id']]['error'], 'backend unavailable')
        self.engine.dispatch.side_effect = None
        self.engine.dispatch.return_value = 'Waiting for confirmation.'
        result = self.engine.run_now(row['id'])
        self.assertEqual(result['status'], 'confirmation_requested')

    def test_turning_monitoring_off_stops_remaining_rules_in_batch(self):
        self.engine.save(definition(name='First'))
        self.engine.save(definition(name='Second'))
        active = [True]
        def dispatch(*args):
            active[0] = False
            return 'Done'
        self.engine.dispatch.side_effect = dispatch
        self.engine.tick({'battery_percent':10,'charging':False}, lambda:active[0])
        self.engine.dispatch.assert_called_once()
        self.assertFalse(self.engine.monitoring)

    def test_real_registry_permission_denial_never_calls_action(self):
        permission = PermissionManager(Path(self.temp.name)/'permissions.json')
        permission.set('open_app','Deny')
        handler = Mock(return_value='Opened')
        registry = ActionRegistry({'open_app':ActionRecord(name='open_app', handler=handler, valid=True)}, lambda msg:None)
        row = self.engine.save(definition(action={'name':'open_app','parameters':{'app_name':'calculator'}}))
        self.engine.dispatch = registry.run
        with patch('core.permission_manager.manager', permission), patch.object(registry, 'enabled', return_value=True):
            result = self.engine.run_now(row['id'])
        handler.assert_not_called()
        self.assertEqual(result['status'], 'blocked_or_failed')
        self.assertIn('denied', result['error'])

    def test_tool_enable_disable_run_and_unknown_action(self):
        row = self.engine.save(definition(enabled=False))
        with patch.object(automation_manager, 'automations', self.engine):
            self.assertIn('true', automation_manager.run({'action':'enable','id':row['id']}))
            self.assertIn('returned', automation_manager.run({'action':'run_now','id':row['id']}))
            self.assertIn('false', automation_manager.run({'action':'disable','id':row['id']}))
            self.assertIn('Unknown', automation_manager.run({'action':'invented'}))

    def test_missing_and_stale_deletes_are_not_reported_successful(self):
        row = self.engine.save(definition())
        self.engine.save({**row, 'name':'Edited'})
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            self.engine.delete(row['id'], row['revision'])
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.engine.delete('b'*32)

    def test_context_content_is_not_misclassified_as_action_failure(self):
        row = self.engine.save(definition(action={'name':'computer_context','parameters':{}}))
        self.engine.dispatch.return_value = '{"window_title":"Error log and confirmation notes"}'
        self.assertEqual(self.engine.run_now(row['id'])['status'], 'returned')

class AutomationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = AutomationEngine(Path(self.temp.name)/'rules.json')
        self.engine.dispatch = Mock(return_value='Notification shown.')
        self.panel = AutomationPanel(engine=self.engine)
        self.panel.timer.stop()
        self.addCleanup(self.close_panel)
        self.wait()

    def wait(self):
        deadline = time.monotonic()+8
        while self.panel.busy and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.005)
        self.assertFalse(self.panel.busy)
        self.app.processEvents()

    def close_panel(self):
        self.wait()
        self.panel.close(); self.panel.deleteLater()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def create(self):
        self.panel.name.setText('Battery warning')
        self.panel.message.setText('Connect charger')
        self.panel.add_condition()
        self.panel.save(); self.wait()

    def test_visual_save_enable_run_disable_delete(self):
        self.create()
        row = self.panel.selected
        self.assertFalse(row['enabled'])
        self.assertEqual(row['conditions'][0]['value'], False)
        self.panel.toggle(); self.wait()
        self.assertTrue(self.panel.selected['enabled'])
        self.panel.run_now(); self.wait()
        self.engine.dispatch.assert_called_once_with('notify', {'text':'Connect charger'})
        self.assertIn('Notification shown', self.panel.details.text())
        self.panel.toggle(); self.wait()
        self.assertFalse(self.panel.selected['enabled'])
        self.panel.delete(); self.wait()
        self.assertEqual(self.engine.list(), [])
        self.assertIsNone(self.panel.selected)

    def test_periodic_refresh_keeps_unsaved_form_and_stale_edit_is_rejected(self):
        self.create()
        original = deepcopy(self.panel.selected)
        self.panel.name.setText('Unsaved local title')
        self.engine.save({**original,'name':'Changed externally'})
        self.panel.refresh(); self.wait()
        self.assertEqual(self.panel.name.text(), 'Unsaved local title')
        self.panel.save(); self.wait()
        self.assertIn('changed elsewhere', self.panel.status.text())
        self.panel.reload(); self.wait()
        self.assertEqual(self.panel.name.text(), 'Changed externally')

    def test_new_and_invalid_condition_do_not_overwrite_saved_rule(self):
        self.create()
        self.panel.new()
        self.assertIsNone(self.panel.selected)
        self.panel.name.setText('Invalid')
        self.panel.message.setText('Message')
        self.panel.conditions.cellWidget(0,2).setText('not a number')
        self.panel.save(); self.wait()
        self.assertIn('number', self.panel.status.text())
        self.assertEqual(len(self.engine.list()),1)

    def test_computer_status_option_uses_discovered_action(self):
        self.panel.action.setCurrentIndex(self.panel.action.findData('computer_context'))
        self.assertEqual(self.panel.definition()['action'], {'name':'computer_context','parameters':{}})

if __name__ == '__main__':
    unittest.main()

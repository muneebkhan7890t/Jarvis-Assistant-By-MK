import ast
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.permission_manager import PermissionManager, policy_for
from core.remote_store import RemoteStore
from core.workspaces import WorkspaceStore, validate


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.permissions = PermissionManager(self.root / 'permissions.json')
        self.encrypted = RemoteStore(self.root / 'remote.db')
        self.store = WorkspaceStore(self.encrypted, self.permissions)
        self.value = {'name': 'Example', 'folder': str(self.root), 'notes': 'private stopping point',
                      'next_steps': 'Fix the fixture\nReview changes', 'apps': ['vscode'], 'urls': ['https://example.com/docs']}

    def test_encrypted_roundtrip_revision_conflicts_and_delete_preserves_folder(self):
        row = self.store.save(self.value)
        reopened = WorkspaceStore(self.encrypted, self.permissions)
        self.assertEqual(reopened.get(row['id'])['notes'], self.value['notes'])
        self.assertNotIn(self.value['notes'].encode(), self.encrypted.path.read_bytes())
        changed = reopened.save({**row, 'notes': 'new checkpoint'}, row['revision'])
        with self.assertRaises(ValueError):
            self.store.save(row, row['revision'])
        with self.assertRaises(ValueError):
            self.store.delete(row['id'], row['revision'])
        self.store.delete(row['id'], changed['revision'])
        self.assertEqual(self.store.list(), [])
        self.assertTrue(self.root.is_dir())

    def test_invalid_paths_apps_urls_and_limits(self):
        for change in ({'folder': '.'}, {'folder': str(self.root.anchor)}, {'folder': '//server/share'},
                       {'apps': ['powershell']}, {'apps': ['vscode --command']},
                       {'urls': ['file:///C:/secret']}, {'urls': ['javascript:alert(1)']},
                       {'urls': ['https://user:password@example.com']}, {'urls': ['https://example.com:99999']},
                       {'urls': ['https://example.com'] * 9}, {'notes': 'a' * 10001}):
            with self.assertRaises((ValueError, OSError)):
                validate({**self.value, **change})
        self.assertEqual(validate({**self.value, 'folder': '', 'apps': [], 'urls': []})['folder'], '')

    def test_reviewed_plan_returns_each_real_adapter_result_and_persists_receipt(self):
        row = self.store.save(self.value)
        calls = []
        result = self.store.restore_reviewed(self.store.preview(row['id']), lambda item: calls.append(item) or 'Adapter accepted the open request')
        self.assertEqual([item['kind'] for item in calls], ['folder', 'app', 'url'])
        self.assertEqual(result['status'], 'returned / unverified')
        self.assertEqual(self.store.latest_run(row['id'])['outcomes'], result['outcomes'])
        self.assertEqual(self.store.get(row['id'])['revision'], row['revision'])

    def test_tampered_or_stale_review_does_not_open_anything(self):
        row = self.store.save(self.value)
        plan = self.store.preview(row['id'])
        forged = {**plan, 'items': [{'kind': 'app', 'value': 'powershell'}]}
        with self.assertRaises(ValueError):
            self.store.restore_reviewed(forged, lambda item: self.fail('opened'))
        self.store.save({**row, 'notes': 'changed'}, row['revision'])
        with self.assertRaises(ValueError):
            self.store.restore_reviewed(plan, lambda item: self.fail('opened'))

    def test_permission_denial_and_mid_run_change_stop_reopening(self):
        row = self.store.save(self.value)
        plan = self.store.preview(row['id'])
        self.permissions.set('browser', 'Deny')
        with self.assertRaises(PermissionError):
            self.store.restore_reviewed(plan, lambda item: self.fail('opened'))
        self.permissions.set('browser', 'Ask')
        calls = []
        def opener(item):
            calls.append(item)
            self.permissions.set('open_app', 'Deny')
            return 'Folder request returned'
        result = self.store.restore_reviewed(plan, opener)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'stopped with error')
        self.permissions.set('memory', 'Deny')
        with self.assertRaises(PermissionError):
            self.store.list()

    def test_missing_folder_and_adapter_failure_are_not_success(self):
        folder = self.root / 'project'
        folder.mkdir()
        row = self.store.save({**self.value, 'folder': str(folder)})
        folder.rmdir()
        with self.assertRaises(FileNotFoundError):
            self.store.preview(row['id'])
        self.assertEqual(self.store.get(row['id'])['notes'], self.value['notes'])
        folder.mkdir()
        calls = []
        result = self.store.restore_reviewed(self.store.preview(row['id']), lambda item: calls.append(item) or 'Could not open folder')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'stopped with error')

    def test_typed_continue_opens_local_page_without_cloud_or_execution(self):
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_on_text_command')
        module = ast.Module(body=[method], type_ignores=[])
        env = {}
        exec(compile(ast.fix_missing_locations(module), 'main.py', 'exec'), env)
        opened = []
        instance = SimpleNamespace(ui=SimpleNamespace(_open_workspace_panel=lambda: opened.append(True)))
        for text in ('Continue my work', 'resume my work!', 'mera kaam jari rakho'):
            env['_on_text_command'](instance, text)
        self.assertEqual(len(opened), 3)

    def test_policy_uses_all_selected_categories_and_requires_confirmation(self):
        row = self.store.save(self.value)
        policy = policy_for('workspace_restore', self.store.preview(row['id']))
        self.assertEqual(set(policy.permissions), {'memory', 'file_read', 'open_app', 'browser'})
        self.assertTrue(policy.confirmation_required)

    def test_ui_save_review_cancel_restore_dirty_guard_and_delete(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        from core.workspace_panel import WorkspacePanel
        app = QApplication.instance() or QApplication([])
        panel = WorkspacePanel(store=self.store)
        def settle():
            for _ in range(300):
                app.processEvents()
                if not panel.busy:
                    break
                time.sleep(.01)
            self.assertFalse(panel.busy)
        settle()
        panel.name.setText('Fixture checkpoint')
        panel.folder.setText(str(self.root))
        panel.notes.setPlainText('Stopped after tests')
        panel.steps.setPlainText('Review the next change')
        panel.save()
        settle()
        self.assertEqual(len(self.store.list()), 1)
        with patch.object(panel, 'question', return_value=False), patch.object(self.store, 'restore_reviewed') as restore:
            panel.resume()
            restore.assert_not_called()
        with patch.object(panel, 'question', return_value=True), patch.object(self.store, 'restore_reviewed', return_value={'status': 'returned / unverified', 'outcomes': []}) as restore:
            panel.resume()
            settle()
            restore.assert_called_once()
        panel.notes.setPlainText('Unsaved change')
        panel.resume()
        self.assertIn('Save this checkpoint', panel.status.text())
        with patch.object(panel, 'question', return_value=False):
            panel.refresh()
        self.assertEqual(panel.notes.toPlainText(), 'Unsaved change')
        with patch.object(panel, 'question', return_value=True):
            panel.remove()
            settle()
        self.assertEqual(self.store.list(), [])
        panel.close()

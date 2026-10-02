import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import productivity_store as store
from core.action_loader import discover_actions
from memory import config_manager
from actions import notes, task_manager, reminder

ROOT = Path(__file__).resolve().parents[1]


class ProductivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch.object(store, 'DB_PATH', Path(self.temp.name) / 'items.db')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_task_lifecycle(self):
        self.assertIn('#1', task_manager.run({'action': 'add', 'title': 'Finish project', 'due': '2030-12-01'}))
        self.assertIn('Finish project', task_manager.run({'action': 'list'}))
        task_manager.run({'action': 'complete', 'id': 1})
        self.assertEqual('No matching tasks.', task_manager.run({'action': 'list'}))
        self.assertIn('completed', task_manager.run({'action': 'list', 'status': 'completed'}))
        task_manager.run({'action': 'reopen', 'id': 1})
        task_manager.run({'action': 'archive', 'id': 1})
        self.assertEqual('No matching tasks.', task_manager.run({'action': 'list'}))
        task_manager.run({'action': 'restore', 'id': 1})
        self.assertIn('Finish project', task_manager.run({'action': 'list'}))

    def test_notes_search_read_and_persistence(self):
        notes.run({'action': 'add', 'title': 'Ideas', 'body': 'Urdu اردو and Straße'})
        # Fresh module import still opens the same file; no in-memory task cache.
        db_path = store.DB_PATH
        importlib.reload(store)
        store.DB_PATH = db_path
        self.assertIn('Ideas', notes.run({'action': 'search', 'query': 'STRASSE'}))
        self.assertIn('اردو', notes.run({'action': 'read', 'id': 1}))
        notes.run({'action': 'archive', 'id': 1})
        self.assertEqual('No matching notes.', notes.run({'action': 'list'}))
        notes.run({'action': 'restore', 'id': 1})
        self.assertIn('Ideas', notes.run({'action': 'list'}))

    def test_task_cannot_modify_note(self):
        notes.run({'action': 'add', 'title': 'Private', 'body': 'Example'})
        self.assertIn('not found', task_manager.run({'action': 'complete', 'id': 1}))
        self.assertIn('[active]', notes.run({'action': 'read', 'id': 1}))

    def test_validation(self):
        for params in ({'action': 'add'}, {'action': 'add', 'title': 7},
                       {'action': 'add', 'title': 'x', 'due': '2030-02-30'},
                       {'action': 'add', 'title': 'x', 'due': '20301201'},
                       {'action': 'complete', 'id': True},
                       {'action': 'list', 'status': 'wrong'},
                       {'action': 'list', 'offset': -1}):
            self.assertNotIn('Saved', task_manager.run(params))
        self.assertIn('provide body', notes.run({'action': 'add', 'title': 'x'}))
        self.assertEqual('No matching tasks.', task_manager.run({'action': 'list'}))

    def test_search_treats_sql_as_data(self):
        notes.run({'action': 'add', 'title': "O'Brien", 'body': "100% _ ' ; DROP TABLE items;"})
        self.assertIn("O'Brien", notes.run({'action': 'search', 'query': '100% _'}))
        self.assertIn("O'Brien", notes.run({'action': 'list'}))

    def test_parallel_writes_and_pagination(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda i: task_manager.run({'action': 'add', 'title': f'Task {i}'}), range(25)))
        self.assertTrue(all('Saved task' in r for r in results))
        self.assertEqual(len(set(r.split(':')[0] for r in results)), 25)
        self.assertIn('offset=20', task_manager.run({'action': 'list'}))
        self.assertEqual(len(task_manager.run({'action': 'list', 'offset': 20}).splitlines()), 5)

    def test_unavailable_storage(self):
        with patch.object(store, 'DB_PATH', Path(self.temp.name)):
            self.assertIn('unavailable', notes.run({'action': 'list'}))

    def test_discovery_and_dispatch(self):
        folder = Path(self.temp.name) / 'actions'
        folder.mkdir()
        for name in ('notes.py', 'task_manager.py'):
            (folder / name).write_bytes((ROOT / 'actions' / name).read_bytes())
        registry = discover_actions(folder, logger=lambda _: None)
        self.assertEqual(registry.names(), {'notes', 'task_manager'})
        self.assertIn('Saved', registry.run('notes', {'action': 'add', 'title': 'Test', 'body': 'Text'}))
        self.assertEqual(len(registry.get_tool_declarations()), 2)


class ConfigurationTests(unittest.TestCase):
    def test_env_overrides_file(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ' environment-key '}), patch.object(config_manager, 'load_api_keys', return_value={'gemini_api_key': 'file-key'}):
            self.assertEqual(config_manager.get_gemini_key(), 'environment-key')

    def test_empty_env_falls_back_to_file(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ' '}), patch.object(config_manager, 'load_api_keys', return_value={'gemini_api_key': ' file-key '}):
            self.assertEqual(config_manager.get_gemini_key(), 'file-key')

    def test_malformed_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api_keys.json'
            with patch.object(config_manager, 'CONFIG_FILE', path), patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                for data in ('[]', 'null', '{broken'):
                    path.write_text(data)
                    self.assertEqual(config_manager.load_api_keys(), {})
                    self.assertIsNone(config_manager.get_gemini_key())


class RegressionTests(unittest.TestCase):
    def test_same_minute_reminders_have_distinct_names(self):
        target = datetime.now() + timedelta(days=1)
        params = {'date': target.strftime('%Y-%m-%d'), 'time': '12:00', 'message': 'Test'}
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DB_PATH', Path(folder) / 'productivity.db'), \
             patch.object(reminder, '_get_os', return_value='windows'), \
             patch.object(reminder, '_write_notify_script', return_value=Path('unused.py')) as writer, \
             patch.object(reminder, '_schedule_windows', return_value='mock-job'):
            self.assertIn('Reminder set', reminder.reminder(params))
            self.assertIn('Reminder set', reminder.reminder(params))
        self.assertNotEqual(writer.call_args_list[0].args[0], writer.call_args_list[1].args[0])

    def test_all_python_files_parse(self):
        for path in ROOT.rglob('*.py'):
            if any(part.startswith('.venv') or part in ('venv', '__pycache__') for part in path.parts):
                continue
            with self.subTest(path=path):
                ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))


if __name__ == '__main__':
    unittest.main()

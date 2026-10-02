"""Exercise actual Qt editors against temporary storage; no native jobs are created."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtCore import QThreadPool, QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from core import productivity_store as store, reminders, undo
from core.productivity_panel import ProductivityPanel, ReminderPanel


class ProductivityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(store, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        undo.clear()
        self.addCleanup(undo.clear)
        self.panels = []
        self.addCleanup(self.close_panels)

    def close_panels(self):
        for panel in self.panels:
            if sip.isdeleted(panel):
                continue
            self.wait(panel)
            panel.close()
            panel.deleteLater()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def wait(self, panel):
        deadline = time.monotonic() + 8
        while panel.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(panel.busy, 'Qt operation did not finish')
        self.app.processEvents()

    def panel(self, kind):
        panel = ReminderPanel() if kind == 'reminder' else ProductivityPanel(kind)
        self.panels.append(panel)
        self.wait(panel)
        return panel

    def test_task_create_edit_new_complete_restore_and_undo(self):
        panel = self.panel('task')
        panel.title.setText('Ship upgrade')
        panel.priority.setCurrentText('high')
        panel.tags.setText('release, tests')
        panel.save()
        self.wait(panel)
        self.assertIsNotNone(panel.selected)
        first_id = panel.selected['id']
        panel.body.setPlainText('Tests passed')
        panel.save()
        self.wait(panel)
        self.assertEqual(len(store.query_items('task')), 1)
        self.assertEqual(panel.selected['body'], 'Tests passed')
        panel.new()
        self.assertIsNone(panel.selected)
        panel.title.setText('Second task')
        panel.save()
        self.wait(panel)
        self.assertNotEqual(panel.selected['id'], first_id)
        panel.complete()
        self.wait(panel)
        self.assertIsNone(panel.selected)
        self.assertEqual(len(store.query_items('task')), 1)
        panel.filter.setCurrentText('completed')
        self.wait(panel)
        panel.table.selectRow(0)
        panel.select()
        panel.complete()
        self.wait(panel)
        self.assertEqual(len(store.query_items('task')), 2)
        panel.undo()
        self.wait(panel)
        self.assertEqual(len(store.query_items('task', status='completed')), 1)

    def test_note_pin_and_validation_visible(self):
        panel = self.panel('note')
        panel.title.setText('Design')
        panel.save()
        self.wait(panel)
        self.assertIn('body', panel.status.text())
        self.assertEqual(store.query_items('note'), [])
        panel.body.setPlainText('Preserve existing architecture')
        panel.category.setText('Development')
        panel.save()
        self.wait(panel)
        panel.pin()
        self.wait(panel)
        self.assertEqual(panel.selected['pinned'], 1)
        panel.refresh()
        self.wait(panel)
        self.assertEqual(panel.selected['category'], 'Development')

    def test_reminder_create_refresh_edit_new_and_cancel(self):
        with patch('actions.reminder.register_persistent', side_effect=lambda row:('native', 'test')), patch('actions.reminder.cancel_native', return_value=''):
            panel = self.panel('reminder')
            due = datetime.now() + timedelta(days=1)
            panel.message.setText('Review release')
            panel.date.setText(due.strftime('%Y-%m-%d'))
            panel.time.setText(due.strftime('%H:%M'))
            panel.save()
            self.wait(panel)
            self.assertIsNotNone(panel.selected)
            ident = panel.selected['id']
            panel.refresh()
            self.wait(panel)
            self.assertEqual(panel.selected['id'], ident)
            panel.message.setText('Review tested release')
            panel.save()
            self.wait(panel)
            self.assertEqual(len(reminders.list_reminders()), 1)
            self.assertEqual(reminders.get(ident)['message'], 'Review tested release')
            panel.action('cancel')
            self.wait(panel)
            self.assertIsNone(panel.selected)
            self.assertEqual(reminders.get(ident)['state'], 'cancelled')
            panel.filter.setCurrentText('cancelled')
            self.wait(panel)
            panel.table.selectRow(0)
            panel.select()
            panel.new()
            self.assertIsNone(panel.selected)

    def test_background_work_and_completion_use_correct_threads(self):
        panel = self.panel('task')
        main_thread = threading.get_ident()
        received = []
        panel.background(threading.get_ident, lambda worker:received.append((worker, threading.get_ident())))
        self.wait(panel)
        self.assertNotEqual(received[0][0], main_thread)
        self.assertEqual(received[0][1], main_thread)

    def test_closing_editor_during_io_does_not_access_deleted_widgets(self):
        panel = self.panel('task')
        release = threading.Event()
        self.addCleanup(release.set)
        received = []
        panel.background(lambda:release.wait(5), received.append)
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(sip.isdeleted(panel))
        release.set()
        self.wait(panel)
        self.assertEqual(received, [])


if __name__ == '__main__':
    unittest.main()

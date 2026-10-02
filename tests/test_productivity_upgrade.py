from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import plistlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch
from core import productivity_store as store, reminders, undo
from actions import notes, task_manager, reminder

class StoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'productivity.db'
        patcher = patch.object(store, 'DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        undo.clear()
        self.addCleanup(undo.clear)

class ProductivityUpgradeTests(StoreCase):
    def test_old_schema_migration_preserves_user_records(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, kind TEXT, title TEXT, body TEXT, due TEXT, done INTEGER, archived INTEGER, created TEXT)")
            db.execute("INSERT INTO items VALUES(1,'note','Legacy','Keep me','',0,0,'2025-01-01')")
        rows = store.query_items('note')
        self.assertEqual(rows[0]['body'], 'Keep me')
        self.assertEqual(rows[0]['version'], 0)
        self.assertEqual(rows[0]['tags'], [])
        self.assertEqual(rows[0]['priority'], 'normal')

    def test_edit_metadata_filters_and_preserve_unspecified_fields(self):
        self.assertIn('Saved', task_manager.run({'action':'add','title':'Ship','priority':'high','project':'MARK','tags':['release','tests'],'due':'2027-01-01'}))
        row = store.query_items('task')[0]
        self.assertIn('applied', task_manager.run({'action':'edit','id':row['id'],'body':'Verified','version':0}))
        updated = store.query_items('task', query='release', project='MARK')[0]
        self.assertEqual(updated['priority'], 'high')
        self.assertEqual(updated['due'], '2027-01-01')
        self.assertEqual(updated['version'], 1)
        self.assertIn('changed elsewhere', task_manager.run({'action':'edit','id':row['id'],'version':0,'title':'stale'}))

    def test_note_pins_categories_and_archive_restore(self):
        notes.run({'action':'add','title':'API','body':'port 8000','category':'Development','tags':'api, backend, api'})
        row = store.query_items('note')[0]
        self.assertEqual(row['tags'], ['api','backend'])
        for action in ('pin','archive'):
            notes.run({'action':action,'id':row['id']})
        self.assertEqual(store.query_items('note'), [])
        archived = store.query_items('note', status='archived', category='development')[0]
        self.assertEqual(archived['pinned'], 1)
        notes.run({'action':'restore','id':row['id']})
        self.assertEqual(len(store.query_items('note')), 1)

    def test_undo_edits_and_creation_without_losing_newer_changes(self):
        notes.run({'action':'add','title':'Draft','body':'before'})
        ident = store.query_items('note')[0]['id']
        notes.run({'action':'edit','id':ident,'body':'after'})
        self.assertTrue(undo.undo_last().startswith('Undone:'))
        self.assertEqual(store.query_items('note')[0]['body'], 'before')
        self.assertTrue(undo.undo_last().startswith('Undone:'))
        self.assertEqual(store.query_items('note'), [])
        notes.run({'action':'add','title':'Second','body':'keep'})
        with store.database() as db:
            db.execute("UPDATE items SET body='external edit',version=version+1")
        self.assertIn('Could not undo', undo.undo_last())
        self.assertEqual(store.query_items('note')[0]['body'], 'external edit')

    def test_bad_metadata_does_not_write(self):
        for fields in ({'priority':'maximum'},{'tags':[3]},{'tags':['x'*41]},{'due':'tomorrow'}):
            task_manager.run({'action':'add','title':'bad',**fields})
        self.assertEqual(store.query_items('task'), [])

    def test_edit_cannot_cross_item_kind(self):
        notes.run({'action':'add','title':'Note','body':'body'})
        ident = store.query_items('note')[0]['id']
        self.assertIn('not found', task_manager.run({'action':'edit','id':ident,'title':'changed'}))
        self.assertEqual(store.query_items('note')[0]['title'], 'Note')

class ReminderTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.clock = datetime(2027,1,4,12,tzinfo=timezone.utc)
        patcher = patch.object(reminders, 'now_utc', lambda:self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.schedule = Mock(side_effect=lambda row:(f"native-{row['id']}-{row['generation']}",'test'))
        self.cancel = Mock(return_value='')

    def add(self, repeat='none'):
        return reminders.add('Check build', self.clock+timedelta(minutes=10), repeat, self.schedule)

    def test_ids_persistence_and_history(self):
        first, second = self.add(), self.add()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(reminders.get(first['id'])['state'], 'pending')
        self.assertEqual(len(reminders.list_reminders()), 2)
        self.assertEqual([r['event'] for r in reminders.history(first['id'])], ['scheduled','created'])

    def test_cancelled_or_superseded_job_cannot_deliver(self):
        row = self.add()
        changed = reminders.change(row['id'],'snooze',minutes=30,schedule=self.schedule,cancel=self.cancel)
        self.assertEqual(changed['generation'],2)
        self.clock += timedelta(hours=1)
        notify = Mock(return_value=True)
        self.assertFalse(reminders.fire(row['id'],1,notify))
        reminders.change(row['id'],'cancel',cancel=self.cancel)
        self.assertFalse(reminders.fire(row['id'],2,notify))
        notify.assert_not_called()
        self.assertEqual(reminders.get(row['id'])['state'],'cancelled')

    def test_delivery_claim_is_once_under_concurrent_native_invocations(self):
        row = self.add()
        self.clock += timedelta(minutes=11)
        notify = Mock(return_value=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _:reminders.fire(row['id'],1,notify), range(8)))
        self.assertEqual(sum(results),1)
        notify.assert_called_once_with('Check build')
        self.assertEqual(reminders.get(row['id'])['state'],'completed')

    def test_repeat_reschedules_and_failure_is_durable(self):
        row = self.add('daily')
        self.clock += timedelta(minutes=11)
        self.assertTrue(reminders.fire(row['id'],1,lambda m:True,self.schedule))
        next_row=reminders.get(row['id'])
        self.assertEqual(next_row['state'],'pending')
        self.assertEqual(next_row['generation'],2)
        self.assertGreater(datetime.fromisoformat(next_row['due_at']),self.clock)
        self.clock = datetime.fromisoformat(next_row['due_at'])+timedelta(seconds=1)
        self.assertFalse(reminders.fire(row['id'],2,lambda m:False,self.schedule))
        self.assertEqual(reminders.get(row['id'])['state'],'failed')
        self.assertIn('delivery_failed',[r['event'] for r in reminders.history(row['id'])])

    def test_failed_edit_restores_previous_pending_schedule(self):
        old=self.add()
        with self.assertRaises(RuntimeError):
            reminders.change(old['id'],'edit',message='Changed',schedule=Mock(side_effect=OSError('scheduler offline')),cancel=self.cancel)
        self.assertEqual(reminders.get(old['id'])['generation'],1)
        self.assertEqual(reminders.get(old['id'])['message'],'Check build')
        self.assertEqual(reminders.get(old['id'])['state'],'pending')
        self.cancel.assert_not_called()

    def test_cleanup_failure_cannot_reenable_cancelled_generation(self):
        row=self.add()
        result=reminders.change(row['id'],'cancel',cancel=Mock(side_effect=OSError('unavailable')))
        self.assertIn('cleanup_warning',result)
        self.assertEqual(reminders.get(row['id'])['state'],'cancelled')

    def test_edit_conflict_and_validation(self):
        row=self.add()
        with self.assertRaises(ValueError):
            reminders.change(row['id'],'edit',message='bad',expected_generation=999)
        for count in (0,10081,'20',True):
            with self.assertRaises(ValueError):
                reminders.change(row['id'],'snooze',minutes=count)
        with self.assertRaises(ValueError):
            reminders.add('past',self.clock-timedelta(seconds=1),schedule=self.schedule)

    def test_recurring_schedule_skips_missed_events_and_weekends(self):
        due=datetime(2027,1,1,9,tzinfo=timezone.utc)
        now=due+timedelta(days=30)
        following=reminders.next_occurrence(due,'weekdays',now)
        self.assertGreater(following,now)
        self.assertLess(following.astimezone().weekday(),5)
        self.assertIsNone(reminders.next_occurrence(due,'none',now))

    def test_only_stale_inflight_jobs_are_recovered(self):
        old=self.add()
        recent=self.add()
        with store.database() as db:
            db.execute("UPDATE reminders SET state='firing',updated_at=? WHERE id=?",((self.clock-timedelta(minutes=6)).isoformat(),old['id']))
            db.execute("UPDATE reminders SET state='firing' WHERE id=?",(recent['id'],))
        self.assertEqual(reminders.recover_interrupted(),1)
        self.assertEqual(reminders.get(old['id'])['state'],'failed')
        self.assertEqual(reminders.get(recent['id'])['state'],'firing')

    def test_persistent_script_calls_guard_and_does_not_embed_message(self):
        with patch.object(reminder,'_scripts_dir',return_value=Path(self.temp.name)):
            p=reminder._write_notify_script('test','private reminder content','windows',reminder_id='a'*32,generation=2)
        source=p.read_text()
        self.assertIn('reminders.run_scheduled',source)
        self.assertNotIn('private reminder content',source)
        compile(source,str(p),'exec')

    def test_native_worker_waits_for_minute_precision_and_rechecks_cancellation(self):
        row = self.add()
        self.clock += timedelta(minutes=9, seconds=40)
        def advance(seconds):
            self.clock += timedelta(seconds=seconds)
        with patch.object(reminders, 'sleep', side_effect=advance), patch.object(reminders, 'fire', return_value=True) as fire:
            self.assertTrue(reminders.run_scheduled(row['id'], 1))
            fire.assert_called_once_with(row['id'], 1)
        self.clock -= timedelta(seconds=20)
        def cancel_in_wait(seconds):
            reminders.change(row['id'], 'cancel', cancel=self.cancel)
        with patch.object(reminders, 'sleep', side_effect=cancel_in_wait), patch.object(reminders, 'fire') as fire:
            self.assertFalse(reminders.run_scheduled(row['id'], 1))
            fire.assert_not_called()

    def test_early_native_invocation_keeps_pending_state(self):
        row = self.add()
        with patch.object(reminders, 'sleep') as sleep:
            self.assertFalse(reminders.run_scheduled(row['id'], 1))
            sleep.assert_not_called()
        self.assertEqual(reminders.get(row['id'])['state'], 'pending')

    def test_windows_scheduler_xml_preserves_special_path_characters(self):
        script = Path(self.temp.name) / 'a & b.py'
        documents = []
        def register(argv, **kwargs):
            documents.append(ET.parse(argv[argv.index('/XML')+1]))
            return Mock(returncode=0, stdout='', stderr='')
        with patch.object(reminder, '_scripts_dir', return_value=Path(self.temp.name)), patch.object(reminder.subprocess, 'run', side_effect=register):
            result = reminder._schedule_windows(self.clock, 'test-task', script, 'Content')
        self.assertEqual(result, 'test-task')
        ns = {'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(documents[0].find('.//t:Arguments', ns).text, f'"{script}"')

    def test_mac_scheduler_plist_escapes_paths(self):
        script = Path(self.temp.name) / 'a & b.py'
        with patch.object(reminder.Path, 'home', return_value=Path(self.temp.name)), patch.object(reminder.subprocess, 'run', return_value=Mock(returncode=0)):
            label = reminder._schedule_mac(self.clock, 'test-task', script)
        plist = Path(self.temp.name) / 'Library' / 'LaunchAgents' / (label + '.plist')
        data = plistlib.loads(plist.read_bytes())
        self.assertEqual(data['ProgramArguments'][1], str(script))
        self.assertEqual(data['StartCalendarInterval']['Month'], self.clock.month)

    def test_linux_systemd_preserves_snooze_seconds(self):
        target = self.clock.replace(second=37)
        with patch.object(reminder.shutil, 'which', return_value='/bin/systemd-run'), patch.object(reminder.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(reminder._schedule_linux(target, 'test-task', Path('test.py')), 'test-task')
        self.assertIn('--on-calendar=2027-01-04 12:00:37', run.call_args.args[0])

if __name__=='__main__':
    unittest.main()

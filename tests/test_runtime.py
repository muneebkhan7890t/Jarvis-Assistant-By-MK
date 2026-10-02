from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import jobs
from core.battery import BatteryMonitor, snapshot
from actions import dev_agent, project_jobs


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.patch = patch.object(jobs, 'DB_PATH', self.folder / 'jobs.db')
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def wait_done(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = jobs.get(job_id)
            if row['state'] not in ('queued', 'running'):
                return row
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_build_continues_while_other_conversation_happens(self):
        entered, release = threading.Event(), threading.Event()
        def worker(folder, progress):
            progress('Writing object detection files')
            entered.set()
            release.wait(3)
            (folder / 'main.py').write_text('print("detection")')
            return 'Generated and tested'
        row, started = jobs.start('object detection', {}, self.folder / 'projects', worker)
        try:
            self.assertTrue(started)
            self.assertTrue(entered.wait(2))
            # Status calls and unrelated work proceed without waiting for the worker.
            self.assertIn('Writing object detection', project_jobs.run({'action': 'search', 'query': 'object detection'}))
            self.assertEqual(jobs.get(row['id'])['state'], 'running')
            self.assertTrue(Path(row['folder']).is_dir())
            duplicate, created = jobs.start('another project', {}, self.folder, worker)
            self.assertFalse(created)
            self.assertEqual(row['id'], duplicate['id'])
        finally:
            release.set()
        self.assertEqual(self.wait_done(row['id'])['state'], 'completed')
        self.assertTrue((Path(row['folder']) / 'main.py').exists())
        self.assertIn(row['folder'], jobs.context())
        self.assertEqual(len(jobs.pending_notifications()), 1)
        jobs.update(row['id'], notified=1)
        self.assertEqual(jobs.pending_notifications(), [])

    def test_worker_failure_and_review_are_not_completion(self):
        for error, expected in [(RuntimeError('quota failed'), 'failed'), (jobs.JobNeedsReview('timeout'), 'needs_review')]:
            def worker(folder, progress):
                raise error
            row, _ = jobs.start('build', {}, self.folder, worker)
            self.assertEqual(self.wait_done(row['id'])['state'], expected)

    def test_cooperative_cancel_retains_folder(self):
        release = threading.Event()
        def worker(folder, progress):
            release.wait(3)
            progress('next checkpoint')
            return 'should not complete'
        row, _ = jobs.start('cancel me', {}, self.folder, worker)
        try:
            self.assertIn('requested', jobs.cancel(row['id']))
        finally:
            release.set()
        self.assertEqual(self.wait_done(row['id'])['state'], 'cancelled')
        self.assertTrue(Path(row['folder']).exists())

    def test_restart_marks_orphan_interrupted_and_preserves_request(self):
        with patch('threading.Thread.start'):
            row, _ = jobs.start('object detection camera', {'language': 'python'}, self.folder, lambda *_: '')
        jobs.recover_interrupted()
        self.assertEqual(jobs.get(row['id'])['state'], 'interrupted')
        self.assertIn('object detection camera', project_jobs.run({'action': 'list'}))
        self.assertIn('interrupted', jobs.context())

    def test_retry_uses_fresh_folder(self):
        row, _ = jobs.start('build', {}, self.folder, lambda *_: 'ok')
        self.wait_done(row['id'])
        with patch.object(dev_agent, 'PROJECTS_DIR', self.folder), patch.object(dev_agent, '_build_project', return_value='ok'):
            result = project_jobs.run({'action': 'retry', 'id': row['id']})
            new_row = jobs.recent()[0]
            self.wait_done(new_row['id'])
        self.assertIn('started', result)
        self.assertNotEqual(row['folder'], new_row['folder'])
        self.assertTrue(Path(row['folder']).exists())

    def test_dev_agent_returns_before_builder_finishes(self):
        release = threading.Event()
        def build(*args, **kwargs):
            release.wait(3)
            return 'done'
        with patch.object(dev_agent, 'PROJECTS_DIR', self.folder), patch.object(dev_agent, '_build_project', side_effect=build):
            result = dev_agent.dev_agent({'description': 'object detection'})
            try:
                self.assertIn('You can continue talking', result)
                row = jobs.recent()[0]
                self.assertIn(row['folder'], result)
                self.assertIn(row['state'], ('queued', 'running'))
            finally:
                release.set()
            self.wait_done(row['id'])

    def test_no_jobs_does_not_claim_work_exists(self):
        self.assertIn('No recorded build was started', project_jobs.run({'action': 'list'}))


class BuildTests(unittest.TestCase):
    def test_nonzero_exit_and_timeout_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(subprocess, 'run', return_value=SimpleNamespace(returncode=9, stdout='', stderr='')):
                output = dev_agent._run_project('python main.py', Path(folder))
                self.assertTrue(dev_agent._has_error(output, 'python main.py'))
            with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('python', 1)):
                output = dev_agent._run_project('python main.py', Path(folder))
                self.assertIn('not verified', output)
                self.assertTrue(dev_agent._has_error(output, 'python main.py'))

    def test_generated_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            self.assertEqual(dev_agent._safe_project_path(base, 'src/main.py'), base / 'src' / 'main.py')
            for name in ('../outside.py', str(base.parent / 'outside.py'), '.'):
                with self.assertRaises(ValueError):
                    dev_agent._safe_project_path(base, name)

    def test_builder_timeout_requires_review_and_reports_reserved_folder(self):
        plan = {'project_name': 'object_detection', 'files': [{'path': 'main.py'}], 'dependencies': []}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(dev_agent, '_plan_project', return_value=plan), \
             patch.object(dev_agent, '_write_file', return_value='print(1)'), \
             patch.object(dev_agent, '_open_vscode'), \
             patch.object(dev_agent, '_run_project', return_value='Timed out after 30s'), \
             patch.object(dev_agent.time, 'sleep'):
            with self.assertRaises(jobs.JobNeedsReview) as caught:
                dev_agent._build_project('detect', 'python', '', 30, project_dir=Path(folder))
            self.assertIn(folder, str(caught.exception))

    def test_certificate_is_generated_only_in_requested_folder(self):
        from core.dashboard_tls import ensure_certificate
        from cryptography import x509
        with tempfile.TemporaryDirectory() as folder:
            ensure_certificate(folder, '192.168.1.20')
            certificate = Path(folder) / 'config' / 'certs' / 'jarvis.crt'
            original = certificate.read_bytes()
            cert = x509.load_pem_x509_certificate(original)
            self.assertIn('192.168.1.20', str(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value))
            ensure_certificate(folder, '192.168.1.20')
            self.assertEqual(certificate.read_bytes(), original)


class BatteryTests(unittest.TestCase):
    def test_thresholds_cooldown_and_charging(self):
        clock = [0]
        monitor = BatteryMonitor(clock=lambda: clock[0])
        def check(percent, plugged=False):
            return monitor.check({'percent': percent, 'plugged': plugged})
        self.assertIsNone(check(50))
        self.assertIn('20%', check(20))
        self.assertIsNone(check(19))
        self.assertIn('critically low', check(10))
        self.assertIsNone(check(9))
        clock[0] = 901
        self.assertIn('9%', check(9))
        self.assertIsNone(check(9, True))
        self.assertIn('9%', check(9))
        self.assertIsNone(monitor.check(None))

    def test_missing_battery_is_supported(self):
        with patch('core.battery.psutil.sensors_battery', return_value=None):
            self.assertIsNone(snapshot())


try:
    from fastapi.testclient import TestClient
    HAS_WEB = True
except ImportError:
    HAS_WEB = False


@unittest.skipUnless(HAS_WEB, 'Install requirements.txt for dashboard integration tests')
class PhoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job_patch = patch.object(jobs, 'DB_PATH', Path(self.temp.name) / 'jobs.db')
        self.job_patch.start()
        self.addCleanup(self.job_patch.stop)
        from dashboard.server import DashboardServer
        legacy = patch.object(DashboardServer, "_legacy_allowed", return_value=True)
        legacy.start()
        self.addCleanup(legacy.stop)
        with patch('core.dashboard_tls.ensure_certificate'), patch('dashboard.server._local_ip', return_value='127.0.0.1'):
            self.server = DashboardServer()
        self.client = TestClient(self.server.app)
        self.addCleanup(self.client.close)
        key = self.server.new_key()
        response = self.client.post('/login', json={'pin': key})
        self.assertEqual(response.status_code, 200)
        self.headers = {'Authorization': 'Bearer ' + response.json()['token']}

    def test_unauthorized_requests_rejected(self):
        self.assertEqual(self.client.get('/api/projects').status_code, 401)
        self.assertEqual(self.client.post('/api/projects', json={'description':'x'}).status_code, 401)
        self.assertEqual(self.client.post('/api/projects/missing/cancel').status_code, 401)

    def test_status_available_without_live_session(self):
        response = self.client.get('/api/projects', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['assistant_online'])
        self.assertIn('battery', response.json())

    def test_offline_command_returns_error_instead_of_silent_loss(self):
        response = self.client.post('/api/command', headers=self.headers, json={'text': 'open calculator'})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.server._command_queue.empty())

    def test_online_command_is_queued(self):
        self.server._session_ready = lambda: True
        response = self.client.post('/api/command', headers=self.headers, json={'text': 'open calculator'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server._command_queue.get_nowait(), 'open calculator')

    def test_project_input_validation_and_dispatch(self):
        for body in ({}, [], {'description': 7}):
            self.assertEqual(self.client.post('/api/projects', headers=self.headers, json=body).status_code, 400)
        with patch('memory.config_manager.get_gemini_key', return_value='test'), patch.object(dev_agent, 'dev_agent', return_value='Job started') as runner:
            response = self.client.post('/api/projects', headers=self.headers, json={'description': 'object detection'})
            self.assertEqual(response.status_code, 200)
            runner.assert_not_called()
            self.assertIn('not available', response.json()['message'])

    def test_cancel_retry_validation_and_dispatch(self):
        self.assertEqual(self.client.post('/api/projects/missing/cancel', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post('/api/projects/missing/delete', headers=self.headers).status_code, 400)
        with patch.object(jobs, 'get', return_value={'id':'known'}), patch.object(project_jobs, 'run', return_value='Cancellation requested') as run:
            response = self.client.post('/api/projects/known/cancel', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            run.assert_called_once_with({'action':'cancel', 'id':'known'})


if __name__ == '__main__':
    unittest.main()

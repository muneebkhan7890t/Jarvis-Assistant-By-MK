import base64
import os
import socket
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from core.permission_manager import PermissionManager
from core.remote_store import RemoteStore
from core.remote_projects import ProjectRunner


class ProjectRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RemoteStore(self.root / "remote.db")
        self.permissions = PermissionManager(self.root / "permissions.json")
        public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.device = self.store.enroll(base64.b64encode(public).decode(), "Test phone", "Android")["id"]
        self.store.trust(self.device, ["projects"])
        self.enabled = True
        def authorize(device, capability):
            row = self.store.device(device)
            if not self.enabled or not row or not row["trusted"] or capability not in row["capabilities"]:
                raise PermissionError("Revoked")
        self.runner = ProjectRunner(self.store, authorize, self.permissions)
        self.addCleanup(self.runner.shutdown)

    def profile(self, code="print('job output')", **values):
        return self.store.save_profile({"name": "Test command", "cwd": str(self.root),
            "argv": [sys.executable, "-u", "-c", code], "timeout": 10, "kind": "task", "enabled": True, **values})

    def start(self, row, request="test-request-1"):
        return self.runner.start(self.device, row["id"], row["revision"], request)[0]

    def wait(self, command_id, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.store.receipt(self.device, command_id)
            if row["status"] not in ("queued", "running"):
                return row
            time.sleep(.025)
        self.fail("Project worker did not finish")

    def test_profiles_are_encrypted_revisioned_and_disabled_by_default(self):
        row = self.profile(enabled=False)
        self.assertNotIn(b"Test command", self.store.path.read_bytes())
        with self.assertRaises(PermissionError):
            self.start(row)
        row["enabled"] = True
        saved = self.store.save_profile(row, row["revision"])
        with self.assertRaises(ValueError):
            self.store.save_profile(row, row["revision"])
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(ValueError):
            self.store.delete_profile(saved["id"], 1)

    def test_policy_deny_and_executable_change_block_launch(self):
        row = self.profile()
        self.permissions.set("terminal", "Deny")
        with self.assertRaises(PermissionError):
            self.start(row)
        self.permissions.set("terminal", "Always Ask")
        with patch("core.remote_projects.executable_hash", return_value="changed"):
            with self.assertRaises(PermissionError):
                self.start(row)

    @unittest.skipUnless(os.name == "nt", "Windows owned process trees")
    def test_real_exit_stdout_idempotency_and_durable_notification(self):
        row = self.profile()
        with patch("core.confirm.request", side_effect=AssertionError("A fixed locally reviewed command must not prompt again")):
            command_id = self.start(row)
            self.assertEqual(self.start(row), command_id)
            receipt = self.wait(command_id)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.assertEqual(receipt["result"]["exit_code"], 0)
        self.assertIn("job output", receipt["result"]["output"])
        messages = self.store.notifications(self.device)
        self.assertEqual(len(messages), 1)
        reopened = RemoteStore(self.store.path)
        self.assertEqual(reopened.notifications(self.device)[0]["id"], messages[0]["id"])
        with self.assertRaises(ValueError):
            self.store.read_notification("different-device", messages[0]["id"])
        self.store.read_notification(self.device, messages[0]["id"])
        self.assertIsNotNone(self.store.notifications(self.device)[0]["read_at"])

    @unittest.skipUnless(os.name == "nt", "Windows owned process trees")
    def test_nonzero_timeout_and_bounded_output(self):
        failed = self.wait(self.start(self.profile("import sys; print('failure'); sys.exit(7)")))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["result"]["exit_code"], 7)
        timed = self.wait(self.start(self.profile("import time; time.sleep(30)", timeout=1), "timeout-request"))
        self.assertEqual(timed["status"], "failed")
        self.assertIn("time limit", timed["result"]["message"])
        large = self.wait(self.start(self.profile("print('x'*200000)"), "output-request"))
        self.assertLessEqual(len(large["result"]["output"]), 65536)
        self.assertTrue(large["result"]["truncated"])

    @unittest.skipUnless(os.name == "nt", "Windows owned process trees")
    def test_stop_kills_spawned_child_and_revocation_stops_running_job(self):
        import psutil
        code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print('CHILD:'+str(p.pid),flush=True); time.sleep(60)"
        command_id = self.start(self.profile(code))
        child = None
        for _ in range(150):
            result = self.store.receipt(self.device, command_id)["result"] or {}
            if "CHILD:" in result.get("output", ""):
                child = psutil.Process(int(result["output"].split("CHILD:")[1].split()[0]))
                break
            time.sleep(.025)
        self.assertIsNotNone(child, self.store.receipt(self.device, command_id))
        self.runner.cancel(self.device, command_id)
        self.assertEqual(self.wait(command_id)["status"], "cancelled")
        child.wait(timeout=3)
        second = self.start(self.profile("import time; time.sleep(30)"), "revoked-request")
        self.store.revoke(self.device)
        self.assertEqual(self.wait(second)["status"], "failed")

    def test_notification_is_device_scoped_and_deduplicated(self):
        command_id, _ = self.store.enqueue(self.device, "notification-request", {"text": "example"})
        for _ in range(2):
            self.store.update(command_id, "failed", {"message": "Example failure"})
        self.assertEqual(len(self.store.notifications(self.device)), 1)
        self.assertEqual(self.store.notifications("other-device"), [])

    @unittest.skipUnless(os.name == "nt", "Windows owned process trees")
    def test_server_health_stop_and_occupied_port(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        code = f"from http.server import HTTPServer,BaseHTTPRequestHandler; HTTPServer(('127.0.0.1',{port}),BaseHTTPRequestHandler).serve_forever()"
        command_id = self.start(self.profile(code, kind="server", port=port, timeout=10))
        for _ in range(150):
            row = self.store.receipt(self.device, command_id)
            if (row["result"] or {}).get("port_reachable"):
                break
            time.sleep(.025)
        self.assertTrue(row["result"].get("port_reachable"), row)
        self.assertEqual(row["status"], "running")
        self.runner.shutdown()
        self.assertEqual(self.wait(command_id)["status"], "cancelled")
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            row = self.profile(code, kind="server", port=occupied.getsockname()[1])
            with patch.object(self.runner, "process_factory") as create:
                receipt = self.wait(self.start(row, "occupied-request"))
            self.assertEqual(receipt["status"], "failed")
            self.assertIn("already in use", receipt["result"]["message"])
            create.assert_not_called()


class ProjectReviewUITests(unittest.TestCase):
    def test_pc_review_required_and_stale_edits_rejected(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from core.remote_project_panel import RemoteProjectPanel
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            store = RemoteStore(Path(tmp) / "remote.db")
            with patch("core.remote_project_panel.remote_store", return_value=store):
                panel = RemoteProjectPanel()
            panel.name.setText("Fixture")
            panel.cwd.setText(tmp)
            panel.exe.setText(sys.executable)
            panel.args.setPlainText("-c\nprint('fixture')")
            panel.approved.setChecked(True)
            with patch("core.remote_project_panel.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                panel.save()
            self.assertEqual(store.profiles(), [])
            def settle():
                for _ in range(200):
                    app.processEvents()
                    if not panel.busy:
                        break
                    time.sleep(.01)
                self.assertFalse(panel.busy)
            with patch("core.remote_project_panel.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                panel.save()
                settle()
                row = store.profiles()[0]
                self.assertEqual(row["argv"][1:], ["-c", "print('fixture')"])
                self.assertTrue(row["enabled"])
                store.save_profile({**row, "name": "Newer change"}, row["revision"])
                panel.name.setText("Stale edit")
                panel.save()
                settle()
                self.assertIn("changed", panel.status.text())
                self.assertEqual(store.profiles()[0]["name"], "Newer change")
            panel.close()


if __name__ == "__main__":
    unittest.main()

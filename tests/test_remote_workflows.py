from pathlib import Path
import tempfile
import threading
import time
import unittest
from core.remote_store import RemoteStore
from core.permission_manager import PermissionManager
from core.workflows import WorkflowManager
from core.remote_workflows import RemoteWorkflows, version


class RemoteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = RemoteStore(root / "remote.db")
        self.definitions = WorkflowManager(root / "workflows")
        self.permissions = PermissionManager(root / "permissions.json")
        self.authorized, self.calls = True, []
        def authorize(device, capability):
            if not self.authorized:
                raise PermissionError("Device revoked")
        self.runner = RemoteWorkflows(self.store, authorize, self.dispatch, self.definitions, self.permissions)
        self.row = self.definitions.save({"name": "Example", "steps": [
            {"name": "open_app", "parameters": {"app_name": "calculator"}},
            {"name": "computer_settings", "parameters": {"action": "mute"}}]})

    def dispatch(self, name, args):
        self.calls.append((name, args))
        return "Action returned"

    def start(self):
        return self.runner.start("owner", self.row["id"], version(self.row), "workflow-request-1")[0]

    def wait(self, ident):
        for _ in range(200):
            row = self.store.receipt("owner", ident)
            if row["status"] not in ("queued", "running"):
                return row
            time.sleep(.01)
        self.fail("Workflow did not finish")

    def test_steps_receipts_idempotency_and_notification(self):
        ident = self.start()
        row = self.wait(ident)
        self.assertEqual(row["status"], "returned")
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(row["result"]["verified"])
        self.assertEqual(self.start(), ident)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.store.notifications("owner")), 1)

    def test_changed_definition_and_medium_risk_steps_are_rejected(self):
        self.definitions.save({**self.row, "name": "Changed"})
        with self.assertRaises(ValueError):
            self.start()
        self.row = self.definitions.save({"name": "File read", "steps": [{"name": "file_controller", "parameters": {"action": "read", "path": "private"}}]})
        with self.assertRaises(PermissionError):
            self.start()
        self.assertEqual(self.calls, [])

    def test_cancel_and_revocation_stop_before_next_step(self):
        for revoke in (False, True):
            with self.subTest(revoke=revoke):
                self.calls.clear()
                entered, release = threading.Event(), threading.Event()
                def dispatch(name, args):
                    self.calls.append(name)
                    entered.set()
                    release.wait(2)
                    return "Returned"
                self.runner.dispatch = dispatch
                ident, _ = self.runner.start("owner", self.row["id"], version(self.row), "revoke-" + str(revoke))
                try:
                    self.assertTrue(entered.wait(2))
                    if revoke:
                        self.authorized = False
                    else:
                        self.runner.cancel("owner", ident)
                finally:
                    release.set()
                self.assertEqual(self.wait(ident)["status"], "failed" if revoke else "cancelled")
                self.assertEqual(len(self.calls), 1)

    def test_permission_denial_prevents_first_step(self):
        self.permissions.set("open_app", "Deny")
        with self.assertRaises(PermissionError):
            self.start()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

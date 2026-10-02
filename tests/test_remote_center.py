import base64
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient
from core.remote_store import RemoteStore, CAPABILITIES
from core.permission_manager import DEFAULTS
from dashboard.remote_api import scoped_path
from dashboard.server import DashboardServer


class Identity:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()

    def signature(self, device_id, nonce, path, body):
        message = f"MARK-LIV-REMOTE-v1\n{device_id}\n{nonce}\nPOST\n{path}\n{hashlib.sha256(body).hexdigest()}".encode()
        r, s = decode_dss_signature(self.key.sign(message, ec.ECDSA(hashes.SHA256())))
        return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()


class RemoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.store = RemoteStore(Path(self.temp.name) / "remote.db", clock=lambda: self.now)
        self.identity = Identity()
        self.device = self.store.enroll(self.identity.public, "Owner phone", "Android")
        self.device_id = self.device["id"]

    def signed(self, path="/remote-api/computer", body=b"{}"):
        nonce = self.store.challenge(self.device_id)["nonce"]
        return nonce, self.identity.signature(self.device_id, nonce, path, body)

    def verify(self, nonce, signature, path="/remote-api/computer", body=b"{}"):
        return self.store.verify(self.device_id, nonce, signature, "POST", path, body)

    def test_pending_not_authorized_and_explicit_trust(self):
        with self.assertRaises(PermissionError):
            self.verify(*self.signed())
        self.store.trust(self.device_id, ["computer"])
        self.assertEqual(self.verify(*self.signed())["capabilities"], ["computer"])

    def test_replay_body_path_and_wrong_key(self):
        self.store.trust(self.device_id, ["computer"])
        nonce, signature = self.signed()
        self.verify(nonce, signature)
        with self.assertRaises(PermissionError):
            self.verify(nonce, signature)
        with self.assertRaises(PermissionError):
            self.verify(*self.signed(), body=b'{"tampered":true}')
        with self.assertRaises(PermissionError):
            self.verify(*self.signed(), path="/remote-api/screen")
        nonce = self.store.challenge(self.device_id)["nonce"]
        with self.assertRaises(PermissionError):
            self.verify(nonce, Identity().signature(self.device_id, nonce, "/remote-api/computer", b"{}"))

    def test_expiry_revocation_and_persistence(self):
        self.store.trust(self.device_id, ["computer"])
        signed = self.signed()
        self.now += 31
        with self.assertRaises(PermissionError):
            self.verify(*signed)
        reopened = RemoteStore(self.store.path, clock=lambda: self.now)
        self.assertTrue(reopened.device(self.device_id)["trusted"])
        signed = self.signed()
        reopened.revoke(self.device_id)
        with self.assertRaises(PermissionError):
            self.verify(*signed)

    def test_idempotency_encrypted_results_and_restart(self):
        command, created = self.store.enqueue(self.device_id, "request-123", {"text": "private command"})
        self.assertTrue(created)
        self.assertEqual(self.store.enqueue(self.device_id, "request-123", {"text": "private command"}), (command, False))
        with self.assertRaises(ValueError):
            self.store.enqueue(self.device_id, "request-123", {"text": "different"})
        self.assertNotIn(b"private command", self.store.path.read_bytes())
        self.store.update(command, "running")
        self.store.recover()
        row = self.store.receipts(self.device_id)[0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("unknown", row["result"]["message"])
        self.assertEqual(self.store.receipts("another-device"), [])

    def test_invalid_curve_and_capability(self):
        with self.assertRaises(ValueError):
            self.store.trust(self.device_id, ["arbitrary_shell"])
        key = ec.generate_private_key(ec.SECP384R1())
        public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        with self.assertRaises(ValueError):
            self.store.enroll(public, "Phone", "Android")

    def test_scope_traversal_and_secrets(self):
        root = Path(self.temp.name)
        (root / "report.txt").write_text("example")
        (root / ".env").write_text("fake secret")
        (root / "token.json").write_text("fake token")
        self.assertEqual(scoped_path([str(root)], 0, "report.txt"), root / "report.txt")
        for name in ("../outside", str(root / "report.txt"), ".env", "token.json", "remote.key", "remote.db"):
            with self.assertRaises((PermissionError, FileNotFoundError)):
                scoped_path([str(root)], 0, name)


class RemoteAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RemoteStore(Path(self.temp.name) / "remote.db")
        self.cfg = {"remote_control_enabled": True, "allow_device_pairing": True,
                    "remote_features": dict.fromkeys(CAPABILITIES, True), "remote_file_roots": [self.temp.name]}
        for target, kwargs in (("dashboard.remote_api.remote_store", {"return_value": self.store}),
                               ("core.permission_manager.manager.settings", {"side_effect": lambda: DEFAULTS.copy()}),
                               ("memory.config_manager.load_api_keys", {"side_effect": lambda: self.cfg}),
                               ("dashboard.remote_api.load_api_keys", {"side_effect": lambda: self.cfg}),
                               ("core.dashboard_tls.ensure_certificate", {}),
                               ("dashboard.server._local_ip", {"return_value": "127.0.0.1"})):
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        self.server = DashboardServer()
        self.executed = []
        self.server.remote_dispatch = lambda n, p: self.executed.append((n, p)) or "Test action receipt"
        self.client = TestClient(self.server.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.identity = Identity()
        response = self.client.post("/remote-api/enroll", json={"code": self.server.new_key(), "public_key": self.identity.public, "name": "Test phone", "platform": "Android"})
        self.assertEqual(response.status_code, 200, response.text)
        self.device_id = response.json()["id"]

    def request(self, operation, body=None):
        body = json.dumps(body or {}).encode()
        path = "/remote-api/" + operation
        response = self.client.post("/remote-api/challenge", json={"device_id": self.device_id})
        if response.status_code != 200:
            return response
        nonce = response.json()["nonce"]
        signature = self.identity.signature(self.device_id, nonce, path, body)
        return self.client.post(path, content=body, headers={"Content-Type": "application/json", "X-Device": self.device_id, "X-Nonce": nonce, "X-Signature": signature})

    def trust(self, caps=None):
        self.store.trust(self.device_id, list(CAPABILITIES) if caps is None else caps)

    def test_trust_cannot_be_granted_over_http(self):
        self.assertEqual(self.request("session").status_code, 403)
        self.trust(["computer"])
        self.assertEqual(self.request("trust", {"capabilities": list(CAPABILITIES)}).status_code, 404)
        self.assertEqual(self.request("computer").status_code, 200)
        self.assertEqual(self.request("screen").status_code, 403)
        self.store.revoke(self.device_id)
        self.assertEqual(self.request("computer").status_code, 403)

    def test_master_and_feature_switches(self):
        self.trust()
        self.cfg["remote_features"]["computer"] = False
        self.assertEqual(self.request("computer").status_code, 403)
        self.cfg["remote_control_enabled"] = False
        self.assertEqual(self.request("session").status_code, 403)

    def test_legacy_cannot_bypass_owner_trust_by_default(self):
        with patch("memory.config_manager.load_api_keys", return_value={"remote_control_enabled": True}):
            self.assertEqual(self.client.post("/login", json={"pin": self.server.new_key()}).status_code, 410)
            self.assertEqual(self.client.get("/api/projects").status_code, 410)
            self.assertIn("Remote Command Center", self.client.get("/").text)

    def test_real_receipts_duplicate_and_unknown_command(self):
        self.trust()
        body = {"text": "open calculator", "request_id": "stable-request-1"}
        response = self.request("command", body)
        self.assertEqual(response.status_code, 200, response.text)
        command_id = response.json()["id"]
        self.assertEqual(self.request("command", body).json()["id"], command_id)
        for _ in range(50):
            rows = self.store.receipts(self.device_id)
            if rows[0]["status"] != "queued" and rows[0]["status"] != "running":
                break
            time.sleep(.01)
        self.assertEqual(len(self.executed), 1)
        self.assertEqual(rows[0]["status"], "returned")
        self.assertFalse(rows[0]["result"]["verified"])
        self.request("command", {"text": "delete everything", "request_id": "stable-request-2"})
        for _ in range(50):
            rows = self.store.receipts(self.device_id)
            if rows[0]["status"] == "failed":
                break
            time.sleep(.01)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(len(self.executed), 1)

    def test_files_and_no_unsigned_access(self):
        self.trust()
        (Path(self.temp.name) / "report.txt").write_text("hello")
        response = self.request("download", {"root": 0, "path": "report.txt"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(base64.b64decode(response.json()["data"]), b"hello")
        self.assertEqual(self.request("download", {"root": 0, "path": "remote.key"}).status_code, 403)
        self.assertEqual(self.client.post("/remote-api/computer", json={}).status_code, 403)
        self.assertEqual(self.client.post("/remote-api/challenge", json={"device_id": self.device_id}, headers={"Origin": "https://evil.test"}).status_code, 403)

    def test_strict_remote_dispatch_cannot_queue_desktop_confirmation(self):
        from core.permission_manager import PermissionManager
        manager = PermissionManager(Path(self.temp.name) / "permissions.json")
        manager.set("open_app", "Ask")
        with patch("core.confirm.request") as confirm:
            result = manager.invoke("open_app", {"app_name": "calculator"}, lambda p: self.fail("Must not execute"), source="phone", require_allowed=True)
        self.assertIn("Permission denied", result)
        confirm.assert_not_called()

    def test_screen_returns_image_and_announces_capture(self):
        from PIL import Image
        self.trust()
        with patch("pyautogui.screenshot", return_value=Image.new("RGB", (32, 32), "navy")) as capture, patch.object(self.server, "remote_notice", create=True) as notice:
            response = self.request("screen")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(base64.b64decode(response.json()["image"]).startswith(b"\xff\xd8"))
            capture.assert_called_once()
            notice.assert_called_once()

    def test_chat_offline_deduplicated_and_tool_scopes(self):
        self.trust()
        body = {"text": "hello", "request_id": "chat-request-1"}
        self.assertEqual(self.request("chat", body).status_code, 400)
        self.server._session_ready = lambda: True
        self.assertEqual(self.request("chat", body).status_code, 200)
        self.assertFalse(self.request("chat", body).json()["new"])
        self.assertEqual(self.server._command_queue.qsize(), 1)
        self.assertEqual(self.server.remote_live_device, self.device_id)
        with self.assertRaises(PermissionError):
            self.server.remote_tool_dispatch("file_controller", {"action": "read", "path": "C:/secret.txt"})
        self.store.trust(self.device_id, ["chat"])
        with self.assertRaises(PermissionError):
            self.server.remote_tool_dispatch("open_app", {"app_name": "calculator"})
        self.assertFalse(self.executed)

    def test_voice_ticket_is_single_use_and_revoke_stops_stream(self):
        from starlette.websockets import WebSocketDisconnect
        self.trust()
        self.server._session_ready = lambda: True
        ticket = self.request("voice-ticket").json()["ticket"]
        with self.client.websocket_connect("/remote-voice?ticket=" + ticket) as ws:
            ws.send_bytes(b"\x00\x00" * 128)
            for _ in range(100):
                if not self.server._phone_audio_queue.empty():
                    break
                time.sleep(.01)
            self.assertFalse(self.server._phone_audio_queue.empty())
            self.assertEqual(self.server.remote_live_device, self.device_id)
            self.store.revoke(self.device_id)
            ws.send_bytes(b"\x00\x00" * 128)
            self.assertEqual(ws.receive()["type"], "websocket.close")
        self.assertTrue(self.server._phone_audio_queue.empty())
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/remote-voice?ticket=" + ticket):
                self.fail("Ticket replay accepted")

    def test_main_relay_records_sent_chat_without_claiming_completion(self):
        # Compile the real integration method without booting Qt/audio/Gemini.
        source = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(source) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_process_dashboard_commands")
        namespace = {"asyncio": asyncio}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "main-relay", "exec"), namespace)
        self.trust()
        command_id, _ = self.store.enqueue(self.device_id, "relay-chat-1", {"text": "hello", "type": "chat"})

        async def run():
            sent = asyncio.Event()
            async def send(**kwargs):
                self.assertEqual(kwargs["turns"]["parts"][0]["text"], "hello")
                sent.set()
            queue = asyncio.Queue()
            queue.put_nowait({"remote_id": command_id, "device_id": self.device_id, "text": "hello"})
            dashboard = SimpleNamespace(_command_queue=queue, remote_validate=self.server.remote_validate)
            assistant = SimpleNamespace(_dashboard=dashboard, session=SimpleNamespace(send_client_content=send),
                                        ui=SimpleNamespace(write_log=lambda text: None), _wake_enabled=False)
            task = asyncio.create_task(namespace["_process_dashboard_commands"](assistant))
            try:
                await asyncio.wait_for(sent.wait(), timeout=2)
                await asyncio.sleep(.02)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        with patch("core.remote_store.remote_store", return_value=self.store):
            asyncio.run(run())
        row = self.store.receipts(self.device_id)[0]
        self.assertEqual(row["status"], "returned")
        self.assertFalse(row["result"]["verified"])

    @unittest.skipUnless(os.name == "nt", "Windows owned process trees")
    def test_project_api_uses_reviewed_arguments_and_persists_notification(self):
        self.trust()
        profile = self.store.save_profile({"name": "API test", "cwd": self.temp.name,
            "argv": [sys.executable, "-c", "print('reviewed execution')"], "enabled": True})
        body = {"profile_id": profile["id"], "revision": profile["revision"], "request_id": "project-api-request"}
        self.assertEqual(self.request("project-run", {**body, "argv": ["untrusted"]}).status_code, 400)
        result = self.request("project-run", body)
        self.assertEqual(result.status_code, 200, result.text)
        command_id = result.json()["id"]
        for _ in range(200):
            row = self.store.receipt(self.device_id, command_id)
            if row["status"] not in ("queued", "running"):
                break
            time.sleep(.025)
        self.assertEqual(row["status"], "completed", row)
        self.assertIn("reviewed execution", row["result"]["output"])
        self.assertFalse(self.request("project-run", body).json()["new"])
        notifications = self.request("notifications").json()["notifications"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(self.request("notification-read", {"id": notifications[0]["id"]}).status_code, 200)

    def test_saved_workflow_api_and_step_override_rejection(self):
        from core.workflows import WorkflowManager
        definitions = WorkflowManager(Path(self.temp.name) / "workflows")
        definitions.save({"name": "Example", "steps": [{"name": "open_app", "parameters": {"app_name": "calculator"}}]})
        self.trust()
        with patch("core.workflows.workflows", definitions):
            row = self.request("workflows").json()["workflows"][0]
            body = {"id": row["id"], "version": row["version"], "request_id": "workflow-api-request"}
            self.assertEqual(self.request("workflow-run", {**body, "steps": []}).status_code, 400)
            response = self.request("workflow-run", body)
            self.assertEqual(response.status_code, 200, response.text)
            for _ in range(100):
                receipt = self.store.receipt(self.device_id, response.json()["id"])
                if receipt["status"] == "returned":
                    break
                time.sleep(.01)
        self.assertEqual(receipt["status"], "returned", receipt)
        self.assertEqual(len(self.executed), 1)

    def test_automation_controls_use_revision_scope_and_durable_run(self):
        from core.automation import AutomationEngine
        engine = AutomationEngine(Path(self.temp.name) / "automation.json")
        engine.dispatch = lambda name, args: "Local notification"
        rule = engine.save({"name": "Example", "trigger": {"field": "cpu_percent", "op": "gt", "value": 90},
            "action": {"name": "open_app", "parameters": {"app_name": "calculator"}}, "enabled": True, "cooldown": 0})
        self.trust()
        with patch("core.automation.automations", engine):
            response = self.request("automation-control", {"id": rule["id"], "revision": rule["revision"], "action": "disable"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(engine.get(rule["id"])["enabled"])
            self.assertEqual(self.request("automation-control", {"id": rule["id"], "revision": rule["revision"], "action": "enable"}).status_code, 400)
            revision = response.json()["revision"]
            response = self.request("automation-control", {"id": rule["id"], "revision": revision, "action": "enable"})
            body = {"id": rule["id"], "revision": response.json()["revision"], "action": "run", "request_id": "automation-api-request"}
            result = self.request("automation-control", body)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse(self.request("automation-control", body).json()["new"])
            for _ in range(100):
                receipt = self.store.receipt(self.device_id, result.json()["id"])
                if receipt["status"] == "returned":
                    break
                time.sleep(.01)
            self.assertEqual(receipt["status"], "returned", receipt)
            self.assertEqual(len(self.executed), 1)
            self.store.trust(self.device_id, ["commands"])
            self.assertEqual(self.request("automations").status_code, 403)


    def test_phone_speaker_tickets_pcm_scope_revocation_and_replay(self):
        from starlette.websockets import WebSocketDisconnect
        self.trust(['voice'])
        self.server._session_ready = lambda: True
        self.assertEqual(self.request('audio-ticket').status_code, 403)
        self.trust(['voice', 'chat'])
        ticket = self.request('audio-ticket').json()['ticket']
        async def emit(data):
            self.server.remote_publish_audio(data)
        with self.client.websocket_connect('/remote-listen?ticket=' + ticket, headers={'origin': 'https://testserver'}) as ws:
            self.client.portal.call(emit, b'\x00\x01' * 1200)
            self.assertEqual(ws.receive_bytes(), b'\x00\x01' * 1200)
            self.client.portal.call(emit, None)
            self.assertEqual(ws.receive_json(), {'type': 'clear'})
            self.assertEqual(self.request('audio-ticket').status_code, 400)
            self.store.revoke(self.device_id)
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_bytes()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/remote-listen?ticket=' + ticket, headers={'origin': 'https://testserver'}):
                pass

    def test_push_subscription_routes_require_trust_and_are_device_scoped(self):
        from test_remote_push import fixture_subscription
        self.assertEqual(self.request('push-status').status_code, 403)
        self.trust()
        result = self.request('push-status')
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['subscribed'])
        self.assertEqual(self.request('push-subscribe', {'subscription': fixture_subscription('https://127.0.0.1/private')}).status_code, 400)
        self.assertEqual(self.request('push-subscribe', {'subscription': fixture_subscription()}).status_code, 200)
        self.assertTrue(self.request('push-status').json()['subscribed'])
        self.assertEqual(self.request('push-unsubscribe').status_code, 200)
        self.assertFalse(self.request('push-status').json()['subscribed'])
        self.assertEqual(self.client.get('/remote-sw.js').status_code, 200)
        self.assertEqual(self.client.get('/static/remote-companion.js').status_code, 200)
        self.assertEqual(self.client.get('/remote-manifest.json').json()['start_url'], '/remote')


if __name__ == "__main__":
    unittest.main()

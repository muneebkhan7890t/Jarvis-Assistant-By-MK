import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from dashboard.server import DashboardServer

class DashboardSecurityTests(unittest.TestCase):
    def setUp(self):
        legacy = patch.object(DashboardServer, "_legacy_allowed", return_value=True)
        legacy.start()
        self.addCleanup(legacy.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch("core.dashboard_tls.ensure_certificate"), patch("dashboard.server._local_ip", return_value="127.0.0.1"):
            self.server = DashboardServer()
        self.server._uploads_dir = Path(self.temp.name)
        self.client = TestClient(self.server.app)
        self.addCleanup(self.client.close)
        key = self.server.new_key()
        token = self.client.post("/login", json={"pin":key}).json()["token"]
        self.token = token
        self.headers = {"Authorization": "Bearer " + token}

    def test_expired_session_and_revocation(self):
        self.server._token_expiry[self.token] = time.time()-1
        self.assertEqual(self.client.get("/api/files", headers=self.headers).status_code, 401)
        self.server.revoke_all()
        self.assertFalse(self.server._tokens)
        self.assertFalse(self.server._token_keys)

    def test_login_limit_and_malformed_input(self):
        self.assertEqual(self.client.post("/login", json=[]).status_code, 400)
        for _ in range(12):
            response = self.client.post("/login", json={"pin":"wrong"})
        self.assertEqual(response.status_code, 429)

    def test_origin_and_security_headers(self):
        response = self.client.post("/api/wake", headers={**self.headers, "Origin":"https://evil.test"})
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/api/files", headers=self.headers)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_uploads_reject_executable_and_strip_paths(self):
        response = self.client.post("/api/upload", headers=self.headers, files={"file":("../../note.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.server._uploads_dir / "note.txt").read_bytes(), b"hello")
        response = self.client.post("/api/upload", headers=self.headers, files={"file":("malware.exe", b"x", "application/octet-stream")})
        self.assertEqual(response.status_code, 400)

    def test_body_limit_and_command_validation(self):
        self.server._session_ready = lambda: True
        response = self.client.post("/api/command", headers=self.headers, json={"text":"x"*40000})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/api/command", headers=self.headers, json={"text":{}})
        self.assertIn(response.status_code, (200, 400))
        self.assertTrue(self.server._command_queue.empty())

    def test_device_rotation_and_revoke(self):
        self.server._device_sessions["old"] = {"session_key":"abc123", "expires":time.time()+3600}
        response = self.client.post("/api/device-login", json={"device_token":"old"})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["device_token"], "old")
        self.assertNotIn("old", self.server._device_sessions)
        self.assertEqual(self.client.post("/api/device-login", json={"device_token":"old"}).status_code, 401)
        self.assertEqual(self.client.post("/api/revoke-devices", headers=self.headers).status_code, 200)
        self.assertFalse(self.server._tokens)

    def test_websocket_rejects_foreign_origin(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws?token="+self.token, headers={"Origin":"https://evil.test"}):
                self.fail("Foreign origin accepted")

if __name__ == "__main__":
    unittest.main()

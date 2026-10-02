import ast
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from core import confirm
from core.permission_manager import PermissionManager, Risk, policy_for
from core.intent_router import route
from core.sandbox import validate, run
from core.workflows import WorkflowManager
from core.automation import AutomationEngine
from core.project_memory import ProjectMemory
from core.remote_security import RateLimiter, safe_upload_name, same_origin

class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = PermissionManager(Path(self.temp.name) / "permissions.json")
        self.shown = []
        confirm._pending = None
        confirm.bind(lambda title, detail: self.shown.append((title, detail)), lambda: None)
        self.addCleanup(lambda: confirm.bind(None, None))
        self.addCleanup(lambda: setattr(confirm, "_pending", None))

    def test_model_cannot_confirm_and_arguments_are_bound(self):
        calls, finished = [], threading.Event()
        params = {"receiver": "Alice", "message_text": "hello", "confirmed": True}
        def send(args):
            calls.append(args)
            finished.set()
            return "sent"
        self.assertIn("CONFIRMATION_PENDING", self.manager.invoke("send_message", params, send))
        params["receiver"] = "Mallory"
        self.assertFalse(calls)
        self.assertIn("Alice", self.shown[0][1])
        confirm.resolve(True)
        self.assertTrue(finished.wait(2))
        self.assertEqual(calls[0]["receiver"], "Alice")
        self.assertNotIn("confirmed", calls[0])
        confirm.resolve(True)
        self.assertEqual(len(calls), 1)

    def test_pending_request_cannot_be_replaced(self):
        first, second = Mock(), Mock()
        self.manager.invoke("send_message", {"receiver": "A"}, first)
        self.manager.invoke("send_message", {"receiver": "B"}, second)
        self.assertEqual(len(self.shown), 1)
        self.assertIn('"A"', self.shown[0][1])
        confirm.resolve(False)
        first.assert_not_called()
        second.assert_not_called()

    def test_expiry_and_policy_change(self):
        handler = Mock()
        self.manager.invoke("send_message", {}, handler)
        confirm._pending.at -= 100
        confirm.resolve(True)
        handler.assert_not_called()
        self.manager.invoke("send_message", {}, handler)
        self.manager.set("messages", "Deny")
        confirm.resolve(True)
        time.sleep(.03)
        handler.assert_not_called()

    def test_critical_always_asks_even_allow(self):
        self.manager.set("terminal", "Allow")
        self.assertEqual(self.manager.decision("dev_agent", {})[1], "ask")
        self.assertEqual(self.manager.decision("open_app", {"app_name": "calculator"})[1], "allow")
        self.assertEqual(self.manager.decision("open_app", {"app_name": "powershell -c whoami"})[1], "ask")

    def test_corrupt_policy_denies_and_while_active(self):
        self.manager.path.write_text('{broken')
        self.assertEqual(self.manager.decision("system_status", {})[1], "deny")
        self.manager.path.unlink()
        self.manager.set("screen", "Allow While Active")
        self.assertEqual(self.manager.decision("screen_process", {}, active=False)[1], "deny")

    def test_headless_fails_closed(self):
        confirm.bind(None, None)
        handler = Mock()
        self.assertIn("not available", self.manager.invoke("send_message", {}, handler))
        handler.assert_not_called()

    def test_unknown_actions_fail_closed(self):
        self.assertEqual(policy_for("new_unreviewed_plugin").risk, Risk.CRITICAL)

class RoutingTests(unittest.TestCase):
    def test_local_and_mixed_language(self):
        for text in ("open chrome", "Jarvis Chrome open karo."):
            self.assertEqual(route(text).parameters, {"app_name": "chrome"})
        self.assertEqual(route("Volume thora kam karo").parameters["action"], "volume_down")
        self.assertEqual(route("show battery").name, "system_status")

    def test_ambiguous_or_destructive_not_fuzzy_routed(self):
        for text in ("open chrome and send a message", "delete all files", "could you explain volume", "open powershell"):
            self.assertIsNone(route(text))

class OfflineIntegrationTests(unittest.TestCase):
    def test_text_command_dispatches_without_live_session(self):
        from main import JarvisLive
        finished = threading.Event()
        assistant = object.__new__(JarvisLive)
        assistant._loop = None
        assistant.session = None
        assistant.ui = SimpleNamespace(write_log=lambda text: finished.set())
        assistant._action_registry = SimpleNamespace(run=Mock(return_value="Opened calculator"))
        assistant._on_text_command("open calculator")
        self.assertTrue(finished.wait(2))
        assistant._action_registry.run.assert_called_once()
        self.assertEqual(assistant._action_registry.run.call_args.args[0], "open_app")

class SandboxTests(unittest.TestCase):
    def test_rejects_escapes(self):
        for code in ("import os", "open('secret').read()", "eval('1')", "exec('1')", "getattr(print, '__globals__')", "pyautogui.__dict__", "Path('/').unlink()", "while True: print(1)", "[print(1) for x in range(9)]", "f = pyautogui.click; f()", "pyautogui.click(**{})"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate(code)

    def test_actual_allowlisted_instruction(self):
        desktop = SimpleNamespace(click=Mock())
        result = run("x = 12\npyautogui.click(x, 20)\nprint('issued')", desktop)
        desktop.click.assert_called_once_with(12, 20)
        self.assertEqual(result, "issued")
        with self.assertRaises(ValueError):
            run("time.sleep(1000)", desktop)

    def test_path_restrictions(self):
        from core.project_sandbox import safe_path
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(safe_path(folder, "src/a.py"), Path(folder) / "src/a.py")
            for name in ("../x.py", "C:\\Windows\\x.py", "/etc/passwd", "a/../../x", "."):
                with self.assertRaises(ValueError):
                    safe_path(folder, name)

    def test_host_never_runs_when_sandbox_missing(self):
        from core.project_sandbox import command
        with patch("memory.config_manager.load_api_keys", return_value={}), patch("subprocess.run") as runner:
            with self.assertRaises(RuntimeError):
                command("python main.py", Path.cwd(), 1)
            runner.assert_not_called()

class WorkflowTests(unittest.TestCase):
    def test_validation_recording_and_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = WorkflowManager(folder)
            with self.assertRaises(ValueError):
                manager.save({"name": "bad", "steps": [{"name": "send_message", "parameters": {}}]})
            manager.record("morning")
            manager.observe("open_app", {"app_name": "calculator"})
            manager.observe("send_message", {"message_text": "private"})
            workflow = manager.finish_recording()
            self.assertEqual(len(workflow["steps"]), 1)
            calls = []
            manager.dispatch = lambda name, args: calls.append(name) or "Opened"
            manager.run(workflow["id"])
            deadline = time.monotonic() + 2
            while manager.state == "running" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(manager.state, "completed")
            self.assertEqual(calls, ["open_app"])

    def test_workflow_stops_on_denied_step(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = WorkflowManager(folder)
            row = manager.save({"name": "test", "steps": [{"name": "open_app", "parameters": {"app_name": "chrome"}}]*2})
            callback = Mock(return_value="Permission denied")
            manager.dispatch = callback
            manager.run(row["id"])
            deadline = time.monotonic()+2
            while manager.state == "running" and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(manager.state, "stopped")
            self.assertEqual(callback.call_count, 1)

class AutomationTests(unittest.TestCase):
    def test_duration_edges_cooldown_and_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = [0]
            engine = AutomationEngine(Path(folder)/"rules.json", lambda: clock[0])
            action = Mock(return_value="notified")
            engine.dispatch = action
            row = engine.save({"name": "CPU", "trigger": {"field":"cpu_percent", "op":"gt", "value":90}, "duration":300, "action":{"name":"notify"}})
            engine.tick({"cpu_percent":99})
            clock[0] = 299
            engine.tick({"cpu_percent":99})
            action.assert_not_called()
            clock[0] = 301
            engine.tick({"cpu_percent":99})
            engine.tick({"cpu_percent":99})
            self.assertEqual(action.call_count, 1)
            row["enabled"] = False
            engine.save(row)
            engine.tick({"cpu_percent":99})
            self.assertEqual(action.call_count, 1)

    def test_sensitive_automation_rejected(self):
        engine = AutomationEngine()
        with self.assertRaises(ValueError):
            engine.save({"name":"bad", "trigger":{"field":"charging", "op":"eq", "value":False}, "action":{"name":"dev_agent"}})

class StorageTests(unittest.TestCase):
    def test_memory_dedup_version_pin_and_protection(self):
        from memory import memory_manager as m
        with tempfile.TemporaryDirectory() as folder, patch.object(m, "MEMORY_PATH", Path(folder)/"facts.json"):
            m.remember("color", "dark", "preferences")
            m.remember("other_color", "dark", "preferences")
            self.assertEqual(len(m.load_memory()["preferences"]), 1)
            m.remember("color", "light", "preferences")
            entry = m.load_memory()["preferences"]["color"]
            self.assertEqual(entry["previous_value"], "dark")
            self.assertIn("id", entry)
            m.pin_memory("preferences", "color")
            m.remember("name", "Owner", "identity")
            with patch.object(m, "MEMORY_MAX_CHARS", 1):
                m.save_memory(m.load_memory())
            self.assertIn("color", m.load_memory()["preferences"])
            self.assertIn("name", m.load_memory()["identity"])

    def test_project_path_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectMemory(Path(folder)/"projects.json")
            first = manager.save({"name":"app", "path":folder, "last_task":"auth"})
            second = manager.save({"name":"app", "path":folder, "last_task":"tests"})
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(manager.list()), 1)
            self.assertEqual(manager.list("tests")[0]["last_task"], "tests")

class RemoteHelpersTests(unittest.TestCase):
    def test_rate_limit_recovers(self):
        now = [0]
        limiter = RateLimiter(2, 60, lambda: now[0])
        self.assertTrue(limiter.allow("ip"))
        self.assertTrue(limiter.allow("ip"))
        self.assertFalse(limiter.allow("ip"))
        now[0] = 61
        self.assertTrue(limiter.allow("ip"))

    def test_upload_and_origin(self):
        self.assertEqual(safe_upload_name("../../report.txt"), "report.txt")
        for name in ("CON.txt", "run.exe", "file.html", ".."): 
            with self.assertRaises(ValueError):
                safe_upload_name(name)
        self.assertTrue(same_origin("https://127.0.0.1:8000", "127.0.0.1:8000"))
        self.assertFalse(same_origin("https://evil.test", "127.0.0.1:8000"))

class PackagingTests(unittest.TestCase):
    def test_private_files_excluded(self):
        from scripts.build_release import included
        for path in ("config/api_keys.json", "config/certs/jarvis.key", "memory/long_term.json", "memory/jobs.db", ".venv/a.py", "core/__pycache__/a.py", "workflows/private.json", "uploads/data.txt"):
            self.assertFalse(included(Path(path)), path)
        self.assertTrue(included(Path("main.py")))
        self.assertTrue(included(Path("config/__init__.py")))
        self.assertTrue(included(Path("config/api_keys.example.json")))

class ArchiveTests(unittest.TestCase):
    def test_traversal_and_overwrite_are_rejected(self):
        import zipfile
        from core.archive_safety import extract
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../outside.txt", "bad")
            with self.assertRaises(ValueError):
                extract(archive, root / "out")
            self.assertFalse((root / "outside.txt").exists())
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("safe.txt", "good")
            extract(archive, root / "out")
            self.assertEqual((root / "out" / "safe.txt").read_text(), "good")
            with self.assertRaises(ValueError):
                extract(archive, root / "out")

class EventTests(unittest.TestCase):
    def test_subscriber_failure_and_unsubscribe(self):
        from core.event_bus import EventBus
        bus = EventBus()
        received = []
        def bad(event, payload):
            raise RuntimeError("private exception")
        bus.subscribe("event", bad)
        remove = bus.subscribe("event", lambda event, payload: received.append(payload))
        bus.emit("event", value=1)
        remove()
        bus.emit("event", value=2)
        self.assertEqual(received, [{"value":1}])

if __name__ == "__main__":
    unittest.main()

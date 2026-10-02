"""Optional real-browser validation using temporary identities and mocked PC actions.

Run manually with playwright and Edge installed; never starts the real assistant.
"""
import os
import asyncio
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from playwright.sync_api import sync_playwright
    import uvicorn
    from core.dashboard_tls import ensure_certificate
    from core.remote_store import RemoteStore, CAPABILITIES
    from dashboard.server import DashboardServer
    from core.workflows import WorkflowManager
    from core.automation import AutomationEngine
    output = ROOT / "validation"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store = RemoteStore(base / "remote.db")
        definitions = WorkflowManager(base / "workflows")
        definitions.save({"name": "Example workflow", "steps": [{"name": "open_app", "parameters": {"app_name": "calculator"}}]})
        automation = AutomationEngine(base / "automations.json")
        automation.dispatch = lambda name, args: "Fixture notification returned"
        automation.save({"name": "Example automation", "trigger": {"field": "cpu_percent", "op": "gt", "value": 95},
                         "action": {"name": "notify", "parameters": {"text": "Fixture notice"}}, "enabled": False})
        cfg = {"remote_control_enabled": True, "allow_device_pairing": True,
               "remote_features": dict.fromkeys(CAPABILITIES, True), "remote_file_roots": [tmp]}
        ensure_certificate(base, "127.0.0.1")
        with patch("core.dashboard_tls.ensure_certificate"), patch("dashboard.server._local_ip", return_value="127.0.0.1"), \
                patch("dashboard.remote_api.remote_store", return_value=store), \
                patch("dashboard.remote_api.load_api_keys", side_effect=lambda: cfg), \
                patch("core.workflows.workflows", definitions), patch("core.automation.automations", automation), \
                patch("core.jobs.recent", return_value=[]), patch("core.project_memory.projects.list", return_value=[]):
            dashboard = DashboardServer()
            async def capture_loop():
                dashboard.test_loop = asyncio.get_running_loop()
            dashboard._startup_callbacks.append(capture_loop)
            actions = []
            dashboard.remote_dispatch = lambda name, args: actions.append((name, args)) or "Simulated action returned"
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(dashboard.app, log_level="error", access_log=False,
                                    ssl_keyfile=str(base / "config/certs/jarvis.key"),
                                    ssl_certfile=str(base / "config/certs/jarvis.crt")))
            thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(.05)
                assert server.started, "Temporary test server did not start"
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel="msedge", headless=True, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
                    try:
                        context = browser.new_context(ignore_https_errors=True, viewport={"width": 390, "height": 844}, device_scale_factor=1)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"https://127.0.0.1:{port}/remote#pair={dashboard.new_key()}")
                        page.get_by_role("button", name="Request trust", exact=True).click()
                        page.wait_for_function("document.getElementById('fingerprint').textContent.includes('SHA-256:')")
                        device = store.devices()[0]
                        assert not device["trusted"]
                        page.screenshot(path=str(output / "remote-pairing.png"), full_page=True)
                        store.trust(device["id"], list(CAPABILITIES))
                        page.get_by_role("button", name="Connect after PC approval").click()
                        page.wait_for_function("!document.getElementById('dashboard').hidden")
                        page.get_by_role("heading", name="PC status").wait_for()
                        page.locator(".metric").first.wait_for()
                        page.screenshot(path=str(output / "remote-computer.png"), full_page=True)
                        page.get_by_role("button", name="Commands", exact=True).click()
                        page.get_by_placeholder("What should the PC do?").fill("open calculator")
                        page.get_by_role("button", name="Send command", exact=True).click()
                        page.wait_for_function("document.getElementById('notice').textContent.includes('Received by PC')")
                        page.get_by_role("button", name="Jobs", exact=True).click()
                        page.get_by_text("Simulated action returned", exact=True).wait_for()
                        assert len(actions) == 1, actions
                        page.screenshot(path=str(output / "remote-jobs.png"), full_page=True)
                        store.save_profile({"name": "Temporary validation task", "cwd": tmp,
                            "argv": [sys.executable, "-c", "print('PROJECT_BROWSER_OK')"], "enabled": True, "timeout": 10})
                        page.get_by_role("button", name="Projects", exact=True).click()
                        page.get_by_role("heading", name="Temporary validation task").wait_for()
                        page.screenshot(path=str(output / "remote-projects.png"), full_page=True)
                        page.get_by_role("button", name="Run command", exact=True).click()
                        page.wait_for_function("document.getElementById('notice').textContent.includes('Job accepted')")
                        page.get_by_role("button", name="Jobs", exact=True).click()
                        page.get_by_text("PROJECT_BROWSER_OK", exact=True).wait_for(timeout=15000)
                        page.get_by_role("button", name="Notifications", exact=True).click()
                        page.get_by_role("heading", name="Command completed", exact=True).wait_for()
                        page.screenshot(path=str(output / "remote-notifications.png"), full_page=True)
                        page.get_by_role("button", name="Mark read", exact=True).first.click()
                        page.get_by_role("button", name="Workflows", exact=True).click()
                        page.get_by_role("button", name="Run workflow", exact=True).click()
                        page.wait_for_function("document.getElementById('notice').textContent.includes('Workflow accepted')")
                        page.get_by_role("button", name="Jobs", exact=True).click()
                        page.get_by_text("All 1 steps returned. Individual action outcomes are unverified.", exact=True).wait_for(timeout=15000)
                        page.get_by_role("button", name="Automations", exact=True).click()
                        page.get_by_role("button", name="Enable", exact=True).click()
                        page.get_by_role("button", name="Run now", exact=True).wait_for()
                        page.screenshot(path=str(output / "remote-automations.png"), full_page=True)
                        page.get_by_role("button", name="Run now", exact=True).click()
                        page.wait_for_function("document.getElementById('notice').textContent.includes('Automation accepted')")
                        page.get_by_role("button", name="Jobs", exact=True).click()
                        page.get_by_text("Fixture notification returned", exact=True).wait_for(timeout=15000)
                        page.reload()
                        page.wait_for_function("!document.getElementById('dashboard').hidden")
                        assert page.evaluate("identity.privateKey.extractable") is False
                        dashboard._session_ready = lambda: True
                        page.get_by_role("button", name="Chat", exact=True).click()
                        page.get_by_role("button", name="Start microphone", exact=True).click()
                        page.wait_for_function("document.getElementById('micState').textContent.includes('MICROPHONE LIVE')")
                        for _ in range(100):
                            if not dashboard._phone_audio_queue.empty():
                                break
                            time.sleep(.02)
                        assert not dashboard._phone_audio_queue.empty(), "Fake browser microphone did not reach the PC queue"
                        page.get_by_role("button", name="Stop microphone", exact=True).click()
                        page.wait_for_function("microphone===null")
                        page.get_by_role('button', name='Play replies on phone', exact=True).click()
                        page.wait_for_function("document.getElementById('speakerState').textContent.includes('speaker on')")
                        dashboard.test_loop.call_soon_threadsafe(dashboard.remote_publish_audio, b'\x00\x00' * 1200)
                        page.wait_for_function('speaker.next > 0')
                        page.screenshot(path=str(output / 'remote-phone-audio.png'), full_page=True)
                        page.get_by_role('button', name='Stop phone speaker', exact=True).click()
                        page.wait_for_function('speaker===null')
                        page.get_by_role('button', name='Notifications', exact=True).click()
                        page.get_by_role('button', name='Enable phone alerts', exact=True).wait_for()
                        page.screenshot(path=str(output / 'remote-push-controls.png'), full_page=True)
                        assert not errors, errors
                        store.revoke(device["id"])
                        page.get_by_role("button", name="Computer", exact=True).click()
                        page.wait_for_function("document.getElementById('notice').textContent.includes('not trusted')")
                        print("Browser: signing, pairing, receipts, real temporary project task, workflows, automations, notifications, fake audio and revocation passed.")
                    finally:
                        browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                listener.close()
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont, QFontDatabase
        from core.remote_panel import RemotePanel
        app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        app.setFont(QFont("Segoe UI", 10))
        with patch("core.remote_panel.remote_store", return_value=store), patch("core.remote_panel.load_api_keys", return_value=cfg):
            panel = RemotePanel()
            panel.setStyleSheet("QWidget {background:#0c1420;color:#d6e8f5;font-family:'Segoe UI';font-size:13px} QLineEdit,QListWidget {background:#142237;border:1px solid #30465e;padding:5px} QPushButton {background:#17354a;border:1px solid #3584a4;padding:7px}")
            panel.resize(900, 700)
            panel.show()
            app.processEvents()
            panel.devices.setCurrentRow(0)
            app.processEvents()
            panel.grab().save(str(output / "remote-devices-desktop.png"))
            style = panel.styleSheet()
            panel.close()
        from core.remote_project_panel import RemoteProjectPanel
        with patch("core.remote_project_panel.remote_store", return_value=store):
            panel = RemoteProjectPanel()
            panel.setStyleSheet(style)
            panel.resize(900, 800)
            panel.show()
            panel.table.selectRow(0)
            app.processEvents()
            panel.grab().save(str(output / "remote-projects-desktop.png"))
            panel.close()
        print("Desktop device panel rendered with temporary test data.")


if __name__ == "__main__":
    main()

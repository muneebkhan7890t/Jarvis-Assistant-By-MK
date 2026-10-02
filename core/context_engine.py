"""Ephemeral context. Clipboard and screenshots are never sampled here."""
from collections import deque
from threading import RLock
import time

class ContextEngine:
    def __init__(self):
        self._lock = RLock()
        self._recent = deque(maxlen=20)
        self._state = {}

    def snapshot(self):
        import psutil
        state = {"sampled_at": time.time(), "cpu_percent": psutil.cpu_percent(),
                 "ram_percent": psutil.virtual_memory().percent}
        battery = psutil.sensors_battery()
        state["battery_percent"] = battery.percent if battery else None
        state["charging"] = battery.power_plugged if battery else None
        state["network_connected"] = any(s.isup for n, s in psutil.net_if_stats().items() if n.lower() not in ("lo", "loopback"))
        try:
            import sys
            if sys.platform == "win32":
                import win32gui, win32process
                handle = win32gui.GetForegroundWindow()
                state["window_title"] = win32gui.GetWindowText(handle)
                _, pid = win32process.GetWindowThreadProcessId(handle)
                state["process_name"] = psutil.Process(pid).name()
        except (ImportError, OSError, psutil.Error):
            state["window_title"] = None
        with self._lock:
            if state.get("window_title") != self._state.get("window_title"):
                self._recent.append({"window_title": state.get("window_title"), "at": state["sampled_at"]})
            self._state = state
            return {**state, "recent_applications": list(self._recent)}

    def resolve(self, reference):
        state = self.snapshot()
        if reference.strip().lower() in ("it", "this app", "current app"):
            return state.get("process_name")
        return None

context = ContextEngine()

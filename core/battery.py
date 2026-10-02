"""Battery readings and one warning per threshold, with a reminder cooldown."""
import time
import psutil


def snapshot():
    try:
        value = psutil.sensors_battery()
        if value is None:
            return None
        return {'percent': round(float(value.percent), 1), 'plugged': bool(value.power_plugged)}
    except (AttributeError, OSError, RuntimeError, NotImplementedError):
        return None


class BatteryMonitor:
    def __init__(self, clock=time.monotonic, cooldown=900):
        self.clock = clock
        self.cooldown = cooldown
        self.level = 0
        self.last = float('-inf')

    def check(self, battery):
        if battery is None or battery['plugged'] or battery['percent'] > 20:
            self.level = 0
            return None
        level = 2 if battery['percent'] <= 10 else 1
        now = self.clock()
        if level > self.level or now - self.last >= self.cooldown:
            self.level, self.last = level, now
            label = 'critically low' if level == 2 else 'low'
            return f"Sir, your battery is {label} at {battery['percent']:g}%. Please connect your charger."
        return None


def speak_locally(text):
    """Windows fallback when the cloud session is asleep/offline. No network needed."""
    import sys
    if sys.platform != 'win32':
        return False
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            win32com.client.Dispatch('SAPI.SpVoice').Speak(text)
            return True
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return False

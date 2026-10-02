"""Read-only installation diagnostics; no model calls or microphone capture."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def check():
    started = time.perf_counter()
    results = {"python": {"ok": sys.version_info >= (3, 11), "version": sys.version.split()[0]}}
    for module in ("PyQt6", "sounddevice", "numpy", "google.genai", "psutil", "fastapi", "cryptography", "playwright"):
        try:
            found = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            found = False
        results[module] = {"ok": found}
    from memory.config_manager import get_gemini_key
    results["credentials"] = {"ok": bool(get_gemini_key()), "note": "Not required for offline text mode"}
    with sqlite3.connect(":memory:") as db:
        results["sqlite"] = {"ok": db.execute("pragma integrity_check").fetchone()[0] == "ok"}
    results["disk"] = {"ok": shutil.disk_usage(ROOT).free > 100*1024*1024}
    results["docker"] = {"ok": bool(shutil.which("docker")), "note": "Optional; required for generated project execution"}
    results["duration_ms"] = round((time.perf_counter()-started)*1000, 2)
    return results

if __name__ == "__main__":
    print(json.dumps(check(), indent=2))

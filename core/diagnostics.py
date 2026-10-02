"""Bounded, content-free action history and monotonic latency samples."""
from collections import deque
from datetime import datetime, timezone
from threading import RLock
import json
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

_lock = RLock()
_history = deque(maxlen=500)

def record(event, action="", source="local", risk="LOW", duration_ms=0, status=""):
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(), event=event,
               action=action, source=source, risk=risk,
               duration_ms=round(duration_ms, 3), status=status)
    with _lock:
        _history.append(row)
    logging.getLogger("jarvis.audit").info(json.dumps(row))
    from core.event_bus import bus
    bus.emit(event, **{k: v for k, v in row.items() if k != "event"})
    return row

def history():
    with _lock:
        return list(_history)

def configure(folder):
    logger = logging.getLogger("jarvis.audit")
    if logger.handlers:
        return
    Path(folder).mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(Path(folder) / "security.jsonl", maxBytes=1000000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

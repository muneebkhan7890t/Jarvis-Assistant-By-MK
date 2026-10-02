"""Thread-safe events; subscriber failures cannot stop an action."""
from collections import defaultdict
import logging
from threading import RLock

class EventBus:
    def __init__(self):
        self._lock = RLock()
        self._listeners = defaultdict(list)

    def subscribe(self, event, callback):
        with self._lock:
            self._listeners[event].append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._listeners[event]:
                    self._listeners[event].remove(callback)
        return unsubscribe

    def emit(self, event, **fields):
        with self._lock:
            callbacks = tuple(self._listeners[event]) + tuple(self._listeners["*"])
        for callback in callbacks:
            try:
                callback(event, fields)
            except Exception:
                logging.getLogger(__name__).warning("Event subscriber failed: %s", event)

bus = EventBus()

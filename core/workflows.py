"""Semantic, editable action workflows with cooperative pause/cancel.

No raw keystroke recording, passwords or payment steps. Every step uses the
same registry permission gate as interactive commands.
"""
from copy import deepcopy
import json
from pathlib import Path
from threading import Condition, RLock, Thread
import uuid
from core.permission_manager import policy_for, Risk

class WorkflowManager:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else Path(__file__).resolve().parents[1] / "workflows"
        self.lock = RLock()
        self.condition = Condition(self.lock)
        self.state = "idle"
        self.error = ""
        self.index = 0
        self.dispatch = None
        self._recording = None

    def validate(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("Workflow name is required")
        steps = data.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
            raise ValueError("A workflow requires 1-100 semantic steps")
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("parameters"), dict):
                raise ValueError("Each step needs name and parameters")
            policy = policy_for(step.get("name"), step["parameters"])
            if policy.risk in (Risk.HIGH, Risk.CRITICAL):
                raise ValueError("High-risk steps must be performed interactively, not recorded or replayed")
        return deepcopy(data)

    def save(self, data):
        data = self.validate(data)
        ident = data.get("id") or uuid.uuid4().hex
        if not isinstance(ident, str) or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
            raise ValueError("Invalid workflow ID")
        data["id"] = ident
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            temp = self.folder / (ident + ".tmp")
            temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp.replace(self.folder / (ident + ".json"))
        return data

    def list(self):
        with self.lock:
            return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.folder.glob("*.json"))]

    def get(self, ident):
        rows = [r for r in self.list() if r["id"] == ident or r["name"].casefold() == ident.casefold()]
        if len(rows) != 1:
            raise ValueError("Workflow missing or name ambiguous; use its ID")
        return rows[0]

    def delete(self, ident):
        row = self.get(ident)
        with self.lock:
            (self.folder / (row["id"] + ".json")).unlink()

    def record(self, name):
        with self.lock:
            if self._recording is not None:
                raise ValueError("A recording is already active")
            self._recording = {"name": name, "steps": []}

    def observe(self, name, parameters):
        if policy_for(name, parameters).risk != Risk.LOW:
            return
        with self.lock:
            if self._recording is not None and len(self._recording["steps"]) < 100:
                self._recording["steps"].append({"name": name, "parameters": deepcopy(parameters)})

    def finish_recording(self):
        with self.lock:
            if self._recording is None:
                raise ValueError("No recording is active")
            row = self.save(self._recording)
            self._recording = None
            return row

    def control(self, action):
        with self.condition:
            if action == "pause" and self.state == "running":
                self.state = "paused"
            elif action == "resume" and self.state == "paused":
                self.state = "running"
            elif action == "stop" and self.state in ("running", "paused"):
                self.state = "cancelled"
            self.condition.notify_all()
            return self.state

    def run(self, ident):
        data = self.validate(self.get(ident))
        if self.dispatch is None:
            raise RuntimeError("Action registry is not connected")
        with self.condition:
            if self.state in ("running", "paused"):
                raise ValueError("A workflow is already running")
            self.state, self.error, self.index = "running", "", 0
        def worker():
            try:
                for index, step in enumerate(data["steps"]):
                    with self.condition:
                        self.condition.wait_for(lambda: self.state != "paused")
                        if self.state == "cancelled":
                            return
                        self.index = index
                    result = str(self.dispatch(step["name"], step["parameters"]))
                    if any(w in result.lower() for w in ("confirmation", "denied", "failed", "error", "cannot", "could not")):
                        raise RuntimeError("Workflow stopped at step %d: %s" % (index + 1, result))
                with self.lock:
                    self.state = "completed"
            except Exception as exc:
                with self.lock:
                    self.state, self.error = "stopped", str(exc)
        Thread(target=worker, daemon=True, name="workflow").start()
        return "Workflow started."

workflows = WorkflowManager()

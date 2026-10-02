"""Device-scoped execution of saved low-risk workflows through the PC registry."""
import hashlib
import json
import threading
from core.permission_manager import manager, policy_for, Risk


def version(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RemoteWorkflows:
    def __init__(self, store, authorize, dispatch, definitions=None, permissions=None):
        from core.workflows import workflows
        self.store, self.authorize, self.dispatch = store, authorize, dispatch
        self.definitions, self.permissions = definitions or workflows, permissions or manager
        self.lock = threading.RLock()
        self.active = {}

    def listing(self):
        return [{"id": r["id"], "name": r["name"], "version": version(r), "steps": r.get("steps", [])}
                for r in self.definitions.list()]

    def checked(self, device_id, ident, expected):
        self.authorize(device_id, "workflows")
        if self.permissions.settings().get("monitoring") == "Deny":
            raise PermissionError("Workflow control is denied in PC permissions")
        if not isinstance(ident, str) or not isinstance(expected, str):
            raise ValueError("Workflow ID and version are required")
        row = self.definitions.validate(self.definitions.get(ident))
        if version(row) != expected:
            raise ValueError("Workflow changed on the PC; refresh before running")
        for step in row["steps"]:
            if policy_for(step["name"], step["parameters"]).risk != Risk.LOW:
                raise PermissionError("Remote workflows support low-risk steps only; use dedicated scoped controls for files and screen")
            if self.permissions.decision(step["name"], step["parameters"])[1] != "allow":
                raise PermissionError("PC permissions do not allow this workflow to run automatically")
        return row

    def start(self, device_id, ident, expected, request_id):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError("A stable request ID is required")
        row = self.checked(device_id, ident, expected)
        payload = {"type": "workflow", "workflow_id": ident, "version": expected, "text": row["name"]}
        with self.lock:
            with self.store.connect() as db:
                old = db.execute("SELECT id FROM commands WHERE device_id=? AND request_id=?", (device_id, request_id)).fetchone()
            if old:
                return self.store.enqueue(device_id, request_id, payload)
            if self.active:
                raise ValueError("A remote workflow is already running")
            command_id, created = self.store.enqueue(device_id, request_id, payload)
            stop = threading.Event()
            self.active[command_id] = (device_id, stop)
            try:
                threading.Thread(target=self._run, args=(command_id, device_id, ident, expected, stop),
                                 daemon=True, name="remote-workflow").start()
            except Exception:
                self.active.pop(command_id, None)
                self.store.update(command_id, "failed", {"message": "Could not start workflow worker"})
                raise
            return command_id, created

    def cancel(self, device_id, command_id):
        self.authorize(device_id, "workflows")
        row = self.store.receipt(device_id, command_id)
        if not row or row["payload"].get("type") != "workflow":
            raise ValueError("Workflow job not found for this device")
        with self.lock:
            active = self.active.get(command_id)
            if active and active[0] == device_id:
                active[1].set()
                return "Stop requested; the current action will finish before the next step is cancelled"
        return "Workflow job is already " + row["status"]

    def shutdown(self):
        with self.lock:
            for _device, stop in self.active.values():
                stop.set()

    def _run(self, command_id, device_id, ident, expected, stop):
        results = []
        status, message = "failed", "Workflow did not start"
        try:
            row = self.checked(device_id, ident, expected)
            for index, step in enumerate(row["steps"]):
                self.checked(device_id, ident, expected)
                if stop.is_set():
                    status, message = "cancelled", "Stopped before the next step; earlier actions are not undone"
                    break
                self.store.update(command_id, "running", {"message": f"Running step {index + 1} of {len(row['steps'])}",
                                                         "output": "\n".join(results)[-16000:]})
                result = str(self.dispatch(step["name"], step["parameters"]))[:4000]
                results.append(f"Step {index + 1}: {result}")
                if result.lower().startswith(("permission denied", "failed", "error", "cannot", "could not", "skill ", "action '", "tool '")) or "[CONFIRMATION_PENDING]" in result:
                    raise RuntimeError("Workflow stopped because a step did not return an allowed result")
            else:
                status, message = "returned", f"All {len(row['steps'])} steps returned. Individual action outcomes are unverified."
        except Exception as exc:
            status, message = "failed", str(exc)[:1000]
        finally:
            try:
                self.store.update(command_id, status, {"message": message, "output": "\n".join(results)[-16000:], "verified": False})
            finally:
                with self.lock:
                    self.active.pop(command_id, None)

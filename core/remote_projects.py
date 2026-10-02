"""PC-reviewed fixed project commands; durable, cancellable remote jobs."""
from collections import deque
import hashlib
import os
from pathlib import Path
import socket
import threading
import time
import uuid
from core.remote_process import OwnedProcess


def executable_hash(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_profile(value):
    if not isinstance(value, dict):
        raise ValueError("Project command must be an object")
    name = value.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Enter a project command name (1–100 characters)")
    if not isinstance(value.get("cwd"), str) or not value["cwd"].strip():
        raise ValueError("Choose a project directory")
    cwd = Path(value["cwd"]).expanduser().resolve(strict=True)
    if not cwd.is_dir() or cwd == Path(cwd.anchor) or str(cwd).startswith("\\\\"):
        raise ValueError("Choose a local project directory, not a drive root or network share")
    argv = value.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or any(not isinstance(a, str) or "\x00" in a or len(a) > 4000 for a in argv):
        raise ValueError("Enter an executable and at most 63 fixed arguments")
    if sum(map(len, argv)) > 20000:
        raise ValueError("Command arguments are too long")
    exe = Path(argv[0]).expanduser()
    if not exe.is_absolute():
        raise ValueError("Executable must be an absolute path")
    exe = exe.resolve(strict=True)
    if not exe.is_file() or str(exe).startswith("\\\\") or (os.name == "nt" and exe.suffix.lower() != ".exe"):
        raise ValueError("Select a local executable; batch files are not accepted directly")
    kind = value.get("kind", "task")
    if kind not in ("task", "server"):
        raise ValueError("Kind must be task or server")
    timeout = value.get("timeout", 300)
    if type(timeout) is not int or not 1 <= timeout <= (86400 if kind == "server" else 3600):
        raise ValueError("Use a 1–3600 second task timeout, or at most 86400 seconds for a server")
    port = value.get("port", 0)
    if type(port) is not int or not 0 <= port <= 65535 or (kind == "server" and not port):
        raise ValueError("Servers require a local health-check port (1–65535)")
    ident = value.get("id") or uuid.uuid4().hex
    if not isinstance(ident, str) or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
        raise ValueError("Invalid project command ID")
    enabled = value.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Invalid approval state")
    return {"id": ident, "name": name.strip(), "cwd": str(cwd), "argv": [str(exe), *argv[1:]],
            "kind": kind, "timeout": timeout, "port": port, "enabled": enabled,
            "executable_sha256": executable_hash(exe)}


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.15):
            return True
    except OSError:
        return False


class ProjectRunner:
    def __init__(self, store, authorize, permissions=None, process_factory=OwnedProcess):
        from core.permission_manager import manager
        self.store, self.authorize = store, authorize
        self.permissions = permissions or manager
        self.process_factory = process_factory
        self.lock = threading.RLock()
        self.active = {}

    def checked(self, device_id, profile_id, revision, check_hash=False):
        self.authorize(device_id, "projects")
        row = self.store.profile(profile_id)
        if not row["enabled"] or row["revision"] != revision:
            raise PermissionError("Project command was disabled or changed; review it again on the PC")
        if self.permissions.settings().get("terminal") == "Deny":
            raise PermissionError("Terminal execution is denied in PC permissions")
        if not Path(row["cwd"]).is_dir():
            raise ValueError("Approved project directory is unavailable")
        if check_hash and executable_hash(row["argv"][0]) != row["executable_sha256"]:
            raise PermissionError("The executable changed; review and save this command again on the PC")
        return row

    def start(self, device_id, profile_id, revision, request_id):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError("A stable request ID is required")
        if type(revision) is not int:
            raise ValueError("Expected project command revision is required")
        row = self.checked(device_id, profile_id, revision, check_hash=True)
        payload = {"type": "project", "profile_id": profile_id, "revision": revision, "text": row["name"]}
        with self.lock:
            # Idempotency is checked before the active-profile constraint.
            with self.store.connect() as db:
                old = db.execute("SELECT id FROM commands WHERE device_id=? AND request_id=?", (device_id, request_id)).fetchone()
            if old:
                command_id, created = self.store.enqueue(device_id, request_id, payload)
                return command_id, created
            if len(self.active) >= 2 or any(v["profile_id"] == profile_id for v in self.active.values()):
                raise ValueError("This project command is already running, or both worker slots are busy")
            command_id, created = self.store.enqueue(device_id, request_id, payload)
            if not created:
                return command_id, False
            stop = threading.Event()
            self.active[command_id] = {"stop": stop, "device_id": device_id, "profile_id": profile_id}
            try:
                threading.Thread(target=self._run, args=(command_id, device_id, profile_id, revision, stop),
                                 daemon=True, name="remote-project-" + command_id[:8]).start()
            except Exception:
                self.active.pop(command_id)
                self.store.update(command_id, "failed", {"message": "Could not start the project worker"})
                raise
        return command_id, True

    def cancel(self, device_id, command_id):
        self.authorize(device_id, "projects")
        row = self.store.receipt(device_id, command_id)
        if not row or row["payload"].get("type") != "project":
            raise ValueError("Project job not found for this device")
        with self.lock:
            active = self.active.get(command_id)
            if active and active["device_id"] == device_id:
                active["stop"].set()
                return "Stop requested; waiting for the process tree to terminate"
        return "Job is already " + row["status"]

    def shutdown(self):
        with self.lock:
            for job in self.active.values():
                job["stop"].set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.lock:
                if not self.active:
                    return
            time.sleep(.05)

    def _run(self, command_id, device_id, profile_id, revision, stop):
        process = reader = None
        tail, output_lock = deque(maxlen=16), threading.Lock()
        size, reader_error = [0], []
        status, message, exit_code = "failed", "Execution did not start", None
        def logs():
            with output_lock:
                raw = b"".join(tail)[-65536:]
                return raw.decode("utf-8", errors="replace"), size[0] > len(raw)
        try:
            row = self.checked(device_id, profile_id, revision, check_hash=True)
            if stop.is_set():
                status, message = "cancelled", "Cancelled before launch"
                return
            if row["kind"] == "server" and port_open(row["port"]):
                raise ValueError("Configured server port is already in use; no process was started")
            parameters = {"profile_id": profile_id, "revision": revision, "argv": row["argv"], "cwd": row["cwd"]}
            def grant():
                current = self.checked(device_id, profile_id, revision, check_hash=True)
                return current["argv"] == row["argv"] and current["cwd"] == row["cwd"]
            process = self.permissions.invoke_local_grant("remote_project_task", parameters,
                         lambda _args: self.process_factory(row["argv"], row["cwd"]), grant, source="phone")
            if isinstance(process, str):
                raise PermissionError(process)
            def read_output():
                try:
                    for chunk in process.chunks():
                        with output_lock:
                            tail.append(chunk)
                            size[0] += len(chunk)
                except Exception as exc:
                    reader_error.append(type(exc).__name__)
            reader = threading.Thread(target=read_output, daemon=True, name="project-output")
            reader.start()
            started, last_write = time.monotonic(), float("-inf")
            while True:
                self.checked(device_id, profile_id, revision)
                if stop.is_set():
                    status, message = "cancelled", "Stopped by the owner; project file changes are retained"
                    break
                if time.monotonic() - started >= row["timeout"]:
                    status, message = "failed", "Project command exceeded its approved time limit"
                    break
                exit_code = process.poll()
                if exit_code is not None:
                    status = "completed" if exit_code == 0 and row["kind"] == "task" else "failed"
                    message = f"{'Server stopped' if row['kind'] == 'server' else 'Process exited'} with code {exit_code}."
                    break
                if time.monotonic() - last_write >= 1:
                    output, truncated = logs()
                    reachable = port_open(row["port"]) if row["kind"] == "server" else None
                    self.store.update(command_id, "running", {"message": "Process running", "pid": process.pid,
                        "output": output, "truncated": truncated, "port_reachable": reachable,
                        "elapsed_seconds": round(time.monotonic() - started, 1)})
                    last_write = time.monotonic()
                stop.wait(.2)
        except Exception as exc:
            status, message = "failed", str(exc)[:1000]
        finally:
            if process is not None and not isinstance(process, str):
                try:
                    process.terminate()
                    if reader:
                        reader.join(timeout=3)
                    if process.wait(3) is None:
                        status, message = "failed", "Process termination could not be verified; inspect the PC"
                except Exception as exc:
                    status, message = "failed", "Process cleanup needs PC review: " + str(exc)[:300]
                finally:
                    process.close()
            output, truncated = logs()
            if reader_error:
                message += " Output capture ended with " + reader_error[0] + "."
            try:
                self.store.update(command_id, status, {"message": message, "exit_code": exit_code,
                    "output": output, "truncated": truncated, "verified": exit_code is not None,
                    "verification": "Process exit code only; application behavior is not independently verified"})
            finally:
                with self.lock:
                    self.active.pop(command_id, None)

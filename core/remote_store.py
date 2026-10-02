"""Persistent remote identities and encrypted command receipts. No network operations."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

CAPABILITIES = ("computer", "commands", "chat", "voice", "screen", "files", "projects", "workflows", "automations")


def _dpapi(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        error = ctypes.windll.kernel32.GetLastError()
        raise OSError(error, "Cannot unlock local remote storage for this Windows account")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class RemoteStore:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keypath = self.path.with_suffix(".key")
        if not keypath.exists():
            key = Fernet.generate_key()
            protected = _dpapi(key) if os.name == "nt" else key
            try:
                with open(keypath, "xb") as f:
                    f.write(protected)
                if os.name != "nt":
                    keypath.chmod(0o600)
            except FileExistsError:
                pass
        key = keypath.read_bytes()
        self.cipher = Fernet(_dpapi(key, True) if os.name == "nt" else key)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, public_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL, platform TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    created REAL NOT NULL, last_seen REAL, trusted INTEGER NOT NULL DEFAULT 0,
                    capabilities TEXT NOT NULL DEFAULT '[]');
                CREATE TABLE IF NOT EXISTS challenges (
                    nonce TEXT PRIMARY KEY, device_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, status TEXT NOT NULL,
                    payload BLOB NOT NULL, result BLOB, UNIQUE(device_id, request_id));
                CREATE TABLE IF NOT EXISTS project_profiles (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, dedupe TEXT NOT NULL,
                    created REAL NOT NULL, read_at REAL, payload BLOB NOT NULL,
                    UNIQUE(device_id,dedupe));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _seal(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def _open(self, value):
        return json.loads(self.cipher.decrypt(value)) if value else None

    def enroll(self, public_key, name, platform):
        if not isinstance(public_key, str) or len(public_key) > 512:
            raise ValueError("Invalid public key")
        raw = base64.b64decode(public_key, validate=True)
        key = serialization.load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("P-256 key required")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Device name must be 1–80 characters")
        if platform not in ("Android", "iPhone", "Other"):
            raise ValueError("Unknown platform")
        with self.lock, self.connect() as db:
            old = db.execute("SELECT * FROM devices WHERE public_key=?", (public_key,)).fetchone()
            if old:
                return dict(old)
            if db.execute("SELECT count(*) FROM devices").fetchone()[0] >= 32:
                raise ValueError("Device limit reached; remove an old request on the PC")
            device_id = uuid.uuid4().hex
            db.execute("INSERT INTO devices(id,public_key,name,platform,fingerprint,created) VALUES (?,?,?,?,?,?)",
                       (device_id, public_key, name.strip(), platform, hashlib.sha256(raw).hexdigest(), self.clock()))
        return self.device(device_id)

    def device(self, device_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["capabilities"] = json.loads(value["capabilities"])
        return value

    def devices(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM devices ORDER BY created DESC")]
        return [self.device(i) for i in ids]

    def trust(self, device_id, capabilities):
        """Desktop-only entry point: deliberately never exposed as an HTTP route."""
        if not isinstance(capabilities, list) or any(c not in CAPABILITIES for c in capabilities):
            raise ValueError("Invalid capabilities")
        with self.lock, self.connect() as db:
            db.execute("UPDATE devices SET trusted=1, capabilities=? WHERE id=?",
                       (json.dumps(sorted(set(capabilities))), device_id))

    def revoke(self, device_id):
        with self.lock, self.connect() as db:
            db.execute("UPDATE devices SET trusted=0, capabilities='[]' WHERE id=?", (device_id,))
            db.execute("DELETE FROM challenges WHERE device_id=?", (device_id,))

    def remove(self, device_id):
        self.revoke(device_id)
        with self.connect() as db:
            db.execute("DELETE FROM devices WHERE id=?", (device_id,))

    def challenge(self, device_id):
        if not isinstance(device_id, str) or len(device_id) != 32:
            raise ValueError("Invalid device ID")
        now, nonce = self.clock(), secrets.token_urlsafe(32)
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM challenges WHERE expires<=?", (now,))
            if db.execute("SELECT count(*) FROM challenges").fetchone()[0] >= 512:
                raise ValueError("Too many pending challenges")
            # Do not reveal whether an ID is registered or trusted.
            db.execute("INSERT INTO challenges VALUES (?,?,?)", (nonce, device_id, now + 30))
        return {"nonce": nonce, "expires": now + 30}

    def verify(self, device_id, nonce, signature, method, path, body):
        """WebCrypto P1363 signatures bind exact bytes, target and a one-use server nonce."""
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = db.execute("SELECT * FROM challenges WHERE nonce=? AND device_id=?", (nonce, device_id)).fetchone()
            db.execute("DELETE FROM challenges WHERE nonce=?", (nonce,))
        device = self.device(device_id)
        if not challenge or challenge["expires"] <= self.clock() or not device or not device["trusted"]:
            raise PermissionError("Device is not trusted or challenge expired")
        message = f"MARK-LIV-REMOTE-v1\n{device_id}\n{nonce}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}".encode()
        try:
            raw = base64.b64decode(signature, validate=True)
            if len(raw) != 64:
                raise ValueError()
            sig = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
            key = serialization.load_der_public_key(base64.b64decode(device["public_key"]))
            key.verify(sig, message, ec.ECDSA(hashes.SHA256()))
        except Exception as exc:
            raise PermissionError("Invalid device signature") from exc
        with self.connect() as db:
            db.execute("UPDATE devices SET last_seen=? WHERE id=?", (self.clock(), device_id))
        return device

    def enqueue(self, device_id, request_id, payload):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError("A stable request ID is required")
        now = self.clock()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM commands WHERE device_id=? AND request_id=?", (device_id, request_id)).fetchone()
            if old:
                if self._open(old["payload"]) != payload:
                    raise ValueError("Request ID already used for a different command")
                return old["id"], False
            if db.execute("SELECT count(*) FROM commands WHERE status IN ('queued','running')").fetchone()[0] >= 32:
                raise ValueError("Command queue is full")
            command_id = uuid.uuid4().hex
            db.execute("INSERT INTO commands VALUES (?,?,?,?,?,?,?,NULL)",
                       (command_id, device_id, request_id, now, now, "queued", self._seal(payload)))
        return command_id, True

    def update(self, command_id, status, result=None):
        if status not in ("running", "completed", "failed", "cancelled", "returned", "confirmation_requested"):
            raise ValueError("Invalid command status")
        with self.lock, self.connect() as db:
            db.execute("UPDATE commands SET status=?,result=?,updated=? WHERE id=?",
                       (status, self._seal(result), self.clock(), command_id))
            if status in ("completed", "failed", "cancelled", "returned", "confirmation_requested"):
                row = db.execute("SELECT device_id FROM commands WHERE id=?", (command_id,)).fetchone()
                if row:
                    payload = {"title": "Command " + status.replace("_", " "),
                               "message": str((result or {}).get("message", ""))[:2000] if isinstance(result, dict) else str(result)[:2000],
                               "priority": "Important" if status in ("failed", "confirmation_requested") else "Normal",
                               "command_id": command_id}
                    db.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,NULL,?)",
                               (uuid.uuid4().hex, row["device_id"], command_id + ":" + status, self.clock(), self._seal(payload)))

    def receipt(self, device_id, command_id):
        if not isinstance(command_id, str) or len(command_id) != 32:
            raise ValueError("Invalid command ID")
        with self.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE id=? AND device_id=?", (command_id, device_id)).fetchone()
        return {**dict(row), "payload": self._open(row["payload"]), "result": self._open(row["result"])} if row else None

    def notifications(self, device_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM notifications WHERE device_id=? ORDER BY created DESC LIMIT 100", (device_id,)).fetchall()
        return [{"id": r["id"], "created": r["created"], "read_at": r["read_at"], **self._open(r["payload"])} for r in rows]

    def read_notification(self, device_id, notification_id):
        if not isinstance(notification_id, str) or len(notification_id) != 32:
            raise ValueError("Invalid notification ID")
        with self.connect() as db:
            changed = db.execute("UPDATE notifications SET read_at=? WHERE id=? AND device_id=?",
                                 (self.clock(), notification_id, device_id)).rowcount
        if not changed:
            raise ValueError("Notification not found")

    def profiles(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM project_profiles ORDER BY id").fetchall()
        return [self._open(r["payload"]) for r in rows]

    def profile(self, profile_id):
        if not isinstance(profile_id, str) or len(profile_id) != 32:
            raise ValueError("Invalid project command ID")
        with self.connect() as db:
            row = db.execute("SELECT payload FROM project_profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            raise ValueError("Project command not found")
        return self._open(row["payload"])

    def save_profile(self, record, expected_revision=0):
        """Local PC editor only. There is intentionally no remote profile-write route."""
        from core.remote_projects import validate_profile
        row = validate_profile(record)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT revision FROM project_profiles WHERE id=?", (row["id"],)).fetchone()
            revision = old["revision"] if old else 0
            if revision != expected_revision:
                raise ValueError("Project command changed elsewhere; refresh before saving")
            row["revision"] = revision + 1
            db.execute("INSERT OR REPLACE INTO project_profiles VALUES (?,?,?)", (row["id"], row["revision"], self._seal(row)))
        return row

    def delete_profile(self, profile_id, expected_revision):
        with self.connect() as db:
            changed = db.execute("DELETE FROM project_profiles WHERE id=? AND revision=?", (profile_id, expected_revision)).rowcount
        if not changed:
            raise ValueError("Project command changed or was removed; refresh first")

    def receipts(self, device_id, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM commands WHERE device_id=? ORDER BY created DESC LIMIT ?", (device_id, min(limit, 100))).fetchall()
        return [{**dict(r), "payload": self._open(r["payload"]), "result": self._open(r["result"])} for r in rows]

    def recover(self):
        # Never repeat a possibly executed action after a PC/app crash.
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM commands WHERE status IN ('running','queued')")]
        for command_id in ids:
            self.update(command_id, "failed", {"message": "PC service restarted; execution outcome is unknown. Inspect before resending."})


_store = None
_store_lock = threading.Lock()


def remote_store():
    global _store
    with _store_lock:
        if _store is None:
            _store = RemoteStore(Path(__file__).resolve().parents[1] / "memory" / "remote.db")
        return _store

"""Project records, separate from personal memory; commands are data, never auto-run."""
import json
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone
import uuid

class ProjectMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(__file__).resolve().parents[1] / "memory" / "projects.json"
        self.lock = RLock()

    def list(self, query=""):
        with self.lock:
            rows = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        return [r for r in rows if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]

    def save(self, record):
        if not isinstance(record, dict) or not str(record.get("name", "")).strip():
            raise ValueError("Project name is required")
        path = Path(record.get("path", "")).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Project path must be an existing directory")
        with self.lock:
            rows = self.list()
            previous = next((r for r in rows if r["path"] == str(path)), {})
            row = {**previous, **record, "id": previous.get("id", uuid.uuid4().hex),
                   "path": str(path), "updated_at": datetime.now(timezone.utc).isoformat()}
            rows = [r for r in rows if r["id"] != row["id"]] + [row]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.path)
        return row

projects = ProjectMemory()

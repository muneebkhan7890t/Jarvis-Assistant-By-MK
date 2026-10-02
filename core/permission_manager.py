"""Policy enforced outside model arguments. Local Python plugins remain trusted code."""
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import json
from pathlib import Path
from threading import RLock
import time
from core import confirm
from core.diagnostics import record

class Risk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

STATES = ("Allow", "Ask", "Deny", "Allow While Active", "Always Ask")
DEFAULTS = {"microphone": "Allow", "camera": "Ask", "screen": "Allow While Active",
    "cloud_vision": "Ask", "browser": "Ask", "open_app": "Allow", "messages": "Always Ask",
    "file_read": "Allow", "file_write": "Ask", "file_delete": "Always Ask",
    "install": "Always Ask", "terminal": "Always Ask", "power": "Always Ask",
    "location": "Ask", "memory": "Allow", "desktop": "Ask", "settings": "Allow",
    "monitoring": "Ask", "plugins": "Always Ask", "productivity": "Allow",
    "network": "Allow", "system": "Allow", "credentials": "Always Ask"}

@dataclass(frozen=True)
class Policy:
    name: str
    category: str
    risk: Risk
    permissions: tuple
    confirmation_required: bool = False
    voice_authentication_enough: bool = False
    user_interaction_mandatory: bool = False

_SAFE_SETTINGS = {"volume_up", "volume_down", "volume_set", "mute", "unmute", "toggle_mute",
    "brightness_up", "brightness_down", "lock_screen", "sleep_display", "pause_video",
    "minimize", "maximize", "snap_left", "snap_right", "show_desktop", "full_screen"}
_READ_FILES = {"list", "read", "find", "search", "info", "largest", "disk_usage", "list_files", "read_file", "find_files", "get_file_info", "get_largest_files", "get_disk_usage"}

def policy_for(name, parameters=None):
    p = parameters or {}
    action = str(p.get("action", "")).lower().strip()
    category, risk, required = "plugins", Risk.CRITICAL, True
    if name == 'market_analysis':
        category, risk, required = 'network', Risk.LOW, False
    elif name in ("system_status", "close_camera", "computer_context"):
        category, risk, required = "system", Risk.LOW, False
    elif name in ("save_memory", "recall_memory", "memory_control", "project_memory"):
        category, risk, required = "memory", Risk.MEDIUM, False
    elif name in ("notes", "task_manager", "reminder"):
        category, risk, required = "productivity", Risk.MEDIUM, False
    elif name == "project_jobs" and action != "retry":
        category, risk, required = "productivity", Risk.LOW, False
    elif name in ("web_search", "weather_report", "weather", "flight_finder"):
        category, risk, required = "network", Risk.MEDIUM, False
    elif name == "open_app":
        category, risk, required = "open_app", Risk.LOW, False
        app = str(p.get("app_name", "")).lower().strip()
        if app not in {"chrome", "firefox", "whatsapp", "vscode", "vs code", "calculator", "notepad", "spotify", "telegram"}:
            category, risk, required = "open_app", Risk.HIGH, True
        if any(x in app for x in ("powershell", "terminal", "cmd", "bash", "regedit", "python")) or any(x in app for x in ("/", "\\", ":", ";", "&", "|")):
            category, risk, required = "terminal", Risk.CRITICAL, True
    elif name == "computer_settings":
        if action in _SAFE_SETTINGS:
            category, risk, required = "settings", Risk.LOW, False
        elif action == "screenshot":
            category, risk, required = "screen", Risk.MEDIUM, False
        elif action in ("restart", "shutdown", "toggle_wifi"):
            category, risk, required = "power", Risk.CRITICAL, True
        else:
            category, risk, required = "desktop", Risk.HIGH, True
    elif name == "file_controller":
        if action in _READ_FILES:
            category, risk, required = "file_read", Risk.MEDIUM, False
        elif "delete" in action:
            category, risk, required = "file_delete", Risk.HIGH, True
        else:
            category, risk, required = "file_write", Risk.MEDIUM, False
    elif name == "file_processor":
        category, risk, required = "file_write", Risk.HIGH, True
    elif name == "screen_process":
        category, risk, required = ("camera" if p.get("angle") == "camera" else "screen"), Risk.MEDIUM, False
    elif name == "send_message":
        category, risk, required = "messages", Risk.HIGH, True
    elif name in ("dev_agent", "code_helper") or (name == "project_jobs" and action == "retry"):
        category, risk, required = "terminal", Risk.CRITICAL, True
    elif name == "remote_project_task":
        category, risk, required = "terminal", Risk.HIGH, True
    elif name == "workspace_restore":
        permissions = ['memory']
        categories = {'folder': 'file_read', 'app': 'open_app', 'url': 'browser'}
        for item in p.get('items', []):
            category = categories.get(item.get('kind'))
            if category and category not in permissions:
                permissions.append(category)
        return Policy(name, 'memory', Risk.MEDIUM, tuple(permissions), True, False, True)
    elif name == "game_updater":
        category, risk, required = "install", Risk.CRITICAL, True
    elif name in ("browser_control", "youtube_video"):
        category, risk, required = "browser", Risk.HIGH, True
    elif name in ("desktop_control", "computer_control", "undo"):
        category, risk, required = "desktop", Risk.HIGH, True
    elif name in ("workflow_manager", "automation_manager"):
        category, risk, required = "monitoring", Risk.MEDIUM, action not in ("list", "status", "pause", "stop")
    elif name == "manage_monitor":
        category, risk, required = "monitoring", Risk.MEDIUM, False
    elif name == "shutdown_jarvis":
        category, risk, required = "power", Risk.HIGH, True
    if name in ("file_controller", "file_processor", "code_helper"):
        paths = " ".join(str(p.get(k, "")) for k in ("path", "name", "file_path", "output_path", "destination")).lower()
        if any(marker in paths for marker in ("api_keys", ".env", "credentials", "password", "token", ".key", "permissions.json", "win32", "system32", "windows", "registry")):
            category, risk, required = "credentials", Risk.CRITICAL, True
        if name == "file_controller" and action in ("write", "write_file") and not p.get("append", False):
            risk, required = Risk.HIGH, True
    permissions = (category, "cloud_vision") if name == "screen_process" else (category,)
    return Policy(name, category, risk, permissions, required, risk == Risk.LOW, required)

# This capability is never populated from tool parameters or exposed as a tool.
_approved = ContextVar("jarvis_approved_action", default=None)

def fingerprint(name, parameters):
    return hashlib.sha256(json.dumps([name, parameters], sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()

class PermissionManager:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "permissions.json"
        self._lock = RLock()

    def settings(self):
        with self._lock:
            if not self.path.exists():
                return dict(DEFAULTS)
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or any(k not in DEFAULTS or v not in STATES for k, v in data.items()):
                    raise ValueError("Invalid permission configuration")
                return {**DEFAULTS, **data}
            except (ValueError, OSError):
                return dict.fromkeys(DEFAULTS, "Deny")

    def set(self, permission, state):
        if permission not in DEFAULTS or state not in STATES:
            raise ValueError("Unknown permission or state")
        with self._lock:
            data = self.settings()
            data[permission] = state
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def invoke_local_grant(self, name, parameters, handler, validate_grant, source="local"):
        """Internal PC-reviewed grant; never accepts approval from JSON/model input."""
        if name not in ('remote_project_task', 'workspace_restore') or not callable(validate_grant) or not validate_grant():
            raise PermissionError("No matching local approval")
        args = deepcopy(parameters)
        if self.decision(name, args)[1] == "deny":
            raise PermissionError("PC permissions deny this reviewed action")
        token = _approved.set(fingerprint(name, args))
        value = []
        def execute(approved):
            value.append(handler(approved))
            return "Reviewed action returned; inspect its recorded result."
        try:
            result = self.invoke(name, args, execute, source=source)
            if not value:
                raise PermissionError(str(result))
            return value[0]
        finally:
            _approved.reset(token)

    def decision(self, name, parameters, active=True):
        policy = policy_for(name, parameters)
        from memory.config_manager import load_api_keys
        if not load_api_keys().get("skills_enabled", {}).get(name, True):
            return policy, "deny"
        states = [self.settings()[p] for p in policy.permissions]
        if "Deny" in states or (not active and "Allow While Active" in states):
            return policy, "deny"
        if policy.confirmation_required or any(s in ("Ask", "Always Ask") for s in states):
            return policy, "ask"
        return policy, "allow"

    def invoke(self, name, parameters, handler, source="local", active=True, require_allowed=False):
        args = deepcopy(parameters)
        # Approval-shaped input has no authority and is never forwarded.
        for key in ("confirmed", "approved", "approval_token"):
            args.pop(key, None)
        digest = fingerprint(name, args)
        policy, decision = self.decision(name, args, active)
        if decision == "deny" or (require_allowed and decision != "allow"):
            record("tool_denied", name, source, policy.risk.value, status="denied")
            return f"Permission denied for {name}: {', '.join(policy.permissions)}."
        def execute():
            # Recheck policy if it changed while the banner was displayed.
            if self.decision(name, args, active)[1] == "deny":
                return f"Permission denied for {name}."
            token = _approved.set(digest)
            legacy = confirm._trusted_action.set(args.get("action") if name == "computer_settings" else None)
            started = time.perf_counter()
            record("tool_started", name, source, policy.risk.value)
            try:
                result = handler(deepcopy(args))
                text = str(result or "Action returned no result; completion is unverified.")
                failed = any(w in text.lower() for w in ("failed", "error", "cannot", "could not"))
                record("tool_failed" if failed else "tool_finished", name, source, policy.risk.value,
                       (time.perf_counter()-started)*1000, "failed" if failed else "returned")
                if not failed and name not in ("workflow_manager", "automation_manager"):
                    from core.workflows import workflows
                    workflows.observe(name, args)
                return text
            except Exception:
                record("tool_failed", name, source, policy.risk.value,
                       (time.perf_counter()-started)*1000, "exception")
                raise
            finally:
                confirm._trusted_action.reset(legacy)
                _approved.reset(token)
        if _approved.get() == digest or decision == "allow":
            return execute()
        detail = json.dumps(args, ensure_ascii=False, indent=2)
        # Full message draft is visible only in the trusted banner, never audit logs.
        if len(detail) > 12000:
            return "Request too large to review safely; split it into smaller actions."
        record("confirmation_requested", name, source, policy.risk.value, status="pending")
        from memory.config_manager import load_api_keys
        voice_categories = {'browser', 'open_app', 'file_read', 'screen', 'camera', 'cloud_vision',
                            'memory', 'productivity', 'monitoring', 'settings', 'network', 'system'}
        voice_eligible = (source == 'local' and policy.risk != Risk.CRITICAL
                          and set(policy.permissions) <= voice_categories
                          and load_api_keys().get('voice_confirmation_enabled', False))
        return confirm.request(digest, f"{policy.risk.value}: {name}", detail, execute, voice_eligible=voice_eligible)

manager = PermissionManager()

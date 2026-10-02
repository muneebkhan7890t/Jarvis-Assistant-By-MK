"""Conservative local commands. Ambiguous/multi-step language stays on the AI path."""
from dataclasses import dataclass
from difflib import get_close_matches
import re
import time
from core.diagnostics import record

@dataclass(frozen=True)
class Intent:
    name: str
    parameters: dict

ALIASES = {
    "volume up": "volume_up", "volume down": "volume_down", "mute": "mute",
    "brightness up": "brightness_up", "brightness down": "brightness_down",
    "lock pc": "lock_screen", "lock computer": "lock_screen",
    "pause music": "pause_video", "play music": "pause_video",
    "take screenshot": "screenshot", "show desktop": "show_desktop",
    "volume thora kam karo": "volume_down", "volume kam karo": "volume_down",
    "volume barhao": "volume_up", "awaz kam karo": "volume_down",
    "آواز کم کرو": "volume_down", "آواز بڑھاؤ": "volume_up",
}
APPS = {"chrome": "chrome", "whatsapp": "whatsapp", "vs code": "vscode",
        "vscode": "vscode", "calculator": "calculator", "notepad": "notepad",
        "firefox": "firefox", "telegram": "telegram", "spotify": "spotify"}

def route(text):
    started = time.perf_counter()
    text = re.sub(r"\s+", " ", text.strip().lower()).strip(".!?")
    text = re.sub(r"^(?:hey jarvis|jarvis)[, ]+", "", text)
    result = None
    if text in ALIASES:
        result = Intent("computer_settings", {"action": ALIASES[text]})
    elif text in ('give me a best trade setup', 'give me the best trade setup', 'best trade setup', 'analyze crypto', 'analyse crypto'):
        result = Intent('market_analysis', {'asset': 'best'})
    elif text in ('analyze bitcoin', 'analyse bitcoin', 'analyze btc', 'check bitcoin'):
        result = Intent('market_analysis', {'asset': 'BTC'})
    elif text in ('analyze ethereum', 'analyse ethereum', 'analyze eth'):
        result = Intent('market_analysis', {'asset': 'ETH'})
    elif text in ('check gold', 'analyze gold', 'analyse gold'):
        result = Intent('market_analysis', {'asset': 'gold'})
    elif text in ("list tasks", "show tasks"):
        result = Intent("task_manager", {"action": "list"})
    elif text in ("list reminders", "show reminders"):
        result = Intent("reminder", {"action": "list"})
    elif text in ("list notes", "show notes"):
        result = Intent("notes", {"action": "list"})
    elif text in ("list workflows", "list my workflows"):
        result = Intent("workflow_manager", {"action": "list"})
    elif text in ("list projects", "what were we working on"):
        result = Intent("project_memory", {"action": "search"})
    elif text in ("show battery", "battery status", "what is my cpu usage", "what is my ram usage", "system status"):
        result = Intent("system_status", {})
    else:
        match = re.fullmatch(r"(?:open|launch) ([a-z ]+)", text) or re.fullmatch(r"([a-z ]+) open karo", text)
        if match and match[1] in APPS:
            result = Intent("open_app", {"app_name": APPS[match[1]]})
        elif len(text.split()) <= 3:
            # Only unique near matches to low-impact adjustments; never fuzzy destructive actions.
            candidates = get_close_matches(text, [k for k in ALIASES if k.startswith(("volume", "brightness"))], n=2, cutoff=.92)
            if len(candidates) == 1:
                result = Intent("computer_settings", {"action": ALIASES[candidates[0]]})
    record("routing", result.name if result else "ai", duration_ms=(time.perf_counter()-started)*1000)
    return result

"""Compatible structured memory management through existing storage."""
from memory import memory_manager as memory
import json

def run(parameters, **kwargs):
    action = parameters.get("action", "search")
    category, key = parameters.get("category", "notes"), parameters.get("key", "")
    if action == "search":
        return memory.search_memory(parameters.get("query", ""))
    if action == "list":
        return json.dumps([r for r in memory.all_entries_for_ui() if not parameters.get("category") or r["category"] == category], ensure_ascii=False)
    if action == "edit":
        if not key or not parameters.get("value"):
            return "A key and value are required."
        return memory.remember(key, parameters["value"], category)
    if action == "delete":
        return memory.forget(key, category)
    if action in ("pin", "unpin"):
        return memory.pin_memory(category, key, action == "pin")
    return "Unknown memory action."

TOOL = {"name": "memory_control", "description": "Search, list, edit, delete, pin or unpin categorized memories.",
    "parameters": {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in ("action", "category", "key", "value", "query")}, "required": ["action"]}, "handler": run}

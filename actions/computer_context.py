import json
from core.context_engine import context

def run(parameters, **kwargs):
    return json.dumps(context.snapshot(), ensure_ascii=False)

TOOL = {"name": "computer_context", "description": "Read current application, resource usage, battery and local network state. Temporary context only.", "parameters": {"type": "OBJECT", "properties": {}}, "handler": run}

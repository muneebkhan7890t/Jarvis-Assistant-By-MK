import json
from core.project_memory import projects

def run(parameters, **kwargs):
    if parameters.get("action", "search") == "save":
        data = json.loads(parameters.get("record", "{}"))
        return json.dumps(projects.save(data), ensure_ascii=False)
    return json.dumps(projects.list(parameters.get("query", "")), ensure_ascii=False)

TOOL = {"name": "project_memory", "description": "Save or search project context separately from personal facts. Save accepts a JSON record with name and existing path, plus stack, notes, issues, tasks and commands. Commands are never executed.", "parameters": {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in ("action", "record", "query")}}, "handler": run}

import json
from core.workflows import workflows

def run(parameters, **kwargs):
    action = parameters.get("action", "list")
    if action == "list":
        return json.dumps(workflows.list())
    if action == "save":
        return json.dumps(workflows.save(json.loads(parameters.get("definition", "{}"))))
    if action == "record":
        workflows.record(parameters.get("name", ""))
        return "Recording approved low-risk JARVIS actions. Manual mouse/keyboard activity is not recorded."
    if action == "finish_recording":
        return json.dumps(workflows.finish_recording())
    if action == "run":
        return workflows.run(parameters.get("id", ""))
    if action == "delete":
        workflows.delete(parameters.get("id", ""))
        return "Workflow deleted."
    if action in ("pause", "resume", "stop"):
        return workflows.control(action)
    return json.dumps({"state": workflows.state, "step": workflows.index, "error": workflows.error})

TOOL = {"name": "workflow_manager", "description": "List/save/run/delete semantic workflows; record/finish_recording captures safe JARVIS commands; pause/resume/stop/status controls execution. Save definition is JSON with name and steps [{name,parameters}].", "parameters": {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in ("action", "name", "definition", "id")}, "required": ["action"]}, "handler": run}

import json
from core.automation import automations

def run(parameters, **kwargs):
    if not isinstance(parameters, dict):
        return 'Automation parameters must be an object.'
    action = parameters.get("action", "list")
    try:
        ident, revision = parameters.get('id', ''), parameters.get('revision')
        if action == 'save':
            return json.dumps(automations.save(json.loads(parameters.get('definition', '{}'))))
        if action == 'delete':
            automations.delete(ident, revision)
            return 'Automation deleted.'
        if action in ('enable', 'disable'):
            return json.dumps(automations.set_enabled(ident, action == 'enable', revision))
        if action == 'run_now':
            return json.dumps(automations.run_now(ident, revision))
        if action in ('list', 'status'):
            return json.dumps(automations.describe())
        return 'Unknown automation action.'
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        return f'Automation action failed: {exc}'

TOOL = {'name': 'automation_manager', 'description': 'List/save/delete/enable/disable/run_now/status for local state automations. Save definition JSON: name, trigger {field,op,value}, conditions [], action {name,parameters}, duration seconds, cooldown seconds, enabled; retain id and revision when editing. Fields: battery_percent, charging, cpu_percent, ram_percent, network_connected, process_name. Ops lt/gt/eq; boolean/process fields require eq. Only notifications and low-risk commands. Run now requires enabled, skips trigger/duration, and honors cooldown and permissions. Use real IDs from list.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['list','save','delete','enable','disable','run_now','status']},
        'definition': {'type': 'STRING'}, 'id': {'type': 'STRING'},
        'revision': {'type': 'INTEGER', 'description': 'Expected revision from list; protects against stale edits.'}
    }, 'required': ['action']}, 'handler': run}

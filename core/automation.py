"""Validated local rules, guarded execution and thread-safe runtime status."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import operator
from pathlib import Path
from threading import RLock
import time
import uuid
from core.permission_manager import policy_for, Risk

OPS = {'lt': operator.lt, 'gt': operator.gt, 'eq': operator.eq}
NUMERIC = {'battery_percent', 'cpu_percent', 'ram_percent'}
FIELDS = NUMERIC | {'charging', 'network_connected', 'process_name'}
MAX_FILE_BYTES = 1024 * 1024

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def validate(rule):
    if not isinstance(rule, dict) or not isinstance(rule.get('name'), str) or not rule['name'].strip() or len(rule['name']) > 120:
        raise ValueError('Automation name must contain 1-120 characters.')
    conditions = rule.get('conditions', [])
    if not isinstance(conditions, list) or len(conditions) > 10:
        raise ValueError('Use at most ten additional conditions.')
    for c in [rule.get('trigger')] + conditions:
        if not isinstance(c, dict) or c.get('field') not in FIELDS or c.get('op') not in OPS or 'value' not in c:
            raise ValueError('Invalid trigger/condition.')
        value, field = c['value'], c['field']
        if field in NUMERIC:
            if type(value) not in (int, float) or not 0 <= value <= 100 or not math.isfinite(value):
                raise ValueError('Percentage conditions require a number from 0 to 100.')
        elif field in ('charging', 'network_connected'):
            if type(value) is not bool or c['op'] != 'eq':
                raise ValueError('Charging/network conditions must equal true or false.')
        elif not isinstance(value, str) or not value.strip() or len(value) > 200 or c['op'] != 'eq':
            raise ValueError('Process conditions must equal a nonempty process name.')
    action = rule.get('action')
    if not isinstance(action, dict) or not isinstance(action.get('name'), str):
        raise ValueError('Action name is required.')
    parameters = action.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('Action parameters must be an object.')
    if action['name'] == 'notify':
        message = parameters.get('text', 'Automation triggered')
        if not isinstance(message, str) or not message.strip() or len(message) > 500:
            raise ValueError('Notification text must contain 1-500 characters.')
    elif policy_for(action['name'], parameters).risk != Risk.LOW:
        raise ValueError('Automations can notify or run low-risk actions only.')
    for field, default in (('duration', 0), ('cooldown', 60)):
        value = rule.get(field, default)
        if type(value) not in (int, float) or not 0 <= value <= 86400 or not math.isfinite(value):
            raise ValueError('Duration and cooldown must be 0-86400 seconds.')
    if type(rule.get('enabled', True)) is not bool:
        raise ValueError('Enabled must be true or false.')
    ident = rule.get('id')
    if ident is not None and (not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident)):
        raise ValueError('Invalid automation ID.')
    if type(rule.get('revision', 0)) is not int or rule.get('revision', 0) < 0:
        raise ValueError('Revision must be a nonnegative integer.')
    try:
        encoded = json.dumps(rule, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('Definition must contain ordinary JSON values.') from exc
    if len(encoded) > 16000:
        raise ValueError('Automation definition is too large.')
    return {**deepcopy(rule), 'name': rule['name'].strip(), 'conditions': deepcopy(conditions),
            'enabled': rule.get('enabled', True), 'duration': rule.get('duration', 0),
            'cooldown': rule.get('cooldown', 60), 'revision': rule.get('revision', 0),
            'action': {'name': action['name'], 'parameters': deepcopy(parameters)}}

class AutomationEngine:
    def __init__(self, path=None, clock=time.monotonic):
        self.path = Path(path) if path else Path(__file__).resolve().parents[1] / 'config' / 'automations.json'
        self.clock, self.dispatch = clock, None
        self.lock = RLock()
        self.runtime = {}
        self.monitoring, self.next_check, self.monitor_error = False, None, ''

    def list(self):
        with self.lock:
            if not self.path.exists():
                return []
            if self.path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('Automation file exceeds 1 MiB.')
            rows = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(rows, list) or len(rows) > 200:
                raise ValueError('Automation file must contain at most 200 rules.')
            rows = [validate(row) for row in rows]
            ids = [r.get('id') for r in rows]
            if None in ids or len(set(ids)) != len(ids):
                raise ValueError('Saved automations require unique IDs.')
            return rows

    def get(self, ident):
        matches = [r for r in self.list() if r['id'] == ident]
        if not matches:
            raise ValueError('Automation not found. Refresh the list.')
        return matches[0]

    def _state(self, ident):
        return self.runtime.setdefault(ident, {'since': None, 'fired': False, 'last_run': None,
            'last_run_at': None, 'last_checked_at': None, 'status': 'idle', 'error': '',
            'result': '', 'running': False, 'trigger_state': 'waiting', 'source': ''})

    def _editable(self, ident, expected=None):
        old = self.get(ident)
        if self._state(ident)['running']:
            raise ValueError('Automation is running. Wait for its action to finish before changing it.')
        if expected is not None and expected != old['revision']:
            raise ValueError('Automation changed elsewhere. Refresh before saving.')
        return old

    def save(self, rule):
        validated = validate(rule)
        ident = validated.get('id') or uuid.uuid4().hex
        with self.lock:
            rows = self.list()
            old = next((r for r in rows if r['id'] == ident), None)
            if validated.get('id') and old is None:
                raise ValueError('Automation was deleted. Create a new rule instead.')
            if old is not None:
                self._editable(ident, rule.get('revision'))
            elif len(rows) >= 200:
                raise ValueError('At most 200 automations can be stored.')
            validated.update(id=ident, revision=old['revision'] + 1 if old else 0)
            self._write([r for r in rows if r['id'] != ident] + [validated])
            self._state(ident).update(since=None, fired=False, trigger_state='waiting')
        return deepcopy(validated)

    def _write(self, rows):
        encoded = json.dumps(rows, indent=2, allow_nan=False)
        if len(encoded.encode('utf-8')) > MAX_FILE_BYTES:
            raise ValueError('Automation file would exceed 1 MiB; remove unused rules first.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(encoded, encoding='utf-8')
        tmp.replace(self.path)

    def delete(self, ident, expected_revision=None):
        with self.lock:
            self._editable(ident, expected_revision)
            self._write([r for r in self.list() if r['id'] != ident])
            self.runtime.pop(ident, None)

    def set_enabled(self, ident, enabled, expected_revision=None):
        if type(enabled) is not bool:
            raise ValueError('Enabled must be true or false.')
        with self.lock:
            rule = self._editable(ident, expected_revision)
            return self.save({**rule, 'enabled': enabled})

    def set_monitoring(self, enabled, interval=5, error=''):
        with self.lock:
            if not enabled:
                for state in self.runtime.values():
                    state.update(since=None, fired=False)
            self.monitoring = bool(enabled)
            self.next_check = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat() if enabled else None
            self.monitor_error = str(error)[:500]

    def describe(self):
        with self.lock:
            rows = self.list()
            states = {r['id']: deepcopy(self._state(r['id'])) for r in rows}
            for row in rows:
                states[row['id']]['next_check'] = self.next_check if row['enabled'] else None
            return {'rules': rows, 'status': states, 'monitoring': self.monitoring, 'monitor_error': self.monitor_error}

    def _claim(self, rule, source):
        state, now = self._state(rule['id']), self.clock()
        if state['running']:
            raise ValueError('Automation is already running.')
        if not rule['enabled']:
            raise ValueError('Enable this automation before running it.')
        if state['last_run'] is not None and now - state['last_run'] < rule['cooldown']:
            raise ValueError('Automation is cooling down; try again later.')
        if self.dispatch is None:
            raise RuntimeError('Automation action registry unavailable. Start the assistant first.')
        validate(rule)
        state.update(running=True, fired=True, last_run=now, last_run_at=timestamp(),
                     status='running', error='', result='', source=source)

    def _execute(self, rule, dispatch_override=None):
        from core.diagnostics import record
        ident, action, started = rule['id'], rule['action'], self.clock()
        with self.lock:
            source = self._state(ident)['source']
        record('automation_triggered', action['name'], source='automation:' + source)
        try:
            result = str((dispatch_override or self.dispatch)(action['name'], deepcopy(action['parameters'])))
            lower = result.casefold().strip()
            failed = (lower.startswith(('permission denied', 'error', 'failed', 'cannot ', 'could not ', 'i cannot ', 'i could not ', 'action failed', 'unknown action', 'request too large')) or
                      lower.startswith('skill ') and 'disabled' in lower or
                      lower.startswith('action ') and 'not available' in lower or
                      lower.startswith('tool ') and 'failed' in lower)
            if failed:
                status, error = 'blocked_or_failed', result[:500]
            elif lower.startswith(('[confirmation_pending]', 'waiting for confirmation', 'confirmation required', 'please confirm')):
                status, error = 'confirmation_requested', ''
            else:
                status, error = 'returned', ''
        except Exception as exc:
            result, status, error = '', 'error', str(exc)[:500]
        with self.lock:
            self._state(ident).update(running=False, status=status, error=error, result=result[:500])
        record('automation_finished', action['name'], source='automation:' + source,
               duration_ms=(self.clock() - started) * 1000, status=status)
        return {'status': status, 'result': result[:500], 'error': error}

    def run_now(self, ident, expected_revision=None, *, dispatch_override=None, source='manual'):
        """Skip trigger/duration, but retain enabled, cooldown and permission checks."""
        with self.lock:
            rule = self.get(ident)
            if expected_revision is not None and expected_revision != rule['revision']:
                raise ValueError('Automation changed elsewhere. Refresh before running.')
            self._claim(rule, source)
        return self._execute(rule, dispatch_override)

    def tick(self, context, should_continue=None):
        for candidate in self.list():
            if should_continue is not None and not should_continue():
                self.set_monitoring(False)
                return
            with self.lock:
                current = [r for r in self.list() if r['id'] == candidate['id']]
                if not current or not current[0]['enabled']:
                    continue
                rule = current[0]
                state, now = self._state(rule['id']), self.clock()
                state['last_checked_at'] = timestamp()
                if state['running']:
                    continue
                try:
                    conditions = [rule['trigger']] + rule['conditions']
                    matches = all(context.get(c['field']) is not None and OPS[c['op']](context[c['field']], c['value']) for c in conditions)
                    if not matches:
                        state.update(since=None, fired=False, trigger_state='waiting')
                        continue
                    if state['since'] is None:
                        state['since'] = now
                    if state['fired']:
                        state['trigger_state'] = 'latched'
                        continue
                    if now - state['since'] < rule['duration']:
                        state['trigger_state'] = 'holding'
                        continue
                    if state['last_run'] is not None and now - state['last_run'] < rule['cooldown']:
                        state['trigger_state'] = 'cooldown'
                        continue
                    self._claim(rule, 'trigger')
                    state['trigger_state'] = 'latched'
                except Exception as exc:
                    state.update(status='error', error=str(exc)[:500])
                    continue
            self._execute(rule)

automations = AutomationEngine()

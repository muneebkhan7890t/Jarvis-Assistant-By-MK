"""Persistent reminder lifecycle backed by the existing OS scheduler adapters.

Each native job carries an id and generation. Superseded/cancelled jobs cannot
notify even if their OS scheduler entry cannot be removed immediately.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic, sleep
import uuid
from core import productivity_store as store

REPEATS = ('none', 'daily', 'weekly', 'weekdays')

def now_utc():
    return datetime.now(timezone.utc)


def _schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id TEXT PRIMARY KEY, message TEXT NOT NULL, due_at TEXT NOT NULL,
        recurrence TEXT NOT NULL DEFAULT 'none', state TEXT NOT NULL,
        generation INTEGER NOT NULL DEFAULT 1, native_id TEXT NOT NULL DEFAULT '',
        backend TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS reminder_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, reminder_id TEXT NOT NULL,
        event TEXT NOT NULL, at TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')""")


def _event(db, ident, event, detail=''):
    db.execute('INSERT INTO reminder_events(reminder_id,event,at,detail) VALUES(?,?,?,?)',
               (ident, event, now_utc().isoformat(), detail[:500]))


def get(ident):
    with store.database() as db:
        _schema(db)
        row = db.execute('SELECT * FROM reminders WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Reminder not found. Use list to find its ID.')
    return dict(row)


def list_reminders(status='pending'):
    valid = ('pending', 'completed', 'cancelled', 'failed', 'all')
    if status not in valid:
        raise ValueError('Status must be ' + ', '.join(valid))
    with store.database() as db:
        _schema(db)
        sql = 'SELECT * FROM reminders'
        args = ()
        if status != 'all':
            sql += ' WHERE state=?'
            args = (status,)
        rows = db.execute(sql + ' ORDER BY due_at', args).fetchall()
    return [dict(r) for r in rows]


def history(ident=''):
    with store.database() as db:
        _schema(db)
        if ident:
            rows = db.execute('SELECT * FROM reminder_events WHERE reminder_id=? ORDER BY event_id DESC LIMIT 100', (ident,)).fetchall()
        else:
            rows = db.execute('SELECT * FROM reminder_events ORDER BY event_id DESC LIMIT 100').fetchall()
    return [dict(r) for r in rows]


def validate_due(due, now=None):
    now = now or now_utc()
    if not isinstance(due, datetime):
        raise ValueError('Reminder time must be a datetime.')
    due = due.astimezone(timezone.utc)
    if due <= now:
        raise ValueError('That time has already passed.')
    return due


def _message(message):
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise ValueError('Reminder message must contain 1-2000 characters.')
    return message.strip()


def _register(row, schedule=None):
    if schedule is None:
        from actions.reminder import register_persistent
        schedule = register_persistent
    return schedule(row)


def _remove_native(row, cancel=None):
    if not row.get('native_id'):
        return ''
    if cancel is None:
        from actions.reminder import cancel_native
        cancel = cancel_native
    try:
        return cancel(row) or ''
    except Exception as exc:
        return f'Native cleanup failed ({type(exc).__name__}); the old generation is disabled.'


def add(message, due, recurrence='none', schedule=None):
    message, due = _message(message), validate_due(due)
    if recurrence not in REPEATS:
        raise ValueError('Unknown repeat schedule.')
    ident, now = uuid.uuid4().hex, now_utc().isoformat()
    with store.database() as db:
        _schema(db)
        db.execute('INSERT INTO reminders(id,message,due_at,recurrence,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                   (ident, message, due.isoformat(), recurrence, 'scheduling', now, now))
        _event(db, ident, 'created')
    return _activate(ident, schedule)


def _activate(ident, schedule=None):
    row = get(ident)
    try:
        native_id, backend = _register(row, schedule)
        if not native_id:
            raise RuntimeError('The operating-system scheduler did not register the reminder.')
    except Exception as exc:
        with store.database() as db:
            db.execute("UPDATE reminders SET state='failed',error=?,updated_at=? WHERE id=? AND generation=?",
                       (str(exc)[:500], now_utc().isoformat(), ident, row['generation']))
            _event(db, ident, 'schedule_failed', str(exc))
        raise RuntimeError('Reminder scheduling failed: ' + str(exc)) from exc
    with store.database() as db:
        cursor = db.execute("UPDATE reminders SET state='pending',native_id=?,backend=?,error='',updated_at=? WHERE id=? AND generation=? AND state='scheduling'",
                            (native_id, backend, now_utc().isoformat(), ident, row['generation']))
        if cursor.rowcount:
            _event(db, ident, 'scheduled')
    if not cursor.rowcount:
        _remove_native({**row, 'native_id': native_id, 'backend': backend})
        raise RuntimeError('Reminder changed while it was being registered; no active reminder was added.')
    return get(ident)


def change(ident, action, *, due=None, message=None, recurrence=None, minutes=20, schedule=None, cancel=None, expected_generation=None):
    if action not in ('edit', 'snooze', 'cancel', 'complete'):
        raise ValueError('Unknown reminder action.')
    if action == 'snooze':
        if type(minutes) is not int or not 1 <= minutes <= 10080:
            raise ValueError('Snooze must be 1-10080 minutes.')
        due = now_utc() + timedelta(minutes=minutes)
    if due is not None:
        due = validate_due(due)
    if message is not None:
        message = _message(message)
    if recurrence is not None and recurrence not in REPEATS:
        raise ValueError('Unknown repeat schedule.')
    with store.database() as db:
        _schema(db)
        current = db.execute('SELECT * FROM reminders WHERE id=?', (ident,)).fetchone()
        if current is None:
            raise ValueError('Reminder not found.')
        old = dict(current)
        if old['state'] in ('scheduling', 'firing'):
            raise ValueError('Reminder is currently being scheduled or delivered. Try again when it finishes.')
        if expected_generation is not None and expected_generation != old['generation']:
            raise ValueError('Reminder changed elsewhere. Refresh before saving.')
        state = {'cancel': 'cancelled', 'complete': 'completed'}.get(action, 'scheduling')
        next_due = due.isoformat() if due is not None else old['due_at']
        if state == 'scheduling':
            validate_due(datetime.fromisoformat(next_due))
        db.execute("UPDATE reminders SET message=?,due_at=?,recurrence=?,state=?,generation=generation+1,native_id='',backend='',updated_at=?,error='' WHERE id=?",
                   (message if message is not None else old['message'], next_due,
                    recurrence if recurrence is not None else old['recurrence'], state, now_utc().isoformat(), ident))
        _event(db, ident, action)
    if state == 'scheduling':
        try:
            result = _activate(ident, schedule)
        except Exception:
            # Restore an old pending future schedule, instead of losing it on failure.
            if old['state'] == 'pending' and datetime.fromisoformat(old['due_at']) > now_utc():
                with store.database() as db:
                    columns = [k for k in old if k != 'id']
                    restored = db.execute('UPDATE reminders SET '+','.join(k+'=?' for k in columns)+" WHERE id=? AND state='failed' AND generation=?",
                                          [*(old[k] for k in columns), ident, old['generation']+1])
                    if restored.rowcount:
                        _event(db, ident, 'previous_schedule_restored')
            raise
    else:
        result = get(ident)
    warning = _remove_native(old, cancel)
    if warning:
        with store.database() as db:
            _event(db, ident, 'cleanup_warning', warning)
        result['cleanup_warning'] = warning
    return result


def next_occurrence(due, recurrence, now=None):
    """Advance local wall time; do not replay every missed occurrence after sleep."""
    if recurrence == 'none':
        return None
    now = (now or now_utc()).astimezone()
    local = due.astimezone().replace(tzinfo=None)
    increment = timedelta(days=7 if recurrence == 'weekly' else 1)
    while True:
        local += increment
        candidate = local.astimezone(timezone.utc)
        if recurrence == 'weekdays' and local.weekday() >= 5:
            continue
        if candidate > now:
            return candidate


def fire(ident, generation, notify=None, schedule=None):
    """Atomic one-shot claim. Called by the existing platform's native job."""
    with store.database() as db:
        _schema(db)
        row = db.execute('SELECT * FROM reminders WHERE id=?', (ident,)).fetchone()
        if row is None or row['generation'] != generation or row['state'] != 'pending':
            return False
        row = dict(row)
        if datetime.fromisoformat(row['due_at']) > now_utc() + timedelta(seconds=2):
            return False
        db.execute("UPDATE reminders SET state='firing',updated_at=? WHERE id=? AND generation=?", (now_utc().isoformat(), ident, generation))
        _event(db, ident, 'delivery_started')
    try:
        if notify is None:
            from actions.reminder import notify_local
            notify = notify_local
        if notify(row['message']) is False:
            raise RuntimeError('The operating system did not accept a notification.')
    except Exception as exc:
        with store.database() as db:
            db.execute("UPDATE reminders SET state='failed',error=?,updated_at=? WHERE id=? AND generation=?",
                       (str(exc)[:500], now_utc().isoformat(), ident, generation))
            _event(db, ident, 'delivery_failed', str(exc))
        return False
    due = next_occurrence(datetime.fromisoformat(row['due_at']), row['recurrence'])
    with store.database() as db:
        _event(db, ident, 'delivered')
        db.execute("UPDATE reminders SET state='completed',updated_at=? WHERE id=? AND generation=?", (now_utc().isoformat(), ident, generation))
        if due:
            db.execute("UPDATE reminders SET state='scheduling',due_at=?,generation=generation+1,native_id='',backend='' WHERE id=? AND generation=?",
                       (due.isoformat(), ident, generation))
    if due:
        try:
            _activate(ident, schedule)
        except RuntimeError:
            # _activate has durably recorded the failure; do not claim the next run exists.
            return False
    return True


def run_scheduled(ident, generation):
    """Bridge minute-resolution timers and the short registration/activation race.

    A job invoked much too early (e.g. a launchd calendar date in an earlier year)
    remains on disk for its actual date. Always recheck state after waiting.
    """
    deadline = monotonic() + 90
    while monotonic() < deadline:
        row = get(ident)
        if row['generation'] != generation or row['state'] not in ('pending', 'scheduling'):
            return False
        delay = (datetime.fromisoformat(row['due_at']) - now_utc()).total_seconds()
        if delay > 65:
            return False
        if row['state'] == 'pending' and delay <= 0:
            return fire(ident, generation)
        sleep(min(1, max(0.1, delay)) if row['state'] == 'pending' else 0.25)
    return False


def recover_interrupted():
    """Do not replay a possibly delivered notification after an interrupted process."""
    with store.database() as db:
        _schema(db)
        rows = db.execute("SELECT id FROM reminders WHERE state IN ('scheduling','firing') AND updated_at<?", ((now_utc()-timedelta(minutes=5)).isoformat(),)).fetchall()
        for row in rows:
            db.execute("UPDATE reminders SET state='failed', error=?, updated_at=? WHERE id=?",
                       ('Interrupted while scheduling or delivering; inspect history and snooze to retry.', now_utc().isoformat(), row['id']))
            _event(db, row['id'], 'interrupted')
    return len(rows)

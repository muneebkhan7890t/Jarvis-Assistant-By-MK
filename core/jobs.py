"""Durable project jobs independent of the live conversation session."""
import json
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
import uuid
from memory.config_manager import get_base_dir

DB_PATH = get_base_dir() / 'memory' / 'jobs.db'
_start_lock = threading.Lock()


class JobCancelled(Exception):
    pass


class JobNeedsReview(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, request TEXT NOT NULL, options TEXT NOT NULL,
        folder TEXT NOT NULL, state TEXT NOT NULL, progress TEXT NOT NULL,
        result TEXT NOT NULL DEFAULT '', cancel_requested INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL, updated TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0)''')
    db.commit()
    return db


def _query(sql, args=(), one=False):
    db = _db()
    try:
        with db:
            cursor = db.execute(sql, args)
            if cursor.description:
                rows = [dict(row) for row in cursor.fetchall()]
                return (rows[0] if rows else None) if one else rows
    finally:
        db.close()


def get(job_id):
    return _query('SELECT * FROM jobs WHERE id=?', (job_id,), one=True)


def recent(query='', limit=20):
    rows = _query('SELECT * FROM jobs ORDER BY created DESC')
    q = query.casefold()
    return [r for r in rows if q in (r['request']+' '+r['id']+' '+r['folder']).casefold()][:limit]


def update(job_id, **fields):
    allowed = {'state', 'progress', 'result', 'cancel_requested', 'notified'}
    if not fields or not set(fields).issubset(allowed):
        raise ValueError('Invalid job update')
    fields['updated'] = _now()
    _query('UPDATE jobs SET '+','.join(f'{key}=?' for key in fields)+' WHERE id=?',
           (*fields.values(), job_id))


def recover_interrupted():
    """Only at application startup, before any workers start. Never fake a resume."""
    _query("UPDATE jobs SET state='interrupted', progress=?, updated=?, notified=0 "
           "WHERE state IN ('queued','running')",
           ('Assistant stopped before this job finished. Files retained; retry explicitly.', _now()))


def checkpoint(job_id, message):
    row = get(job_id)
    if row['cancel_requested']:
        raise JobCancelled('Cancelled at the next build checkpoint. Existing files were kept.')
    update(job_id, progress=str(message)[:2000])


def start(request, options, projects_dir, worker):
    """Reserve folder and record before starting. One active build prevents collisions."""
    with _start_lock:
        active = _query("SELECT * FROM jobs WHERE state IN ('queued','running') ORDER BY created DESC LIMIT 1", one=True)
        if active:
            return active, False
        job_id = uuid.uuid4().hex[:12]
        import re
        name = re.sub(r'[^\w-]', '_', options.get('project_name', '')).strip('_')[:60] or 'project'
        folder = (Path(projects_dir) / f'{name}_{job_id}').resolve()
        folder.mkdir(parents=True, exist_ok=False)
        now = _now()
        _query('INSERT INTO jobs(id,request,options,folder,state,progress,created,updated) VALUES(?,?,?,?,?,?,?,?)',
               (job_id, request, json.dumps(options), str(folder), 'queued', 'Waiting for build worker', now, now))

        def run():
            try:
                update(job_id, state='running')
                checkpoint(job_id, 'Planning project structure')
                result = worker(folder, lambda msg: checkpoint(job_id, msg))
                checkpoint(job_id, 'Build steps finished')
                update(job_id, state='completed', result=str(result), progress='Build finished; see verification result')
            except JobCancelled as exc:
                update(job_id, state='cancelled', progress=str(exc), result=str(exc))
            except JobNeedsReview as exc:
                update(job_id, state='needs_review', progress='Files saved; verification needs attention', result=str(exc))
            except Exception as exc:
                update(job_id, state='failed', progress='Build failed; partial files retained', result=f'{type(exc).__name__}: {exc}')

        try:
            threading.Thread(target=run, daemon=True, name=f'project-{job_id}').start()
        except Exception as exc:
            update(job_id, state='failed', result=str(exc), progress='Could not start worker')
        return get(job_id), True


def cancel(job_id):
    row = get(job_id)
    if not row:
        return 'Job not found.'
    if row['state'] not in ('queued', 'running'):
        return f"Job is already {row['state']}."
    update(job_id, cancel_requested=1)
    return 'Cancellation requested. Current API call or subprocess must finish before the next checkpoint; files will be kept.'


def describe(row):
    return (f"Job {row['id']} | {row['state']}\nRequest: {row['request']}\n"
            f"Folder: {row['folder']}\nProgress: {row['progress']}\n"
            f"Updated: {row['updated']}\nResult: {row['result'][:4000]}")


def context():
    rows = recent(limit=8)
    return ('[SAVED PROJECT JOBS — snapshots; call project_jobs for current status]\n'
            + '\n'.join(f"{r['id']} | {r['state']} | {r['request'][:160]} | {r['folder']}" for r in rows)) if rows else ''


def pending_notifications():
    return _query("SELECT * FROM jobs WHERE notified=0 AND state NOT IN ('queued','running') ORDER BY created LIMIT 10")

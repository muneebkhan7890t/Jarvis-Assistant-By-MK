"""Local, encrypted work checkpoints. Saving never opens or executes anything."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

from core.remote_store import remote_store
from core.permission_manager import manager

APPS = ('vscode', 'chrome', 'firefox', 'notepad', 'calculator', 'spotify')


def validate(value, check_folder=True):
    if not isinstance(value, dict):
        raise ValueError('Workspace must be an object')
    result = {}
    for field, limit in (('name', 100), ('folder', 1000), ('notes', 10000), ('next_steps', 5000)):
        text = value.get(field, '')
        if not isinstance(text, str) or len(text) > limit or '\x00' in text:
            raise ValueError(f'Invalid {field}; maximum {limit} characters')
        result[field] = text.strip()
    if not result['name']:
        raise ValueError('Give this workspace a name')
    if result['folder']:
        folder = Path(result['folder']).expanduser()
        if not folder.is_absolute() or str(folder).startswith(('\\\\', '//')):
            raise ValueError('Choose an absolute local project folder')
        if check_folder:
            folder = folder.resolve(strict=True)
            if not folder.is_dir() or folder == Path(folder.anchor) or str(folder).startswith(('\\\\', '//')):
                raise ValueError('Choose an existing local project folder, not a drive root')
            result['folder'] = str(folder)
    apps, urls = value.get('apps', []), value.get('urls', [])
    if not isinstance(apps, list) or len(apps) > len(APPS) or any(a not in APPS for a in apps):
        raise ValueError('Choose apps from the supported list')
    if not isinstance(urls, list) or len(urls) > 8:
        raise ValueError('Save at most eight HTTPS pages')
    clean_urls = []
    for url in urls:
        if not isinstance(url, str) or len(url) > 500 or any(ord(c) < 33 for c in url):
            raise ValueError('Each HTTPS address must be at most 500 characters, without spaces')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or '\\' in url:
            raise ValueError('Only HTTPS pages without embedded login credentials are supported')
        # Accessing port validates its syntax/range too.
        parsed.port
        clean_urls.append(url)
    result['apps'] = list(dict.fromkeys(apps))
    result['urls'] = list(dict.fromkeys(clean_urls))
    ident = value.get('id') or uuid.uuid4().hex
    if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
        raise ValueError('Invalid workspace ID')
    result['id'] = ident
    return result


def open_item(item):
    """Fixed apps, folders, and HTTPS pages only; never a saved shell command."""
    kind, value = item['kind'], item['value']
    if kind == 'app':
        from actions.open_app import open_app
        return open_app({'app_name': value})
    if kind == 'folder':
        if os.name == 'nt':
            os.startfile(value)
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', value],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'Folder-open request sent; the window has not been independently verified.'
    if kind == 'url':
        import webbrowser
        if not webbrowser.open(value, new=2):
            raise RuntimeError('Browser did not accept the page-open request')
        return 'Page-open request sent; the loaded page has not been independently verified.'
    raise ValueError('Unsupported workspace item')


class WorkspaceStore:
    def __init__(self, store=None, permissions=None, clock=time.time):
        self.store = store or remote_store()
        self.permissions = permissions or manager
        self.clock = clock
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, updated REAL NOT NULL, payload BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_runs (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, created REAL NOT NULL,
                    status TEXT NOT NULL, payload BLOB NOT NULL);
            ''')

    def permitted(self):
        if self.permissions.settings().get('memory') == 'Deny':
            raise PermissionError('Memory is denied in PC permissions')

    def list(self):
        self.permitted()
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM workspaces ORDER BY updated DESC').fetchall()
        return [dict(self.store._open(r['payload']), revision=r['revision'], updated=r['updated']) for r in rows]

    def get(self, ident):
        self.permitted()
        if not isinstance(ident, str):
            raise ValueError('Select a saved workspace')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM workspaces WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Workspace was removed; refresh the list')
        return dict(self.store._open(row['payload']), revision=row['revision'], updated=row['updated'])

    def save(self, value, expected_revision=0):
        self.permitted()
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('Invalid revision')
        row = validate(value)
        with self.store.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT revision FROM workspaces WHERE id=?', (row['id'],)).fetchone()
            if (old[0] if old else 0) != expected_revision:
                raise ValueError('Workspace changed elsewhere; reload before saving')
            if not old and db.execute('SELECT count(*) FROM workspaces').fetchone()[0] >= 100:
                raise ValueError('Workspace limit reached; delete an unused workspace')
            db.execute('INSERT OR REPLACE INTO workspaces VALUES (?,?,?,?)',
                       (row['id'], expected_revision + 1, self.clock(), self.store._seal(row)))
        return self.get(row['id'])

    def delete(self, ident, revision):
        self.permitted()
        with self.store.connect() as db:
            changed = db.execute('DELETE FROM workspaces WHERE id=? AND revision=?', (ident, revision)).rowcount
            if not changed:
                raise ValueError('Workspace changed elsewhere; reload before deleting')
            db.execute('DELETE FROM workspace_runs WHERE workspace_id=?', (ident,))

    def preview(self, ident):
        saved = self.get(ident)
        row = validate(saved)
        items = []
        if row['folder']:
            items.append({'kind': 'folder', 'value': row['folder']})
        items.extend({'kind': 'app', 'value': app} for app in row['apps'])
        items.extend({'kind': 'url', 'value': url} for url in row['urls'])
        return {'workspace_id': ident, 'revision': saved['revision'], 'items': items}

    def latest_run(self, ident):
        self.get(ident)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM workspace_runs WHERE workspace_id=? ORDER BY created DESC LIMIT 1', (ident,)).fetchone()
        if not row:
            return None
        return dict(self.store._open(row['payload']), status=row['status'], created=row['created'])

    def restore_reviewed(self, plan, opener=open_item):
        """Local PC dialog only: caller must display this exact plan and obtain Yes.

        Intentionally not registered as an AI action or exposed through HTTP.
        """
        plan = deepcopy(plan)
        def valid():
            if self.preview(plan['workspace_id']) != plan:
                raise ValueError('Workspace changed after review; review the new checkpoint')
            return True
        valid()
        outcomes = []
        run_id = uuid.uuid4().hex
        def record(status):
            with self.store.connect() as db:
                # A concurrent explicit delete must not recreate the deleted history.
                if db.execute('SELECT 1 FROM workspaces WHERE id=?', (plan['workspace_id'],)).fetchone():
                    db.execute('INSERT OR REPLACE INTO workspace_runs VALUES (?,?,?,?,?)',
                               (run_id, plan['workspace_id'], started, status,
                                self.store._seal({'revision': plan['revision'], 'outcomes': outcomes})))
                    db.execute('DELETE FROM workspace_runs WHERE workspace_id=? AND id NOT IN '
                               '(SELECT id FROM workspace_runs WHERE workspace_id=? ORDER BY created DESC LIMIT 10)',
                               (plan['workspace_id'], plan['workspace_id']))
        def restore(_args):
            record('opening; if interrupted, outcome is unknown')
            for item in plan['items']:
                try:
                    valid()
                    if self.permissions.decision('workspace_restore', plan)[1] == 'deny':
                        raise PermissionError('PC permissions changed; reopening stopped')
                    result = str(opener(item))
                    failed = any(x in result.lower() for x in ('failed', 'could not', 'cannot', 'error'))
                    outcomes.append({**item, 'status': 'failed' if failed else 'returned / unverified', 'result': result[:1000]})
                    if failed:
                        break
                except Exception as exc:
                    outcomes.append({**item, 'status': 'failed', 'result': str(exc)[:1000]})
                    break
                finally:
                    record('opening; if interrupted, outcome is unknown')
            state = 'stopped with error' if any(o['status'] == 'failed' for o in outcomes) else 'returned / unverified'
            record(state)
            return {'status': state, 'outcomes': outcomes}
        started = self.clock()
        return self.permissions.invoke_local_grant('workspace_restore', plan, restore, valid)

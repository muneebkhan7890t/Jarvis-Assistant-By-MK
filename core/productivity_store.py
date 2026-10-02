"""Local task/note storage. SQLite transactions protect concurrent tool calls."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
import json
from memory.config_manager import get_base_dir

DB_PATH = get_base_dir() / 'memory' / 'productivity.db'


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute('''CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('task', 'note')),
                title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                due TEXT NOT NULL DEFAULT '',
                done INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL)''')
            columns = {r['name'] for r in connection.execute('PRAGMA table_info(items)')}
            additions = {
                'priority': "TEXT NOT NULL DEFAULT 'normal'",
                'project': "TEXT NOT NULL DEFAULT ''",
                'tags': "TEXT NOT NULL DEFAULT '[]'",
                'category': "TEXT NOT NULL DEFAULT ''",
                'pinned': "INTEGER NOT NULL DEFAULT 0",
                'updated': "TEXT NOT NULL DEFAULT ''",
                'version': "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(f'ALTER TABLE items ADD COLUMN {name} {declaration}')
            yield connection
    finally:
        connection.close()


def field(parameters, name, maximum, required=False):
    value = parameters.get(name, '')
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'Please provide {name}.')
    if len(value) > maximum:
        raise ValueError(f'{name} must be at most {maximum} characters.')
    return value


def operate(kind, parameters):
    if not isinstance(parameters, dict):
        return 'Please provide an object of parameters.'
    try:
        return _operate(kind, parameters)
    except ValueError as exc:
        return str(exc)
    except (sqlite3.Error, OSError):
        return 'Local storage is unavailable. Check the memory folder permissions and disk space.'


def _operate(kind, p):
    action = field(p, 'action', 30, True).lower()
    allowed = {'add', 'list', 'search', 'read', 'edit', 'archive', 'restore', 'pin', 'unpin'}
    if kind == 'task':
        allowed |= {'complete', 'reopen'}
    if action not in allowed:
        raise ValueError('Supported actions: ' + ', '.join(sorted(allowed)))
    if action == 'add':
        title = field(p, 'title', 200, True)
        body = field(p, 'body', 8000, kind == 'note')
        due = field(p, 'due', 10) if kind == 'task' else ''
        if due:
            try:
                if date.fromisoformat(due).isoformat() != due:
                    raise ValueError()
            except ValueError:
                raise ValueError('Use YYYY-MM-DD for due.') from None
        metadata = _metadata(p)
        now = datetime.now(timezone.utc).isoformat()
        with database() as db:
            cursor = db.execute(
                'INSERT INTO items(kind,title,body,due,created,updated,priority,project,tags,category) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (kind, title, body, due, now, now, metadata['priority'], metadata['project'], metadata['tags'], metadata['category']))
            row = dict(db.execute('SELECT * FROM items WHERE id=?', (cursor.lastrowid,)).fetchone())
        _register_undo(None, row)
        return f'Saved {kind} #{row["id"]}: {title}' + (
                f' (due {due}; no notification scheduled)' if due else '')

    if action in {'list', 'search'}:
        query = field(p, 'query', 200, action == 'search')
        status = field(p, 'status', 20) or ('open' if kind == 'task' else 'active')
        valid = {'open', 'completed', 'all', 'archived'} if kind == 'task' else {'active', 'all', 'archived'}
        if status not in valid:
            raise ValueError('Status must be one of: ' + ', '.join(sorted(valid)))
        offset = p.get('offset', 0)
        if type(offset) is not int or offset < 0:
            raise ValueError('offset must be a non-negative integer.')
        rows = query_items(kind, query, status, field(p, 'category', 80), field(p, 'project', 200))
        page = rows[offset:offset+20]
        if not page:
            return f'No matching {kind}s.'
        text = '\n'.join(_summary(row) for row in page)
        if offset + 20 < len(rows):
            text += f'\nMore results: repeat with offset={offset+20}.'
        return text

    item_id = p.get('id')
    if type(item_id) is not int or item_id < 1:
        raise ValueError('Provide the positive integer id returned by list or search.')
    with database() as db:
        row = db.execute('SELECT * FROM items WHERE id=? AND kind=?', (item_id, kind)).fetchone()
        if row is None:
            return f'{kind.capitalize()} #{item_id} was not found.'
        if action == 'read':
            return _summary(row) + '\n' + row['body']
        before = dict(row)
        expected = p.get('version')
        if expected is not None and (type(expected) is not int or expected != row['version']):
            raise ValueError('This item changed elsewhere. Refresh before saving.')
        changes = {}
        if action == 'edit':
            for key, maximum in (('title', 200), ('body', 8000), ('project', 200), ('category', 80)):
                if key in p:
                    changes[key] = field(p, key, maximum, key == 'title' or key == 'body' and kind == 'note')
            if 'due' in p and kind == 'task':
                changes['due'] = _due(p)
            metadata = _metadata(p)
            for key in ('priority', 'tags'):
                if key in p:
                    changes[key] = metadata[key]
            if not changes:
                raise ValueError('Provide at least one field to edit.')
        else:
            column, value = {
                'complete': ('done', 1), 'reopen': ('done', 0),
                'archive': ('archived', 1), 'restore': ('archived', 0),
                'pin': ('pinned', 1), 'unpin': ('pinned', 0),
            }[action]
            changes[column] = value
        changes['updated'] = datetime.now(timezone.utc).isoformat()
        changes['version'] = before['version'] + 1
        db.execute('UPDATE items SET ' + ', '.join(k+'=?' for k in changes) + ' WHERE id=? AND kind=?',
                   [*changes.values(), item_id, kind])
        after = dict(db.execute('SELECT * FROM items WHERE id=? AND kind=?', (item_id, kind)).fetchone())
    _register_undo(before, after)
    return f'{kind.capitalize()} #{item_id}: {action} applied.'



def _summary(row):
    status = 'archived' if row['archived'] else ('completed' if row['done'] else 'open')
    if row['kind'] == 'note' and not row['archived']:
        status = 'active'
    due = f" | due {row['due']}" if row['due'] else ''
    tags = json.loads(row['tags']) if isinstance(row['tags'], str) else row['tags']
    metadata = [f"priority {row['priority']}"] if row['kind'] == 'task' else []
    for name in ('project', 'category'):
        if row[name]:
            metadata.append(f'{name}: {row[name]}')
    if tags:
        metadata.append('tags: ' + ', '.join(tags))
    if row['pinned']:
        metadata.append('pinned')
    metadata.append(f"created {row['created'][:10]}, revision {row['version']}")
    return f"#{row['id']} [{status}] {row['title']}{due} | " + ' | '.join(metadata)


def _due(p):
    value = field(p, 'due', 10)
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('Use YYYY-MM-DD for due.') from None
    return value


def _metadata(p):
    priority = field(p, 'priority', 10) or 'normal'
    if priority not in ('low', 'normal', 'high', 'urgent'):
        raise ValueError('Priority must be low, normal, high or urgent.')
    tags = p.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]
    if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
        raise ValueError('Tags must be up to 20 labels of 1-40 characters.')
    tags = list(dict.fromkeys(t.strip() for t in tags))
    return {'priority': priority, 'project': field(p, 'project', 200),
            'category': field(p, 'category', 80), 'tags': json.dumps(tags, ensure_ascii=False)}


def query_items(kind, query='', status=None, category='', project=''):
    """Structured rows shared by desktop UI and local integrations."""
    if kind not in ('task', 'note'):
        raise ValueError('Unknown item kind.')
    status = status or ('open' if kind == 'task' else 'active')
    if status not in ('open', 'completed', 'active', 'archived', 'all'):
        raise ValueError('Invalid item status.')
    with database() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM items WHERE kind=? ORDER BY pinned DESC, id DESC', (kind,))]
    result = []
    for row in rows:
        if status != 'all' and bool(row['archived']) != (status == 'archived'):
            continue
        if status in ('open', 'completed') and bool(row['done']) != (status == 'completed'):
            continue
        if category and row['category'].casefold() != category.casefold():
            continue
        if project and row['project'].casefold() != project.casefold():
            continue
        text = '\n'.join(str(row[k]) for k in ('title', 'body', 'tags', 'project', 'category'))
        if query.casefold() not in text.casefold():
            continue
        row['tags'] = json.loads(row['tags'])
        result.append(row)
    return result


def _register_undo(before, after):
    from core.undo import push_undo
    path = Path(DB_PATH)
    def restore():
        connection = sqlite3.connect(path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                current = connection.execute('SELECT * FROM items WHERE id=? AND kind=?', (after['id'], after['kind'])).fetchone()
                if current is None or any(current[k] != after[k] for k in after if k not in ('version', 'updated')):
                    raise ValueError('Item has changed since this operation; refusing to overwrite newer edits.')
                if before is None:
                    connection.execute('DELETE FROM items WHERE id=? AND kind=?', (after['id'], after['kind']))
                else:
                    restored = {k: v for k, v in before.items() if k not in ('id', 'kind', 'version')}
                    restored.update(version=current['version'] + 1, updated=datetime.now(timezone.utc).isoformat())
                    connection.execute('UPDATE items SET ' + ', '.join(k+'=?' for k in restored) + ' WHERE id=? AND kind=?',
                                       [*restored.values(), after['id'], after['kind']])
        finally:
            connection.close()
        return 'Previous item state restored.'
    push_undo(f"{after['kind']} #{after['id']} change", restore)

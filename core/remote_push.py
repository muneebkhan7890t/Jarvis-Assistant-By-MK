"""Opt-in encrypted Web Push with durable attempts and generic lock-screen text."""
import base64
import importlib.util
import json
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def subscription(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid push subscription')
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise ValueError('Invalid push endpoint')
    url = urlsplit(endpoint)
    # Never allow a phone-supplied subscription to make arbitrary HTTP requests.
    hosts = {'fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com'}
    if url.scheme != 'https' or url.hostname not in hosts or url.port not in (None, 443) or url.username or url.password or url.fragment:
        raise ValueError('Unsupported push provider; use Chrome, Firefox or Safari')
    keys = value.get('keys')
    if not isinstance(keys, dict):
        raise ValueError('Invalid push keys')
    checked = {}
    for name, size in (('p256dh', 65), ('auth', 16)):
        encoded = keys.get(name)
        if not isinstance(encoded, str) or len(encoded) > 100:
            raise ValueError('Invalid push key')
        try:
            raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
            if len(raw) != size:
                raise ValueError()
            if name == 'p256dh':
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid push key') from exc
        checked[name] = encoded
    return {'endpoint': endpoint, 'keys': checked}


def send_push(info, private_key, subject):
    import requests
    from pywebpush import webpush
    from py_vapid import Vapid

    class NoRedirectSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs['allow_redirects'] = False
            return super().request(method, url, **kwargs)

    vapid = Vapid.from_string(private_key)
    with NoRedirectSession() as session:
        response = webpush(subscription_info=subscription(info),
            data=json.dumps({'title': 'MARK LIV', 'body': 'A task result is ready. Open your private inbox.'}),
            vapid_private_key=vapid, vapid_claims={'sub': subject}, ttl=3600,
            timeout=10, requests_session=session)
        if not 200 <= response.status_code < 300:
            raise RuntimeError('Push provider did not accept the notification')


class RemotePush:
    def __init__(self, store, config, sender=send_push, clock=time.time):
        self.store, self.config, self.sender, self.clock = store, config, sender, clock
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS push_secrets (name TEXT PRIMARY KEY, payload BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    device_id TEXT PRIMARY KEY, payload BLOB NOT NULL, since REAL NOT NULL,
                    revision TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS push_attempts (
                    notification_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL,
                    next_at REAL NOT NULL, status TEXT NOT NULL);
            ''')

    def public_key(self):
        with self.store.lock, self.store.connect() as db:
            row = db.execute("SELECT payload FROM push_secrets WHERE name='vapid'").fetchone()
            if row:
                secret = self.store._open(row[0])
            else:
                key = ec.generate_private_key(ec.SECP256R1())
                secret = base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32, 'big')).decode().rstrip('=')
                db.execute("INSERT INTO push_secrets VALUES ('vapid', ?)", (self.store._seal(secret),))
        key = ec.derive_private_key(int.from_bytes(base64.urlsafe_b64decode(secret + '=' * (-len(secret) % 4)), 'big'), ec.SECP256R1())
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(public).decode().rstrip('=')

    def status(self, device_id):
        with self.store.connect() as db:
            row = db.execute('SELECT status FROM push_subscriptions WHERE device_id=?', (device_id,)).fetchone()
        return {'available': importlib.util.find_spec('pywebpush') is not None,
                'subscribed': row is not None, 'status': row[0] if row else 'off'}

    def subscribe(self, device_id, value):
        import uuid
        info = subscription(value)
        self.public_key()
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO push_subscriptions VALUES (?,?,?,?,?)',
                       (device_id, self.store._seal(info), self.clock(), uuid.uuid4().hex, 'enabled'))

    def unsubscribe(self, device_id):
        with self.store.connect() as db:
            db.execute('DELETE FROM push_subscriptions WHERE device_id=?', (device_id,))

    def tick(self):
        cfg = self.config()
        if not cfg.get('remote_control_enabled'):
            return
        subject = cfg.get('remote_private_url', '')
        parsed = urlsplit(subject)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return
        now = self.clock()
        with self.store.connect() as db:
            rows = db.execute('''SELECT n.id, s.device_id, s.payload, s.revision
                FROM notifications n JOIN push_subscriptions s ON n.device_id=s.device_id
                JOIN devices d ON d.id=s.device_id
                LEFT JOIN push_attempts a ON a.notification_id=n.id
                WHERE d.trusted=1 AND n.created>s.since AND n.created>? AND n.read_at IS NULL
                AND (a.notification_id IS NULL OR (a.status='retry' AND a.next_at<=?))
                ORDER BY n.created LIMIT 10''', (now - 86400, now)).fetchall()
        for row in rows:
            if not self.config().get('remote_control_enabled'):
                return
            # Atomic claim avoids simultaneous delivery. A crash leaves outcome unknown;
            # do not replay an attempt that the provider might already have accepted.
            with self.store.lock, self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('''SELECT s.payload FROM push_subscriptions s JOIN devices d ON s.device_id=d.id
                    WHERE s.device_id=? AND s.revision=? AND d.trusted=1''', (row['device_id'], row['revision'])).fetchone()
                if not current:
                    continue
                old = db.execute('SELECT * FROM push_attempts WHERE notification_id=?', (row['id'],)).fetchone()
                if old and (old['status'] != 'retry' or old['next_at'] > now):
                    continue
                attempt = old['attempts'] + 1 if old else 1
                db.execute('INSERT OR REPLACE INTO push_attempts VALUES (?,?,?,?)', (row['id'], attempt, now, 'sending'))
                secret = self.store._open(db.execute("SELECT payload FROM push_secrets WHERE name='vapid'").fetchone()[0])
                info = self.store._open(current[0])
            status, next_at = 'provider accepted; delivery unverified', now
            try:
                self.sender(info, secret, subject)
            except Exception as exc:
                response = getattr(exc, 'response', None)
                code = getattr(response, 'status_code', None)
                if code in (404, 410):
                    status = 'subscription expired; enable alerts again'
                    with self.store.connect() as db:
                        db.execute('DELETE FROM push_subscriptions WHERE device_id=? AND revision=?', (row['device_id'], row['revision']))
                elif code == 429 or (isinstance(code, int) and 500 <= code < 600):
                    status = 'retry' if attempt < 3 else 'failed; saved inbox available'
                    next_at = now + min(300, 30 * 2 ** attempt)
                else:
                    # Transport timeout can follow provider acceptance: do not duplicate it.
                    status = 'delivery unknown or refused; saved inbox available'
            with self.store.connect() as db:
                db.execute('UPDATE push_attempts SET status=?,next_at=? WHERE notification_id=?', (status, next_at, row['id']))
                db.execute('UPDATE push_subscriptions SET status=? WHERE device_id=? AND revision=?', (status, row['device_id'], row['revision']))

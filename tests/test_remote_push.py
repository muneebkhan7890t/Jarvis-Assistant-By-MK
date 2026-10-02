import base64
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from core.remote_push import RemotePush, subscription, send_push
from core.remote_store import RemoteStore


def fixture_subscription(endpoint='https://fcm.googleapis.com/fcm/send/fixture'):
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    public = key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return {'endpoint': endpoint, 'keys': {'p256dh': encode(public), 'auth': encode(b'0123456789abcdef')}}


class RemotePushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000
        self.store = RemoteStore(Path(self.tmp.name) / 'remote.db', clock=lambda: self.now)
        key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.device = self.store.enroll(base64.b64encode(key).decode(), 'Fixture', 'Android')['id']
        self.store.trust(self.device, ['computer'])
        self.config = {'remote_control_enabled': True, 'remote_private_url': 'https://fixture.example'}
        self.sent = []
        self.push = RemotePush(self.store, lambda: self.config, lambda *args: self.sent.append(args), clock=lambda: self.now)

    def result(self):
        self.now += 1
        ident, _ = self.store.enqueue(self.device, 'fixture-request-' + str(self.now), {'text': 'private project'})
        self.store.update(ident, 'completed', {'message': 'private logs'})
        return ident

    def test_endpoint_validation_rejects_local_redirect_targets_and_bad_keys(self):
        for endpoint in ('http://fcm.googleapis.com/x', 'https://127.0.0.1/x', 'https://fcm.googleapis.com.evil.test/x',
                         'https://user@fcm.googleapis.com/x', 'https://fcm.googleapis.com:8443/x', 'https://evil.test/x'):
            with self.assertRaises(ValueError):
                subscription(fixture_subscription(endpoint))
        value = fixture_subscription()
        value['keys']['p256dh'] = 'invalid'
        with self.assertRaises(ValueError):
            subscription(value)

    def test_encrypted_subscription_key_persistence_and_future_only_dedup(self):
        self.result()
        info = fixture_subscription()
        public = self.push.public_key()
        self.push.subscribe(self.device, info)
        self.push.tick()
        self.assertFalse(self.sent)
        self.result()
        self.push.tick()
        self.push.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn(info['endpoint'].encode(), self.store.path.read_bytes())
        self.assertNotIn(self.sent[0][1].encode(), self.store.path.read_bytes())
        reopened = RemotePush(self.store, lambda: self.config, clock=lambda: self.now)
        self.assertEqual(reopened.public_key(), public)

    def test_revoke_disable_read_and_unsubscribe_prevent_delivery(self):
        self.push.subscribe(self.device, fixture_subscription())
        self.result()
        self.store.revoke(self.device)
        self.push.tick()
        self.assertFalse(self.sent)
        self.store.trust(self.device, ['computer'])
        self.config['remote_control_enabled'] = False
        self.push.tick()
        self.assertFalse(self.sent)
        self.config['remote_control_enabled'] = True
        for item in self.store.notifications(self.device):
            self.store.read_notification(self.device, item['id'])
        self.push.tick()
        self.assertFalse(self.sent)
        self.result()
        self.push.unsubscribe(self.device)
        self.push.tick()
        self.assertFalse(self.sent)

    def test_provider_retry_bounded_and_expired_subscription_removed(self):
        class Refused(Exception):
            response = SimpleNamespace(status_code=503)
        def fail(*args):
            self.sent.append(args)
            raise Refused()
        self.push.sender = fail
        self.push.subscribe(self.device, fixture_subscription())
        self.result()
        self.push.tick()
        self.push.tick()
        self.assertEqual(len(self.sent), 1)
        for _ in range(4):
            self.now += 1000
            self.push.tick()
        self.assertEqual(len(self.sent), 3)
        Refused.response.status_code = 410
        self.result()
        self.push.tick()
        self.assertFalse(self.push.status(self.device)['subscribed'])

    def test_real_encryption_and_vapid_use_generic_payload_no_redirect(self):
        self.push.subscribe(self.device, fixture_subscription())
        with self.store.connect() as db:
            key = self.store._open(db.execute("SELECT payload FROM push_secrets WHERE name='vapid'").fetchone()[0])
        calls = []
        def request(session, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return SimpleNamespace(status_code=201, text='', headers={})
        with patch('requests.Session.request', request):
            send_push(fixture_subscription(), key, 'https://fixture.example')
        self.assertEqual(len(calls), 1)
        options = calls[0][2]
        self.assertFalse(options['allow_redirects'])
        self.assertIn('authorization', {k.lower() for k in options['headers']})
        self.assertIsInstance(options['data'], bytes)
        self.assertNotIn(b'A task result', options['data'])

    def test_ambiguous_transport_failure_is_not_replayed(self):
        def fail(*args):
            self.sent.append(args)
            raise TimeoutError()
        self.push.sender = fail
        self.push.subscribe(self.device, fixture_subscription())
        self.result()
        self.push.tick()
        self.now += 1000
        self.push.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('unknown', self.push.status(self.device)['status'])

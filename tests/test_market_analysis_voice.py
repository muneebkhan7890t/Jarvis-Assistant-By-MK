import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch
from core import confirm
from core.market_analysis import metrics, analyze, analyze_asset, FRAMES
from core.permission_manager import PermissionManager
from core.intent_router import route


def fixture_candles(symbol, frame, now=1800000000):
    duration = FRAMES[frame]
    boundary = int(now // duration) * duration
    rows = []
    for i in range(100):
        close = 100 + i * .5
        opened = boundary - (100 - i) * duration
        rows.append([opened * 1000, str(close - .1), str(close + 1), str(close - 1), str(close), '100', (opened + duration) * 1000 - 1])
    return rows


class MarketAnalysisTests(unittest.TestCase):
    def test_actual_multiframe_indicators_and_conditional_levels(self):
        report = analyze_asset('BTCUSDT', fixture_candles, now=1800000000)
        self.assertEqual(set(report['timeframes']), set(FRAMES))
        self.assertFalse(report['orders_placed'])
        self.assertEqual(report['timeframes']['1h']['trend'], 'up')
        self.assertEqual(report['timeframes']['1h']['rsi14'], 100)
        self.assertIn('CONDITIONAL', report['status'])
        self.assertLess(report['invalidation_stop'], report['trigger_level'])
        self.assertGreater(report['illustrative_targets'][0], report['trigger_level'])
        self.assertIn('future closed', report['entry_condition'])

    def test_stale_incomplete_invalid_and_missing_candles_refused(self):
        rows = fixture_candles('BTCUSDT', '15m')
        for data, now in ((rows[:10],1800000000), (rows,1800010000), (rows[:50]+rows[51:],1800000000)):
            with self.assertRaises(ValueError):
                metrics(data, '15m', now)
        rows[-1][4] = 'nan'
        with self.assertRaises(ValueError):
            metrics(rows, '15m', 1800000000)

    def test_gold_and_feed_failure_are_data_requirements_not_blanket_refusal(self):
        self.assertEqual(analyze('gold')['status'], 'DATA REQUIRED')
        def unavailable(*args):
            raise OSError()
        result = analyze('best', unavailable)
        self.assertEqual(len(result['reports']), 2)
        self.assertTrue(all(r['status'] == 'DATA UNAVAILABLE' for r in result['reports']))
        self.assertEqual(route('give me a best trade setup').name, 'market_analysis')
        self.assertEqual(route('check gold').parameters['asset'], 'gold')


class VoiceConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = PermissionManager(Path(self.temp.name)/'permissions.json')
        self.shown, self.logs = [], []
        confirm._pending = None
        confirm._executing = False
        confirm.bind(lambda *args: self.shown.append(args), lambda: None, self.logs.append)
        self.config = patch('memory.config_manager.load_api_keys', return_value={'voice_confirmation_enabled':True})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(lambda: confirm.bind(None,None,None))
        self.addCleanup(lambda: setattr(confirm,'_pending',None))

    def wait_done(self):
        for _ in range(100):
            if not confirm._executing:
                return
            time.sleep(.01)
        self.fail('Approval worker did not finish')

    def test_exact_code_once_and_generic_or_remote_input_cannot_approve(self):
        event = threading.Event()
        calls = []
        self.manager.set('open_app','Ask')
        result = self.manager.invoke('open_app',{'app_name':'calculator'},lambda p: calls.append(p) or event.set() or 'Returned')
        self.assertIn('digit by digit',result)
        code = confirm._pending.voice_code
        for phrase in ('yes','okay','Jarvis confirm 0000','Do not Jarvis confirm '+code):
            self.assertFalse(confirm.resolve_voice(phrase,local_session=True))
        self.assertFalse(confirm.resolve_voice('Jarvis confirm '+code,local_session=False))
        self.assertEqual(calls,[])
        self.assertTrue(confirm.resolve_voice('Jarvis confirm '+' '.join(code),local_session=True))
        self.assertTrue(event.wait(2))
        self.wait_done()
        self.assertFalse(confirm.resolve_voice('Jarvis confirm '+code,local_session=True))
        self.assertEqual(len(calls),1)

    def test_cancel_expiry_denial_and_critical_no_voice(self):
        self.manager.set('open_app','Ask')
        call=lambda p: self.fail('Must not execute')
        self.manager.invoke('open_app',{'app_name':'calculator'},call)
        code=confirm._pending.voice_code
        self.assertTrue(confirm.resolve_voice('Jarvis cancel '+code,local_session=True))
        self.assertIsNone(confirm._pending)
        self.manager.invoke('open_app',{'app_name':'calculator'},call)
        code=confirm._pending.voice_code
        confirm._pending.at-=100
        self.assertFalse(confirm.resolve_voice('Jarvis confirm '+code,local_session=True))
        confirm._pending=None
        self.manager.invoke('open_app',{'app_name':'calculator'},call)
        code=confirm._pending.voice_code
        self.manager.set('open_app','Deny')
        self.assertTrue(confirm.resolve_voice('Jarvis confirm '+code,local_session=True))
        self.wait_done()
        self.manager.invoke('computer_settings',{'action':'shutdown'},call)
        self.assertEqual(confirm._pending.voice_code,'')

    def test_policy_off_and_phone_source_do_not_offer_voice(self):
        self.manager.set('open_app','Ask')
        self.manager.invoke('open_app',{'app_name':'calculator'},lambda p:'Done',source='phone')
        self.assertEqual(confirm._pending.voice_code,'')
        confirm._pending=None
        with patch('memory.config_manager.load_api_keys',return_value={}):
            self.manager.invoke('open_app',{'app_name':'calculator'},lambda p:'Done')
            self.assertEqual(confirm._pending.voice_code,'')

    def test_old_key_cannot_consume_new_pending_action(self):
        confirm.request('first','First','Details',lambda:'No',voice_eligible=True)
        old=confirm._pending
        confirm.resolve(False)
        confirm.request('second','Second','Details',lambda:'No',voice_eligible=True)
        confirm.resolve(True,expected_key=old.key,expected_code=old.voice_code)
        self.assertEqual(confirm._pending.key,'second')

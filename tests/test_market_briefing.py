import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from core.market_briefing import fetch_market_briefing, select_articles


class MarketBriefingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)

    def article(self, title='Bitcoin market update', **changes):
        return dict({'title': title, 'snippet': 'Fixture report, not a quote.',
                     'date': self.now.isoformat(), 'source': 'Fixture News',
                     'url': 'https://example.com/news'}, **changes)

    def test_both_topics_sources_and_timestamps(self):
        queries = []
        def search(query, **kwargs):
            queries.append(query)
            return [self.article('Gold bullion update' if 'gold' in query else 'Bitcoin update')]
        result = fetch_market_briefing(search=search, now=self.now)
        self.assertEqual(len(queries), 2)
        for text in ('CRYPTO', 'GOLD', 'Bitcoin update', 'Gold bullion update', 'Published:', 'Fixture News', 'https://example.com/news', 'not live quotes'):
            self.assertIn(text, result)

    def test_rss_metadata_and_unsafe_xml(self):
        from core.market_briefing import news_feed
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'<rss><channel><item><title>Bitcoin update</title><link>https://example.com/a</link><source>Example</source><pubDate>Wed, 30 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        with patch('core.market_briefing.urlopen', return_value=response):
            rows = news_feed('Bitcoin')
            self.assertEqual(rows[0]['source'], 'Example')
            self.assertEqual(len(select_articles('Crypto', rows, self.now)), 1)
            response.read.return_value = b'<!DOCTYPE rss [<!ENTITY x "test">]><rss />'
            with self.assertRaises(ValueError):
                news_feed('Bitcoin')

    def test_old_future_undated_unrelated_and_unsafe_reports_rejected(self):
        rows = [self.article(date=(self.now - timedelta(days=4)).isoformat()),
                self.article(date=(self.now + timedelta(days=1)).isoformat()),
                self.article(date=''), self.article('Football match result'),
                self.article(url='javascript:alert(1)'), self.article(url='https://u:p@example.com')]
        self.assertEqual(select_articles('Crypto', rows, self.now), [])
        self.assertEqual(fetch_market_briefing(search=lambda *a, **k: rows, now=self.now), '')

    def test_partial_failure_dedup_and_newest_first(self):
        def search(query, **kwargs):
            if 'gold' in query:
                raise OSError('fixture offline')
            old = self.article('Bitcoin older report', date=(self.now - timedelta(hours=5)).isoformat())
            return [old, self.article(), self.article()]
        result = fetch_market_briefing(search=search, now=self.now)
        self.assertIn('No recent timestamped reports available', result)
        self.assertEqual(result.count('Bitcoin market update'), 1)
        self.assertLess(result.index('Bitcoin market update'), result.index('Bitcoin older report'))

    def test_startup_sends_market_greeting_and_both_topic_instructions(self):
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_send_startup_briefing')
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        env = {'asyncio': asyncio, 'datetime': datetime, 'load_memory': lambda: {},
               'pop_last_session': lambda: None, 'fetch_market_briefing': lambda: 'CRYPTO\nBitcoin fixture report with source.\nGOLD\nGold fixture report with source.'}
        exec(compile(module, 'main.py', 'exec'), env)
        async def run():
            shown = []
            sent = AsyncMock()
            instance = SimpleNamespace(session=SimpleNamespace(send_client_content=sent), _turn_done_event=None,
                ui=SimpleNamespace(write_log=lambda text: None, show_content=lambda *args: shown.append(args)))
            real_sleep = asyncio.sleep
            with patch.object(asyncio, 'sleep', new=AsyncMock()):
                await env['_send_startup_briefing'](instance)
                for _ in range(100):
                    if sent.await_count == 2:
                        break
                    await real_sleep(.01)
            self.assertEqual(sent.await_count, 2)
            first = sent.call_args_list[0].kwargs['turns']['parts'][0]['text']
            second = sent.call_args_list[1].kwargs['turns']['parts'][0]['text']
            self.assertIn('crypto and gold', first)
            self.assertIn('one short crypto update and one short gold update', second)
            self.assertIn('Do not recommend or execute trades', second)
            self.assertEqual(shown[0][0], 'MARKETS — Crypto & Gold')
        asyncio.run(run())

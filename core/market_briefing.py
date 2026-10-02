"""Read-only, dated crypto and gold headlines for the startup briefing."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import queue
import re
import threading
import time
from urllib.parse import urlsplit
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

TOPICS = {
    'Crypto': ('Bitcoin Ethereum cryptocurrency market news', r'\b(bitcoin|ethereum|crypto\w*|btc|eth|blockchain)\b'),
    'Gold': ('gold XAUUSD precious metals market news', r'\b(gold|xauusd|bullion|precious metals)\b'),
}


def news_feed(query, max_results=8):
    url = 'https://news.google.com/rss/search?' + urlencode({
        'q': query + ' when:3d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    with urlopen(Request(url, headers={'User-Agent': 'MARK-LIV/1.0'}), timeout=7) as response:
        raw = response.read(500001)
    if len(raw) > 500000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported news feed')
    rows = []
    for item in ElementTree.fromstring(raw).findall('./channel/item')[:100]:
        rows.append({'title': item.findtext('title', ''), 'snippet': '',
                     'url': item.findtext('link', ''), 'source': item.findtext('source', ''),
                     'date': item.findtext('pubDate', '')})
    return rows


def published(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            result = parsedate_to_datetime(value)
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def clean(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def select_articles(topic, rows, now):
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, snippet = clean(row.get('title'), 250), clean(row.get('snippet'), 400)
        date = published(row.get('date'))
        url = row.get('url', '')
        try:
            link = urlsplit(url)
            valid_url = link.scheme == 'https' and link.hostname and not link.username and not link.password
        except (ValueError, TypeError):
            valid_url = False
        if not title or not valid_url or not date or not now - timedelta(hours=72) <= date <= now + timedelta(minutes=5):
            continue
        if not re.search(TOPICS[topic][1], title + ' ' + snippet, re.I):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({'title': title, 'snippet': snippet, 'url': url[:2000],
                       'source': clean(row.get('source') or link.hostname, 100), 'date': date})
    return sorted(result, key=lambda row: row['date'], reverse=True)[:3]


def fetch_market_briefing(search=None, now=None, timeout=9):
    if search is None:
        search = news_feed
    now = now or datetime.now(timezone.utc)
    completed = queue.Queue()
    def fetch(topic, query):
        try:
            rows = select_articles(topic, search(query, max_results=8), now)
        except Exception:
            rows = []
        completed.put((topic, rows))
    for topic, (query, _pattern) in TOPICS.items():
        threading.Thread(target=fetch, args=(topic, query), daemon=True).start()
    deadline = time.monotonic() + timeout
    results = {}
    while len(results) < len(TOPICS):
        try:
            topic, rows = completed.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            break
        results[topic] = rows
    if not any(results.values()):
        return ''
    lines = ['Crypto and gold news', 'Retrieved: ' + now.strftime('%Y-%m-%d %H:%M UTC'),
             'Dated reports from the last 72 hours. Article prices are not live quotes.']
    for topic in TOPICS:
        lines.extend(['', topic.upper()])
        rows = results.get(topic, [])
        if not rows:
            lines.append('No recent timestamped reports available for this topic. Do not infer an update.')
        for row in rows:
            lines.extend([row['title'], row['snippet'],
                          'Published: ' + row['date'].strftime('%Y-%m-%d %H:%M UTC') + ' | ' + row['source'],
                          row['url']])
    return '\n'.join(lines)

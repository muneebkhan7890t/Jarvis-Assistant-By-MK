"""Public spot-candle analysis only. No credentials, accounts or order endpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import time
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = 'https://data-api.binance.vision/api/v3/klines'
FRAMES = {'1d': 86400, '4h': 14400, '1h': 3600, '15m': 900}


def candles(symbol, frame):
    if symbol not in ('BTCUSDT', 'ETHUSDT') or frame not in FRAMES:
        raise ValueError('Unsupported public market')
    url = BASE + '?' + urlencode({'symbol': symbol, 'interval': frame, 'limit': 150})
    with urlopen(url, timeout=8) as response:
        raw = response.read(200001)
    if len(raw) > 200000:
        raise ValueError('Oversized candle response')
    return json.loads(raw)


def ema(values, period):
    result = [values[0]]
    factor = 2 / (period + 1)
    for value in values[1:]:
        result.append(result[-1] + factor * (value - result[-1]))
    return result


def metrics(raw, frame, now):
    if not isinstance(raw, list):
        raise ValueError('Invalid candle response')
    bars = []
    for row in raw:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError('Incomplete candles')
        opened, closed = float(row[0]) / 1000, float(row[6]) / 1000
        if closed >= now:
            continue  # Never treat an unfinished candle as confirmation.
        o, h, l, c, v = map(float, row[1:6])
        if not all(math.isfinite(x) for x in (opened, closed, o, h, l, c, v)) or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
            raise ValueError('Invalid OHLCV values')
        if bars and opened - bars[-1]['opened'] != FRAMES[frame]:
            raise ValueError('Missing or unordered candles')
        bars.append({'opened': opened, 'closed': closed, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v})
    if len(bars) < 60 or now - bars[-1]['closed'] > FRAMES[frame] + 120:
        raise ValueError('Insufficient or stale candles')
    prices = [bar['c'] for bar in bars]
    fast, slow = ema(prices, 20)[-1], ema(prices, 50)[-1]
    differences = [b - a for a, b in zip(prices, prices[1:])]
    gain = sum(max(x, 0) for x in differences[:14]) / 14
    loss = sum(max(-x, 0) for x in differences[:14]) / 14
    for delta in differences[14:]:
        gain, loss = (gain * 13 + max(delta, 0)) / 14, (loss * 13 + max(-delta, 0)) / 14
    rsi = 100 - 100 / (1 + gain / loss) if loss else (100 if gain else 50)
    ranges = [max(b['h'] - b['l'], abs(b['h'] - a['c']), abs(b['l'] - a['c'])) for a, b in zip(bars, bars[1:])]
    atr = sum(ranges[:14]) / 14
    for value in ranges[14:]:
        atr = (atr * 13 + value) / 14
    macd = [a - b for a, b in zip(ema(prices, 12), ema(prices, 26))]
    return {'trend': 'up' if prices[-1] > fast > slow else ('down' if prices[-1] < fast < slow else 'mixed'),
            'last_closed_price': prices[-1], 'last_close_utc': datetime.fromtimestamp(bars[-1]['closed'], timezone.utc).isoformat(),
            'ema20': fast, 'ema50': slow, 'rsi14': rsi, 'atr14': atr,
            'macd': macd[-1], 'macd_signal': ema(macd, 9)[-1],
            'support_20_bars': min(b['l'] for b in bars[-21:-1]),
            'resistance_20_bars': max(b['h'] for b in bars[-21:-1]),
            'last_volume': bars[-1]['v'], 'mean_prior_20_volume': sum(b['v'] for b in bars[-21:-1]) / 20}


def analyze_asset(symbol, fetch=candles, now=None):
    now = time.time() if now is None else now
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(FRAMES)
        raw = list(pool.map(lambda frame: fetch(symbol, frame), frames))
    data = {frame: metrics(rows, frame, now) for frame, rows in zip(frames, raw)}
    result = {'asset': symbol, 'source': BASE, 'as_of_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
              'market': 'Binance spot, USDT quote; not futures or a gold broker', 'timeframes': data,
              'status': 'NO ALIGNED SETUP', 'orders_placed': False,
              'method': 'Illustrative EMA20/50 trend-aligned breakout watchlist, not a validated or personalized strategy',
              'missing_checks': ['live spread and executable quote', 'news/economic calendar risk',
                                 'derivatives/funding/liquidations', 'account risk, fees and position size']}
    direction = data['1d']['trend']
    if direction == 'mixed' or any(data[f]['trend'] != direction for f in ('4h', '1h')):
        return result
    long = direction == 'up'
    hour, entry = data['1h'], data['15m']
    level = hour['resistance_20_bars'] if long else hour['support_20_bars']
    if (long and entry['last_closed_price'] >= level) or (not long and entry['last_closed_price'] <= level):
        result['status'] = 'WAIT FOR A NEW SETUP; BREAKOUT LEVEL ALREADY PASSED'
        return result
    stop = hour['support_20_bars'] - .25 * hour['atr14'] if long else hour['resistance_20_bars'] + .25 * hour['atr14']
    risk = abs(level - stop)
    if not math.isfinite(risk) or risk <= 0 or stop <= 0:
        return result
    targets = [level + (1 if long else -1) * risk * multiple for multiple in (1, 2, 3)]
    if min(targets) <= 0:
        return result
    result.update(status='CONDITIONAL WATCHLIST — NOT READY TO EXECUTE', direction='LONG' if long else 'SHORT SCENARIO (spot does not authorize short selling)',
        trigger_level=level, invalidation_stop=stop, illustrative_targets=targets,
        target_risk_multiples=[1, 2, 3], position_size='Not calculated: account and instrument risk inputs are unavailable',
        entry_condition=f"Wait for a future closed 15m candle {'above' if long else 'below'} {level:.8g}; then recheck spread, news, calendar and risk. Do not chase.",
        confidence='Uncalibrated; no profit probability claimed')
    return result


def analyze(request='best', fetch=candles):
    request = str(request).lower().strip()
    if request in ('gold', 'xauusd', 'xau/usd'):
        return {'asset': 'XAUUSD', 'status': 'DATA REQUIRED', 'orders_placed': False,
                'message': 'Gold analysis is allowed. Provide dated D/4H/1H/15m chart data or connect a read-only gold data provider. News alone cannot establish a numerical trade setup; PAXG is not substituted for spot gold.'}
    symbols = {'btc': ['BTCUSDT'], 'bitcoin': ['BTCUSDT'], 'btcusdt': ['BTCUSDT'],
               'eth': ['ETHUSDT'], 'ethereum': ['ETHUSDT'], 'ethusdt': ['ETHUSDT'],
               'best': ['BTCUSDT', 'ETHUSDT'], 'crypto': ['BTCUSDT', 'ETHUSDT']}.get(request)
    if not symbols:
        raise ValueError('Choose best, BTC, ETH or gold')
    reports = []
    for symbol in symbols:
        try:
            reports.append(analyze_asset(symbol, fetch))
        except Exception:
            reports.append({'asset': symbol, 'status': 'DATA UNAVAILABLE', 'orders_placed': False,
                            'message': 'Could not verify fresh, complete public candles. No levels invented. Retry later or provide chart data.'})
    return {'reports': reports, 'selection': 'Compare available watchlists; there is no calibrated best/profit ranking. NO GOOD TRADE is a valid outcome.',
            'execution': 'Read-only analysis. No account access, order creation or trade approval mechanism.'}

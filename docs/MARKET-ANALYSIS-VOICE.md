# Market setups and voice confirmations

## Ask for analysis

Say “give me the best trade setup”, “analyze Bitcoin”, “analyze Ethereum” or
“check gold”. The assistant has a dedicated read-only `market_analysis` tool.
Exact typed variants also route locally. Analysis is not an order request and
does not need a trading approval. Existing Network Deny settings still apply.

BTC/USDT and ETH/USDT use Binance's public spot-data endpoint without credentials.
The tool fetches daily, 4-hour, 1-hour and 15-minute candles, excludes unfinished
candles, checks continuity/freshness and computes EMA20/50, Wilder RSI14/ATR14,
MACD12/26/signal9, recent support/resistance and volume summaries.

The illustrative method looks for aligned daily/4h/1h trends and a future breakout
of the previous 20 hourly bars. It produces conditional trigger, invalidation and
1R/2R/3R target levels only if eligible; an already-passed trigger is not chased.
It can return NO ALIGNED SETUP. It is not a backtested strategy or a calibrated
profit ranking, and it does not implement the complete supplied trading spec.
Stops include a 0.25 hourly-ATR buffer beyond the opposite 20-bar level. This is
an explicit illustrative rule, not the user's configured strategy.

Prices are last closed candle values, not executable quotes. Spread, news/calendar
risk, derivatives data, fees, account balance and position sizing are not verified.
Results remain watchlists, never “ready to execute.” No trading account, broker
connector, order endpoint or automatic position management is added.

Gold needs a read-only XAU/USD feed or dated multi-timeframe charts. The assistant
asks for this data instead of refusing all analysis or inventing levels. It never
substitutes a gold-backed crypto token for broker spot gold.

Reference: [Binance public market-data endpoint](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md).

## Confirm eligible local actions by voice

Enable **Local voice confirmation codes** in Controls → Privacy and Mode. It has
been enabled for this installation at the owner's request. Existing permission
states are retained; Deny cannot be overridden by a voice code.

When an eligible local action needs approval, the assistant explains it and gives
a fresh four-digit code. Say **“Jarvis confirm 4 8 2 1”** using the actual code it
just gave you, or **“Jarvis cancel 4 8 2 1”**. Digits spoken individually are accepted.
A generic yes/okay, incorrect code, expired code or reused code does nothing.
The normal 90-second expiry and bound action/arguments remain in place.

The code is accepted only from local input transcription while awake and unmuted.
Model output and tool arguments cannot approve it. Phone-origin requests are not
eligible; local voice approval is also disabled while a phone owns the shared Live
session or legacy remote mode is enabled. Restart to release a pinned phone session.
The button remains as a fallback; eligible actions no longer require clicking it.

Voice approval covers selected read/browser/app/screen/camera/memory/productivity/
monitoring/settings/network/system actions. Terminal execution, deletion, writes,
messages, credentials, power and critical actions retain separate desktop review.
Workspace and project-profile review dialogs are unchanged. Trade execution is not
implemented, and voice approval does not create or authorize a trade.

**This is not speaker verification.** Someone audible to the local microphone who
knows the current code could approve it. Keep the option off when that risk is
unacceptable. Cloud speech transcription is required, so offline voice approval
and untested language/recognition variants are not promised.

Tests cover actual indicator calculations on fixture candles, stale/malformed
data, unavailable gold/data sources, routing, code matching, single use, cancellation,
expiry, permission changes, phone/config exclusion and old-request binding. Native
speech recognition with a physical microphone still needs an owner test.

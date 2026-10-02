# Crypto and gold startup briefing

The customized app's footer now reads **By MuneebKhan**. Original upstream license
attribution and resource links remain intact.

When startup briefing is enabled and the cloud voice session is awake and connected,
MARK LIV greets you, fetches separate crypto and gold news lists, and speaks one
short update for each topic. The content panel is labelled **MARKETS — Crypto & Gold**
and includes publisher names, publication dates and source links. The settings drawer
calls the existing toggle **CRYPTO / GOLD BRIEF**. It still runs once per app launch.

Public Google News RSS searches run concurrently with a bounded wait. Only HTTPS
article links with a parseable publication date within the past 72 hours are used;
duplicate titles and unrelated results are filtered. A maximum of three articles
per topic is shown. Retrieved news is treated as untrusted source content.

This is a recent-headline briefing, not a live quote feed or comprehensive market
analysis. Article prices must not be described as current executable prices. If a
topic has no suitable reports, the assistant says so. If both fail, it says fresh
crypto/gold news is unavailable; it does not substitute general world news.
The existing mute, wake-word and offline behavior remains in effect.

The supplied trading specification is a separate future integration. This change
does not connect an exchange, calculate trade setups, authenticate trade approvals,
place orders or manage positions. The assistant prompt explicitly disallows using
general browser/desktop/shell tools as a substitute for a trading integration.

Validation covers topic separation, metadata, date/relevance/URL filtering,
duplicate handling, partial failure, unsafe XML rejection and the actual startup
method's greeting and news instructions with a mocked cloud session. A live feed
check returned six dated articles across both topics. Spoken output still depends
on a working cloud session and audio device.

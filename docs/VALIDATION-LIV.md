# Validation of this upgrade

Environment: Windows, Python 3.12.4. No cloud requests, messages, purchases,
shutdowns, firewall changes or physical device actions were issued for testing.

## Automated checks

`python -m unittest discover -s tests -q`: 168 tests passing (existing tests retained
with phone-project expectations updated for required human approval, and syntax
checks scoped to project source rather than its bundled environment).

The remote upgrade adds 16 tests for real device signatures/replay protection,
trust and scopes, encrypted receipts, deduplication/recovery, safe downloads,
capture notices, chat relay/AI restrictions and voice tickets/revocation. Windows
DPAPI checks ran under the normal Windows account because the restricted runner
cannot unlock that account's DPAPI context. The latest full suite passed in 18.852 s.

The crypto/gold briefing adds five tests covering both topics, dated sources,
freshness and URL/relevance filtering, missing data, deduplication, RSS metadata/
unsafe XML handling and the actual startup method with a mocked voice session.
The footer widget was instantiated and its MuneebKhan credit verified. A separate
read-only public-feed check returned six dated articles across both topics. No
trade, account connection or financial transaction was tested or implemented.
Remote API tests now isolate permission settings instead of depending on the
owner's live PC preferences.

Continue Work adds nine tests for encrypted checkpoint persistence, revision
conflicts and deletion, path/app/URL validation, exact reviewed plans and receipts,
stale or tampered plans, denied or changing permissions, missing folders and partial
failures, local typed entry points, and UI save/cancel/dirty-edit/delete behavior.
All workspace launch adapters are mocked. The desktop page was rendered and inspected
with a temporary checkpoint using scripts/validate_workspace_ui.py.

Phone playback/push adds eight tests: provider endpoint/key validation, encrypted
subscription and VAPID persistence, future-only deduplication, revoke/disable/read/
unsubscribe behavior, bounded provider retries and expiry, real Web Push encryption
and VAPID signing with a mocked HTTP transport, ambiguous timeout non-replay, signed
audio tickets/PCM/interruption/revocation/replay, and subscription routes/assets.
Edge also played synthetic PCM through Web Audio and rendered the opt-in push
controls. Real phone sound and closed-app push delivery have not been verified.

The project continuation adds 15 tests for fixed reviewed profiles, encrypted
revision checks, terminal denial and executable changes, actual temporary Python
processes, output/exit status/timeouts, child-process cleanup, revocation, server
ports and shutdown, PC approval UI, workflow cancellation/version/scope checks,
automation controls and durable device-scoped notifications.

A headless Edge browser at 390×844 also passed pairing, WebCrypto signing,
approval, mocked PC dispatch, durable receipts, saved-key reconnection, fake
microphone PCM delivery and revocation against a temporary loopback HTTPS server.
It also ran a harmless temporary project task and exercised workflow/automation
controls and the saved inbox. Existing user project/job lists were replaced with
test adapters. The latest browser run passed all assertions but emitted Windows
asyncio connection-reset diagnostics during TLS connection teardown.
Phone and desktop screenshots were inspected. No physical phone, real microphone,
Gemini speech request, mobile-data connection or closed-app push was tested.

Coverage includes notes/tasks/jobs, recovery/cancellation, certificates,
configuration precedence, human approval expiry/rejection/argument binding,
permission deny/always-ask, local/offline text dispatch, AST restrictions, project
paths, workflow validation/execution, automation duration/cooldown, memory
metadata/dedup/pin preservation, project records, rate limiting, authentication,
token rotation/revocation, origins, uploads, body limits, archive extraction and
source package exclusions. Unit-test mocks prevent actual desktop/network effects;
they are not production implementations.

The productivity continuation adds 26 tests: legacy SQLite migration, metadata
and search, optimistic edit conflicts, guarded undo, reminder persistence/history,
failed reschedule recovery, repeat calculations, cancellation/generation checks,
eight concurrent delivery claims, native timing/path serialization, and actual
Qt create/edit/filter/complete/pin/undo flows. Qt tests verify worker-thread I/O
and main-thread completion callbacks, including closure during pending I/O.
Native schedulers/notifications are mocked;
these tests do not create real OS jobs.

The automation continuation adds 18 engine/Qt tests covering compatible legacy
definitions, strict validation and file-size limits, tampered actions, revisions,
run-now cooldown/enabled checks, pause/reset behavior, overlapping invocations,
mid-batch privacy opt-out, failed/confirmation results, real registry permission
denial, tool controls, visual create/enable/run/disable/delete, and preservation of
unsaved form content during status refresh. Dispatch is mocked except for the
permission-denial integration; no actual application or computer setting changes.

## Import/UI/performance checks

- `main` imported successfully in approximately 1.874 seconds in the inspected
  environment. OpenCV was not loaded by that import.
- Action discovery returned 24 handlers with no rejected modules.
- The extracted Qt control panel instantiated and rendered offscreen. Permissions
  and Privacy pages were visually inspected. A system font was explicitly loaded
  for the offscreen renderer (its font database was empty); normal native Qt font
  selection is unchanged.
- Tasks, Notes and Reminders pages also rendered at 900 x 650 with temporary
  sample records; all three were visually inspected and their controls were
  exercised in the Qt tests.
- The visual Automation Manager was rendered and inspected with a disabled sample
  rule. Common controls are in a scrollable editor; data and actions are temporary
  fixtures, not changes to the user's monitoring configuration.
- 1,000 `open calculator` intent matches: median 0.0108 ms, p95 0.0131 ms.
  This measures routing only, not microphone/STT/tool/TTS latency. It is a single
  machine microbenchmark, not a cross-platform performance guarantee.
- Read-only health-check CLI found the core packages, SQLite and sufficient disk.
  It detected credentials without displaying them. Docker was unavailable.
- Source archive integrity and exclusion checks run after packaging. No bundled
  private key, API config, user database, memory JSON, .venv or bytecode is included.

## Not verified

Live Gemini conversation, physical microphone/speaker/wake word/camera, actual
browser automation and messaging delivery, a physical phone TLS session, smart
home hardware, real native reminder notification/scheduling, container execution,
and installation on fresh macOS/Linux hosts.
There is no speaker verifier or continuous-perception implementation to validate.

The installed FastAPI/Starlette test client emits an httpx deprecation warning;
the tests pass. Fault-injection tests deliberately log malformed configuration and
failed event subscribers; these are expected test diagnostics.


## Runtime repair

The original workspace `.venv` could not launch: its Python 3.14 base executable
was inaccessible. It was retained. A new `.venv-liv` uses the available Python
3.12.4 with system-site-packages for this workspace. Windows setup now creates
`.venv-liv`, and the VBS launcher probes candidate interpreters before launching.
The complete automated suite was also run through the replacement interpreter.
The source release excludes both environments.

## Trade analysis and local voice confirmation

Seven additional tests cover multi-timeframe calculations, missing/stale candles, gold data requirements, exact voice codes, cancellation, expiry, replay, permission changes and remote-source exclusion. A separate public BTC feed check returned all four timeframes and no aligned setup. Actual microphone confirmation remains to be checked by the user. Voice codes are not speaker verification; financial execution remains unavailable. See MARKET-ANALYSIS-VOICE.md.

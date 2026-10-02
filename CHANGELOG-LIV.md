# MARK LIV incremental upgrade

Added read-only BTC/ETH multi-timeframe analysis and conditional setup watchlists,
explicit gold data requirements, and exact local routing for analysis requests.
Added opt-in one-time local voice approval codes for eligible actions with expiry,
replay rejection and permission rechecks. Critical/destructive actions keep desktop
review; no trading execution or speaker verification is implemented. Seven tests
bring the suite to 168; live public BTC candles were retrieved successfully.

September 30: changed the app footer to By MuneebKhan and replaced general startup
news with separate dated crypto/gold reports and source links. Added bounded RSS
fetching, freshness/relevance filtering, honest unavailable-data responses, and
startup integration tests. This adds market news, not trading execution.

Continue Work: encrypted editable checkpoints, project-context import, notes and
next steps, supported app/folder/HTTPS reopening after exact PC review, revision
conflict checks, permission rechecks, truthful partial results and local text-command
entry points. No automatic activity capture or unsaved-buffer restoration. Added
nine store/policy/routing/UI tests. See docs/CONTINUE-WORK.md.

September 29 phone continuation: opt-in shared assistant audio playback on the
phone, bounded queues and interruption/revocation handling, encrypted Web Push
subscriptions and VAPID keys, generic lock-screen alerts for future task results,
provider allowlisting and bounded explicit-refusal retries. Phone permission is
required; physical delivery remains unverified. Added eight security/transport
tests and synthetic phone playback to Edge validation. See
docs/PHONE-REPLIES-AND-ALERTS.md for setup and limits.

September 23 remote continuation: PC-reviewed fixed project commands, Windows-owned
task/server processes with bounded logs, cancellation and timeout cleanup, saved
low-risk workflow execution, automation enable/disable/run controls, and encrypted
device-scoped notification inboxes. Added Remote Projects PC approval UI and phone
pages. Added 15 tests; all 139 pass. Headless Edge exercised temporary project
execution and the new controls. Closed-app push and physical-phone validation remain
pending. See docs/REMOTE-PROJECTS.md for host-execution boundaries and setup.

Automation continuation: replaced the automation JSON-only tab with a visual
condition/action editor and enable/disable/run-now/delete controls. Added runtime
status, last run, next-check estimate, explicit failure/approval-request outcomes,
revision checks, per-rule execution claims, strict persisted-rule validation and
privacy opt-out checks between rules. Added 18 engine/UI tests. Existing rule
storage and permission-gated action dispatch remain in use.

September 21 continuation: added persistent reminder IDs/history, edit/cancel/
snooze/complete and daily/weekly/weekday repeats using the existing native
schedulers. Added Tasks, Notes and Reminders Qt pages, task priority/project/tags,
note categories/pins, metadata search, conflict-aware edits and notes/tasks undo.
Storage migration retains prior records; scheduler failures are recorded. Native
workers reject superseded jobs and claim delivery atomically. UI storage and
scheduler work runs on worker threads. Added database, scheduler and Qt tests.

Added central permissions, bound desktop approvals, a local text router, activity
and routing metrics, event bus, private-state release exclusions, keyring fallback,
phone session security, bounded desktop instructions and container-only generated
Python execution. Added semantic workflows, state automations, project records,
temporary computer context, memory metadata/pins and a desktop control panel.

Retained the Live voice HUD, action/plugin signatures, file/media/browser tools,
notes/tasks/jobs, wake word, phone audio, existing reminders and undo. Runtime
remote access and background/clipboard monitoring now default off. Insecure host
execution of generated scripts and host dependency auto-install are restricted.
The old bundled key must be rotated. Existing user databases were not deleted.

This release is an incremental foundation. The phase report explicitly lists
partial and unimplemented capabilities; it is not a completed forty-phase product.

Windows launcher/setup now prefer a verified `.venv-liv` runtime, recovering from
a stale bundled environment without deleting it.

# Phone replies and background alerts

## Hear replies on the phone

Restart MARK LIV, refresh the phone page, and open Chat. Enable Chat and Voice
globally and for your trusted device in the PC's Remote Devices settings. Press
**Play replies on phone** to hear the existing cloud assistant's 24 kHz audio.
**Start microphone** is a separate opt-in control. Headphones help prevent echo.

This is the existing shared PC conversation: audio may include replies to someone
at the PC. The session is pinned to one phone until app restart. PC playback is
retained. Leaving Chat, hiding the page, stopping playback, revoking permissions,
disconnecting the cloud session or reaching the 15-minute limit ends the stream.
Slow clients are disconnected instead of accumulating old speech. A PC interrupt
clears pending phone playback. Mobile background speech is not implemented.

## Enable background notifications

The optional dependency is installed with:

```powershell
.\.venv-liv\Scripts\python.exe -m pip install -r requirements-push.txt
```

The development installation already has it. After restarting the app, open
**Notifications → Enable phone alerts** on the trusted phone and allow the browser
permission prompt. On iPhone, add the page to the Home Screen and open it there.
The browser and platform must support Web Push. Currently accepted providers are
Chrome/FCM, Firefox/Mozilla and Safari/Apple. Other endpoints are refused.

Alerts cover future completion/failure records from remote commands, project tasks,
workflows and automation runs. Older unread records remain in the saved inbox and
are not pushed when subscribing. This does not add hardware watchers or reminders
to the push queue. Choose Disable phone alerts to unsubscribe on the PC and browser.

The lock screen shows only “A task result is ready. Open your private inbox.”
Project names, file paths, output and chat text are not in the push payload.
The browser's push provider still handles delivery and sees connection metadata.
Subscriptions and the VAPID private key are encrypted in the existing remote DB.
Only trusted devices can subscribe; disabling remote access or revoking trust
prevents subsequent delivery attempts. Messages already handed to a provider cannot
be recalled. Public Internet exposure of MARK LIV is not required.

Keep the PC awake, running and connected to the Internet. Notifications can arrive
while the page is closed, subject to browser/OS policies. Reading their private
details requires Tailscale connectivity and device trust. A provider accepting a
message is not proof that the phone displayed it; delivery status says so.
Explicit 429/5xx refusals retry at most three times. Ambiguous network timeouts and
crash-interrupted attempts are not replayed because delivery might already have
occurred. The saved inbox remains the authoritative result history.

## Validation and remaining work

Tests exercise real Web Push encryption/VAPID signing with a mocked network transport,
subscription encryption, provider allowlisting, bounded retries, expiry, revocation,
unsubscribe, and signed audio tickets/PCM/interruption. Browser validation uses
synthetic audio and temporary identities. Actual closed-app phone delivery and live
cloud reply playback on a physical phone require an owner-device check.

This phase implements phone playback and notification delivery. Project repair with
reviewed diffs, resumable workspaces, cited personal knowledge and expanded bilingual
or local inference remain separate upgrades; they are not claimed complete here.

References: [Web Push library](https://github.com/web-push-libs/pywebpush),
[browser subscription API](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe).

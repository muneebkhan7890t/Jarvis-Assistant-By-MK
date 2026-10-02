# Remote Command Center — implementation and setup

These are the implemented stages of the September 2026 remote-control
request. It is integrated with MARK LIV's existing action registry, permission
manager, live assistant, project records and job store. The complete requested
remote-control product is **not yet implemented**.

## Available now

- Mobile `/remote` interface: Computer, Chat, Commands, Screen, Files, Projects,
  Workflows, Automations, Jobs, Notifications and Devices. The root URL opens this interface by default.
- [Reviewed project commands](REMOTE-PROJECTS.md): fixed PC-approved tasks and
  development servers, bounded logs, cancellation, workflow execution, automation
  controls and a durable device-scoped notification inbox.
- Browser-generated P-256 identity. Its private key is non-exportable and retained
  in IndexedDB in that browser profile. A pairing code only requests enrollment;
  it never grants device trust. The PC owner compares the complete SHA-256
  fingerprint and grants individual permissions in **Remote Devices**.
- Per-request signatures bind device ID, HTTP method, path, exact body hash and a
  one-use, 30-second server nonce. Replays, modified bodies, mismatched keys,
  expired challenges and revoked/untrusted devices are rejected.
- Persistent trust, last-seen timestamps, PC-wide feature switches, individual
  device capabilities, revocation/removal and read-only shared-folder selection.
- Local English/Roman Urdu command aliases call the real PC action registry.
  These work without Gemini Live. Only permitted LOW-risk actions are accepted;
  settings such as Deny/Ask remain authoritative. Common examples: open calculator,
  open Chrome, volume down, volume kam karo, mute, lock pc and system status.
- Live CPU/RAM/battery readings; explicit screen captures (bounded JPEG, no saved
  screenshot file); read-only folder browsing/downloads limited to configured
  roots and 10 MB. Traversal, absolute paths, alternate streams, links/junctions
  and selected credential/database file patterns are refused. Folder selection
  is the primary boundary; filename filtering cannot identify every secret.
- Durable, device-scoped command receipts with stable request IDs. Retrying the
  same request cannot duplicate execution. A different command using an old ID
  is rejected. Disconnecting the browser does not stop the PC worker.
- Signed Chat requests enter the existing Live assistant queue. The phone can
  view its shared conversation transcript. Chat requires an online PC cloud
  session; new offline messages are rejected instead of silently queued.
- Opt-in phone microphone via AudioWorklet, 16 kHz PCM and WSS. A signed request
  issues a one-use 30-second connection ticket. Only one phone microphone connects
  at once; streams have a 15-minute maximum, bounded frames/queues, per-second
  limits and repeated revocation/master-switch checks. Leaving/hiding the phone
  page stops capture. The PC logs microphone start/stop and screenshot requests.
  Audio reaches the existing Gemini Live relay; replies play on the PC and text
  appears on the phone. Opt-in [phone playback and background alerts](PHONE-REPLIES-AND-ALERTS.md)
  are now available; playback requires Voice and Chat permission and foreground Chat.

## Important current boundaries

The current Gemini Live conversation is shared with the PC. Once remote chat or
voice claims it, its model tools remain limited to that device's permitted LOW-risk
commands until MARK LIV restarts. This deliberately prevents a shared conversation
from mixing device privileges or bypassing Files/Screen scopes. It also restricts
model tools requested at the PC during that session. Direct PC controls remain
available. A second phone cannot claim that assistant session until restart.
Separate simultaneous PC/phone assistant sessions need further implementation.

Chat permission shares the existing PC assistant conversation, including PC-side
utterances; it is not an isolated private chat. Voice sends microphone audio to
the configured cloud assistant. The PC mute control still controls the existing
audio relay. Camera capture is not added or enabled.

Legacy action handlers return prose, not independently verified outcomes. Their
receipts are marked **returned / unverified**, never automatically “completed.”
On PC service restart, orphaned queued/running records are marked failed with
unknown outcome and are not replayed. A pending approval is not completion.
Revocation stops new work and subsequent stream frames; it cannot undo an action
or recall data already delivered.

The old bearer-token dashboard is disabled by default, including its login, file,
project and WebSocket routes. `legacy_remote_enabled=true` is an explicit
compatibility escape hatch and should remain off for the new owner-device model.
Old device tokens do not grant access to the signed interface.

## Private access away from home

Tailscale was found installed and connected on the development PC. This work has
not changed its Serve configuration, firewall, router or remote-access switches.
No real phone or mobile-data session has been validated.

1. Connect the PC and owner phone to your private Tailscale network. The PC must
   remain awake, online and running MARK LIV. Review tailnet access rules.
2. In MARK LIV's **Remote Devices**, enable remote access and the specific
   features you want. Leave LAN access off. Restart MARK LIV to start its
   loopback-only HTTPS listener. Enable pairing only while adding a device.
3. Inspect `tailscale serve status` before changing an existing configuration.
   For a PC without a conflicting Serve listener, the documented private HTTPS
   proxy command is:

   ```powershell
   tailscale serve --bg https+insecure://127.0.0.1:8000
   ```

   Serve provides the trusted HTTPS origin needed by WebCrypto and microphone
   access. The `https+insecure` option skips verification of MARK LIV's
   self-signed certificate **only on the loopback backend connection**. Phone
   traffic still uses HTTPS and the private network. Use Serve, not Funnel.
   Do not forward router ports 8000/8001, SSH, RDP or VNC.
4. Save the HTTPS origin displayed by Tailscale in **Remote Devices → private
   address**. Do not include a path. This makes the existing Remote Control QR
   open `/remote`; its one-use pairing code travels in a URL fragment and is
   immediately removed from browser history by the page.
5. Scan the QR, name the phone, request trust, then click Refresh on the PC's
   device list. Compare the entire fingerprint on both screens, select the
   device permissions and trust it. Click **Connect after PC approval** on the
   phone. Turn off new pairing afterward.
6. Test Computer status first, then a harmless command, then test again using
   mobile data with Tailscale connected. Open Jobs to inspect its receipt.

Official connection references:
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
[Serve CLI and HTTPS backend syntax](https://tailscale.com/docs/reference/tailscale-cli/serve).
Browser microphone requirements:
[getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Storage and privacy

`memory/remote.db` holds public device metadata and encrypted command/result
payloads, approved project profiles and notification contents. The Fernet
encryption key in `memory/remote.key` is protected with
Windows DPAPI for the current Windows account. Both files are excluded from Git
and the release allowlist. On non-Windows systems the key uses a mode-0600 file;
that fallback is not equivalent to Windows DPAPI. Losing the key/account makes
old receipts unreadable; no insecure key-regeneration fallback is provided.

This protects copied receipt payloads, not a compromised running Windows account.
Device names/public keys/timestamps/statuses are metadata, not encrypted fields.
Browser profile deletion removes the phone key and requires new pairing. A
non-exportable key is not biometric authentication: anyone able to use that
unlocked browser profile can use its granted permissions. Keep the phone locked.
Use a stable HTTPS origin, because browser identity storage is origin-specific.

## Remaining requested phases

| Requested area | Current state |
| --- | --- |
| Physical phone + mobile-data validation | Pending phone setup and testing |
| Closed-app push, call-style alerts and notification priorities | Saved inbox and opt-in generic Web Push implemented; physical delivery unverified and call-style alerts pending |
| Email OAuth, trusted contacts, send/reply | Not implemented; provider/account/contact setup needed |
| Existing-project build/test/server/git controls and durable developer-agent fixes | Reviewed fixed commands and owned task/server processes implemented; dedicated Git review and agent repair remain pending |
| Workflow and automation execution/editors | Saved low-risk workflow execution and automation enable/disable/run implemented; definition editing remains on PC |
| File upload/write/analyze-latest-PDF | Read-only browse/download implemented; remaining controls not implemented |
| Remote mouse/keyboard and low-FPS streaming | Capture-on-request only; input/streaming not implemented |
| Critical phone confirmation with PIN/biometrics | Not implemented; sensitive remote model tools fail closed |
| Shutdown/restart, smart home and Wake-on-LAN | Not added to the new remote interface |
| Multiple PCs, isolated concurrent assistant sessions | Not implemented |
| GPU/temperature/port watchers and durable push notifications | Not implemented in the new remote interface |
| Phone audio replies/background speech | Opt-in reply playback implemented; microphone and playback require foreground Chat |

## Validation

Unit/API tests exercise actual signatures, modified/replayed requests, expiry,
trust/revocation, capability switches, safe folder boundaries, encrypted durable
receipts, duplicate commands, restart recovery, chat scope restrictions, voice
ticket replay/revocation, strict policy dispatch and legacy-route isolation.

`scripts/validate_remote_ui.py` uses a temporary loopback HTTPS server, temporary
keys and mocked PC actions. It tests a real headless Edge browser at phone width:
pairing, WebCrypto signatures, explicit PC trust, command receipts, IndexedDB
reconnection, revocation, a real temporary Python task, workflow/automation controls
and saved notifications. Microphone testing uses Edge's **fake media device**;
it never opens the real microphone or connects to Gemini. UI screenshots go to
the excluded `validation/` folder. Tests do not prove physical-phone compatibility,
cloud speech recognition, Internet reachability or absence of all security defects.

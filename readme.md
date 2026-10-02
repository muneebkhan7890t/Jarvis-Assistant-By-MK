# Jarvis Assistant By MK

**A voice-controlled desktop AI assistant customized by MuneebKhan, built on the MARK LIII / JARVIS project by FatihMakes.**

Jarvis combines live voice conversations, desktop tools, personal productivity, reviewed automation, a private phone companion, and read-only crypto market analysis. This edition is developed and tested primarily on Windows. It is an application running on your operating system, not a standalone operating system.

## Features

| Area | Available functionality |
| --- | --- |
| Voice assistant | Gemini Live conversations, wake/sleep behavior, microphone controls and a desktop HUD |
| Desktop tools | App launching, browser tools, file tools, system controls and on-demand screen/camera context, subject to permissions |
| Productivity | Tasks, searchable notes, reminders, repeat schedules, snooze and project records |
| Continue my work | Encrypted local checkpoints, next steps and reviewed reopening of saved folders, apps and pages |
| Workflows and automation | Saved workflows, conditions, enable/disable controls, manual runs and runtime status |
| Project development | Persistent generation jobs, status, cancellation and reviewed project tasks; generated code requires a configured container to execute |
| Phone companion | PC-approved signed device pairing, per-device permissions, chat/microphone, screen capture, scoped read-only files and command receipts |
| Phone alerts | Optional speaker playback, notification inbox and opt-in Web Push for future remote task results |
| Market news | Startup crypto and gold headlines with dated sources |
| Market analysis | Public BTC/ETH candles across daily, 4-hour, 1-hour and 15-minute frames; illustrative conditional setups or a no-setup result |
| Action approvals | Central permissions, sensitive-action review and optional expiring voice codes for eligible local actions |
| Extension support | Discoverable Python actions and plugins |

## Install on Windows

Use Python 3.11 or newer; development validation used Python 3.12.4. Clone or download this repository into a permanent writable folder.

For one-click setup, run **Setup Windows.cmd**. It installs dependencies, creates a desktop shortcut and enables sign-in startup. Alternatively, use PowerShell in the repository root:

```powershell
python -m venv .venv-liv
.\.venv-liv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-liv\Scripts\python.exe -m playwright install chromium
.\.venv-liv\Scripts\python.exe launch.py
```

Enter your own Gemini API key in the setup screen, or configure `GEMINI_API_KEY` in your environment. Cloud features require internet and may incur provider charges. Optional OS credential storage uses `requirements-secrets.txt`; Web Push uses `requirements-push.txt`. See the installation guide before enabling optional features.

Local deterministic text commands can run in offline mode. Full offline speech recognition, speech synthesis and local-model failover are not integrated. Linux/macOS compatibility has not been validated for this customized edition; several upgraded features use Windows-specific facilities.

## Try it

- ?Open calculator.?
- ?Show my tasks.?
- ?Continue my work.?
- ?What is the status of my project??
- ?Give me a Bitcoin trade setup.?

When an eligible action presents a voice code, say **?Jarvis confirm [code]?** or **?Jarvis cancel [code]?** exactly. The option must be enabled in Privacy settings. Codes expire after 90 seconds and are tied to a pending action. Generic ?yes? does not authorize an action. This is not speaker identification; anyone audible to the local microphone with the code may respond. Destructive and critical actions retain desktop confirmation.

## Phone access

Remote access is off by default. Enable only the features you need, pair your phone, approve it on the PC and grant its scopes. Follow the current [Remote Command Center guide](docs/REMOTE-COMMAND-CENTER.md) for private Tailscale access and device management. Do not expose an unauthenticated assistant to the public internet. Phone voice does not approve local voice-code confirmations.

## Market analysis limitations

The analysis tool reads public market data; it has no broker login, account access or order execution. BTC/ETH watchlists use an illustrative EMA trend and breakout method, not a validated profit-prediction system. Missing, stale or unaligned data can produce ?no setup.? Gold numerical analysis requires appropriate chart data or a read-only gold provider. News alone is not a numerical trade setup. Live spread, economic events, account risk and position sizing require additional checks.

## Privacy and permissions

Use Controls to review Permissions, Privacy and Activity. Cloud voice and enabled external services can receive data needed for the requested feature; this is not an entirely local assistant. On-demand screen/file tools can transmit content when enabled. See the security documentation for boundaries and remaining risks.

This source distribution excludes personal configuration, API keys, conversation memory, databases, encryption keys, certificates, browser sessions, logs and virtual environments. Keep these files private. The upstream project previously included a key; if you used that old key, replace it with your own and rotate it where applicable. No claim of a complete independent security audit is made.

## Documentation

- [Installation and migration](docs/INSTALLATION.md)
- [Implementation status and remaining work](docs/IMPLEMENTATION_REPORT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security](docs/SECURITY.md) and [permissions](docs/PERMISSIONS.md)
- [Tasks, notes and reminders](docs/PRODUCTIVITY.md)
- [Automation Manager](docs/AUTOMATIONS.md)
- [Continue my work](docs/CONTINUE-WORK.md)
- [Remote Command Center](docs/REMOTE-COMMAND-CENTER.md)
- [Remote projects](docs/REMOTE-PROJECTS.md)
- [Phone replies and alerts](docs/PHONE-REPLIES-AND-ALERTS.md)
- [Crypto/gold briefing](docs/MARKET-BRIEFING.md)
- [Market analysis and voice confirmations](docs/MARKET-ANALYSIS-VOICE.md)
- [Validation evidence](docs/VALIDATION-LIV.md) and [changelog](CHANGELOG-LIV.md)

## Development and validation

```powershell
.\.venv-liv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv-liv\Scripts\python.exe scripts/health_check.py
.\.venv-liv\Scripts\python.exe scripts/build_release.py
```

The last recorded Windows regression run passed **168 tests**. Windows encryption tests need the normal user account context. Physical phone push delivery and actual microphone confirmation still need end-to-end user validation. Automated checks do not establish that every hardware, cloud or remote configuration works.

The release builder creates an allowlisted source archive under `dist/`. Do not distribute your live working directory. Generated projects require an explicitly configured Docker image; there is no silent host-execution fallback.

## Roadmap

Possible future work includes a tested Linux port, offline speech/model integration, a dedicated desktop shell, additional market-data providers and stronger authenticated approvals. These are not delivered features. A custom bootable operating system and automated trading are not implemented.

## Credits and license

Customized edition: **MuneebKhan (MK)**. Original MARK LIII / JARVIS project: **FatihMakes**. [Original creator resources](https://www.youtube.com/@FatihMakes).

The original copyright and **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** license are preserved in [LICENSE](LICENSE). Public availability does not remove the noncommercial license restriction. Retain attribution when redistributing or adapting the project.

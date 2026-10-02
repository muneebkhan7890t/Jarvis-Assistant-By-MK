# MARK LIV setup and migration

Use Python 3.11 or newer (tested here with 3.12.4). Run from the folder
containing `main.py`, not its outer download directory.

## Windows PowerShell

```powershell
python -m venv .venv-liv
.\.venv-liv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-liv\Scripts\python.exe -m playwright install chromium
# Optional OS-backed credentials:
.\.venv-liv\Scripts\python.exe -m pip install -r requirements-secrets.txt
$env:GEMINI_API_KEY = Read-Host 'New Gemini API key'
.\.venv-liv\Scripts\python.exe main.py
```

Environment credentials take precedence, followed by OS keyring, then private
`config/api_keys.json`. The existing setup screen can save credentials. Without
a usable OS keyring it warns and falls back to the ignored local JSON file.
`Read-Host` above is an interactive input, not a literal key to commit.

The existing `Setup Windows.cmd` remains available. It installs dependencies,
creates a shortcut and enables autostart; the manual commands above do not.

## macOS / Linux

```sh
python3 -m venv .venv-liv
.venv-liv/bin/python -m pip install -r requirements.txt
.venv-liv/bin/python -m playwright install chromium
.venv-liv/bin/python main.py
```

Set `GEMINI_API_KEY` using your shell/session secret mechanism. OS audio/input
permissions and existing platform tools still apply. These platforms were not
exercised in this Windows validation run.

## Offline text mode

Set `assistant_mode` to `offline` in the Privacy panel and restart. For first
launch without a key, create `config/api_keys.json` containing:

```json
{"assistant_mode": "offline"}
```

Supported deterministic text commands include `open calculator`, `open chrome`,
`volume down`, `brightness up`, `lock pc`, `show battery` and
`Jarvis Chrome open karo`. Local text commands also work while Live reconnects.
Offline voice recognition/TTS and automatic local-LLM failover are not integrated.

## Phone

Enable Remote control, Allow LAN clients and Allow new device pairing in the
Privacy panel; restart. Press the existing Remote Control button to pair. The
service generates a fresh self-signed device certificate. Verify the local
machine and certificate before accepting a browser warning. This is TLS, not a
publicly trusted certificate. No automatic firewall modification is made by the
runtime. Session tokens expire after one hour; device tokens expire after 30 days
and rotate on reconnection. Pairings are in memory and reset on process restart.

## Generated projects

Host execution and host dependency installation are disabled for generated code.
Install/configure Docker yourself and prepare an image containing Python and the
project dependencies. Set `developer_sandbox_image` to that local image name in
private configuration. The runner never pulls images automatically. It supports
`python relative_script.py`, with no network, read-only project mount, unprivileged
container user, capability drop and CPU/memory/process/time limits. A missing
container runtime produces a needs-review job with the generated files retained.
Docker is not installed in the validation environment; no container execution
was claimed. A virtual environment alone is not a sandbox.

## Validate and release

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -v
python scripts/health_check.py
python scripts/build_release.py
```

The release is `dist/MARK-LIV-source.zip`. Rebuild with the script; do not zip the
working directory. Requirements pin top-level versions observed in the validation
environment. They are not a transitive, hash-locked dependency set.

## Migration

Back up private configuration and memory outside any release folder. Legacy fact
entries, SQLite notes/tasks/jobs and plugin entry points remain compatible.
Memory metadata is added when an entry changes. Identity, project and pinned
memories survive storage trimming. Workflow/project records are local-only.

Tasks/notes metadata columns and reminder/history tables are added transactionally
to the existing `memory/productivity.db` on first use. IDs and existing content are
retained. Keep the database backup with your private data. Old native reminders
remain installed but cannot appear in the new manager because the earlier version
did not persist their IDs. See [productivity and reminder migration](PRODUCTIVITY.md)
before moving the project or replacing an existing scheduled reminder.

The bundled API key and reusable TLS pair were removed. Rotate the previously
bundled key with its provider; deleting a key from source does not revoke it.
New remote/privacy defaults are deliberately off. High-risk actions now require
an on-screen click, even if a model supplies `confirmed=true`. Legacy desktop
Python outside the bounded grammar and non-Python generated execution now return
an explicit restriction instead of executing unsafe code.


## Existing environment repair

The bundled `.venv` in this working copy points at an inaccessible Python 3.14
installation. It is preserved, but the Windows setup/launcher now prefer
`.venv-liv` and test the interpreter instead of only checking whether an EXE exists.
For this development workspace, `.venv-liv` was created with Python 3.12 and
`--system-site-packages` to reuse already installed, tested dependencies without
network installation. A fresh setup uses the ordinary isolated venv commands above.
Run Setup Windows.cmd again to update an existing autostart/shortcut registration;
this upgrade did not modify your Windows startup registry itself.

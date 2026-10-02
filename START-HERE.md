# Your updated JARVIS assistant

## Install once, then open with one click

1. Extract the ZIP into a permanent, writable folder, for example
   `Documents\JARVIS`. Do not run it from inside the ZIP.
2. Install Python 3.11 or newer if it is not already installed. Python 3.12 was
   used for the automated tests.
3. Double-click **Setup Windows.cmd**. The first setup downloads dependencies
   and a browser, so it needs internet and may take several minutes.
4. Setup creates **JARVIS Assistant** on your desktop and enables startup when
   you sign in to Windows. It then opens the assistant. Enter your Gemini key.
5. Afterwards, use the desktop shortcut or **Start Jarvis.vbs**. Dependencies
   are already installed; launching does not repeat installation.

Windows setup has been supplied, not executed on your PC by this update. It
registers startup only when you run it. Keep the extracted folder in place; if
you move it, rerun setup to update the shortcut and startup path.

This uses a native Windows app because it needs your desktop, microphone, camera
and audio devices. No Docker is required. It appears **after Windows sign-in**,
not on the lock screen before sign-in. A Windows single-instance guard prevents
two copies competing for your microphone. Disable startup from the app settings
or run **Disable Autostart.cmd**.

If it will not open, check `logs/assistant.log`. Logs rotate instead of growing
without limit. Setup stops and shows errors if a download or installation fails.

## The project-forgetting fix

Previously, project generation was awaited from inside the live audio receive
loop. There was no durable job record for the assistant to consult after an
unrelated conversation or a new session. Spoken promises were not proof of work.

Now a project request starts a separate background worker and saves its request,
job ID, exact folder, progress and result in `memory/jobs.db`. The tool returns
immediately so you can continue talking. The assistant is instructed to query
saved jobs before answering questions about previous work.

Try this sequence:

1. "Build an object detection project in Python."
2. Wait for the returned job ID and folder.
3. Ask unrelated questions.
4. "What is the status of my object detection project?"
5. "Where did you save that project?"

Other useful commands:

- "List my project jobs."
- "Cancel that project build."
- "Retry the interrupted object detection project."

Folders are allocated under `Desktop\JarvisProjects` in your Windows user
profile, with a unique suffix. The returned path is authoritative, including on
machines where the desktop is redirected by OneDrive.

The states are queued, running, completed, needs_review, failed, cancelled and
interrupted. Completion notifications appear in the PC log and phone dashboard;
the assistant speaks an update when the live session is available and idle.
An exit without a detected error is reported as that, not a guarantee that all
generated application features work. A timeout requires review.

Only one project build runs at a time. A second request reports the active job
instead of silently replacing it. Cancelling takes effect at the next checkpoint;
an API call or subprocess already in progress can delay cancellation. Closing
the assistant stops its worker. On next launch the job is marked interrupted,
its files remain, and you can explicitly retry into a new folder. It does not
silently rerun commands or claim that it resumed.

Jobs from older versions cannot be reconstructed from a spoken promise. Existing
project files remain where the previous assistant saved them, but only new builds
have job records. The model must still call the build tool; the new phone BUILD
button starts it directly if you want to avoid conversational ambiguity.

## Link your phone and control your PC

1. Start JARVIS on your PC and put the phone on the **same private Wi-Fi/network**.
2. On the PC, open settings and choose **REMOTE CONTROL**.
3. Scan its QR code with your phone, or use the displayed address and pairing key.
4. The dashboard uses a locally generated HTTPS certificate. Your browser may
   show a certificate warning for that local PC address. Verify that the address
   matches the PC's pairing screen before continuing. Pair again after a PC app
   restart; pairing tokens are intentionally kept in memory.
5. On the phone, use the **PC projects & battery** section to build projects,
   inspect saved progress and folders, cancel, or retry. Use the message box below
   it for commands such as "open calculator", "set volume to 30 percent", or
   "show my task list". The existing file-upload and microphone controls remain.

If Windows Firewall asks, allow the app on **Private networks**. The dashboard
uses TCP port 8000, plus 8001 for the existing alternate address. This update
does not automatically elevate or rewrite firewall rules. If the QR address is
wrong because you have several network adapters, use your PC's Wi-Fi IPv4 address
with `https://` and port `8000`.

Phone text commands require an online voice-assistant session. When it is
reconnecting, the phone reports an error instead of silently losing a command.
Project status remains readable, and direct project builds use the configured
Gemini key independently of the voice connection. The PC must remain powered on,
awake and running JARVIS; this does not wake a powered-off PC. Actions that already
require confirmation still require the PC's confirmation button.

This is local-network control, not an internet remote-desktop service. Do not
forward these ports to the public internet. Phone microphone support depends on
the browser accepting the secure connection and microphone permission; text
input remains available. Mobile-data/outside-home access is not configured here.

## Low-battery announcements

The app checks about every 10 seconds. While unplugged, it warns at **20%** and
escalates at **10%**, for example: "Sir, your battery is low at 20%. Please connect
your charger." Repeat warnings are limited to once per 15 minutes. Plugging in
suppresses warnings; desktops without a battery are handled normally.

Alerts show in the PC log and connected phone dashboard. Spoken alerts wait for
a pause in conversation. If the cloud session is offline or sleeping, Windows
local speech is attempted through the existing pywin32 dependency. Muting the
assistant suppresses speech; the warning remains visible. Windows speech voice
and pronunciation depend on the voices installed on your PC.

## What was tested

Automated tests cover durable/background jobs, querying while a worker is busy,
failure and interruption, explicit retry, cancellation, generated-path boundaries,
timeout/nonzero-exit handling, battery thresholds and cooldown, phone authentication,
offline command errors, and project API dispatch. Earlier task-list and notes tests
are retained. The tests use mocked cloud calls and temporary folders.

Run tests after installing requirements:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Live Gemini conversation, a real object-detection build, your physical phone,
microphone, Windows speech output and an actual Windows reboot were not tested.
The scripts provide setup and startup registration; no startup-time guarantee
is possible before testing your computer and network.

The previous task-list and searchable-notes features are still included; see
`IMPROVEMENTS.md` for their commands. Private API keys, memory, jobs and certificates
are not included in the downloadable ZIP. Back up your own `memory` folder before
replacing an existing installation.

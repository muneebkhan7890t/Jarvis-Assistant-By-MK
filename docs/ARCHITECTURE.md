# MARK LIV architecture map

## Inspected baseline

The source has 55 Python modules plus a Qt desktop UI, FastAPI phone UI,
PowerShell/VBS launchers and two unittest suites. `main.py` owns Gemini Live,
audio queues, session recovery, tool dispatch and background watchers. `ui.py`
owns the Qt HUD, setup, settings, camera, memory, clipboard, plugins and the
human confirmation banner. Both remain compatible entry points.

`core/action_loader.py` discovers `TOOL` handlers in `actions/`;
`core/plugin_loader.py` discovers trusted local Python plugins, resolves name
collisions and observes enable flags. Actions cover applications, computer
settings, desktop input, files, documents, messaging, browser, search, media,
reminders, notes, tasks and developer jobs. They are not independent services.

`memory/config_manager.py` resolves environment/local configuration;
`memory/memory_manager.py` stores categorized facts and session summaries.
`core/productivity_store.py` and `core/jobs.py` use SQLite for notes/tasks and
asynchronous cancellable build jobs. `core/undo.py` stores reversible closures;
`core/confirm.py` binds irreversible operations to the trusted Qt banner.

`dashboard/server.py` serves the phone UI and relays authenticated text/PCM;
`dashboard/project_api.py` also invokes developer actions directly. These are
separate entry points that must share authorization. `core/dashboard_tls.py`
already generates device certificates. `core/stt.py`, `core/tts.py` and
`core/llm_client.py` contain optional local providers, but the primary runtime
is a Gemini Live loop. Existing local providers are not full offline failover.

## Upgrade boundaries

Extend discovery and dispatch; retain action signatures. Enforce policy before
handlers, including direct phone project actions. Never expose UI approval as a
tool. Local routing reuses those same registries. Optional engines import heavy
dependencies only when used. Runtime state and user data are excluded from the
source release by an allowlist packager.

Python plugins are trusted code with host privileges, not a sandbox. A virtual
environment is dependency isolation, not a security boundary. Generated desktop
instructions need an AST allowlist and bounded interpretation; generated full
projects require an external process sandbox before automatic execution is safe.


## Current source layout

```text
main.py, ui.py, launch.py          Existing runtime and HUD entry points
core/
  permission_manager.py         Policy and argument-bound dispatch
  confirm.py, undo.py           Trusted UI gate and existing undo
  intent_router.py              Local text intent matching
  event_bus.py, diagnostics.py  Events, timing and action audit
  control_panel.py              Extracted desktop management pages
  productivity_panel.py        Async Qt Tasks, Notes and Reminders editors
  productivity_store.py        Compatible SQLite migration, metadata and undo
  reminders.py                 Persistent schedules, generations and history
  sandbox.py                   Bounded desktop instruction interpreter
  project_sandbox.py           Generated Python container execution
  archive_safety.py            Safe extraction
  context_engine.py            Temporary machine/app snapshot
  workflows.py                 Semantic recorder/player
  automation.py                Local state rules
  automation_panel.py          Visual rule editor and runtime status
  project_memory.py            Separate project metadata
  remote_security.py           Rate limiting/origin/upload helpers
  action_loader.py              Discovery and enabled built-in skills
  plugin_loader.py              Existing Python plugin compatibility
  ...                           Existing audio/voice/LLM/jobs/productivity
memory/                         Existing compatible storage adapters
config/                         Example configuration; runtime state ignored
workflows/                      Created when the user saves a workflow
plugins/                        Trusted user Python plugins
```

The `actions/` package retains the original tools and adds `memory_control`,
`project_memory`, `computer_context`, `workflow_manager` and
`automation_manager`. `dashboard/` retains its HTML/JavaScript companion and
FastAPI server. `scripts/` provides release and health checks, `tests/` contains
regression and Qt integration suites, and `docs/` describes setup, security,
permissions, productivity migration and phase status.

Reminders share the existing productivity database. `actions/reminder.py` retains
the OS adapters; native scripts call the persisted state machine. SQLite serializes
delivery claims, and every edit/cancellation invalidates the old generation. A
notification interrupted after its claim is not replayed automatically because
delivery may already have happened. Recurrence registers the next native job after
successful delivery. Only the trusted desktop UI and existing permission-gated
action paths create or change schedules.

Automation definitions remain in `config/automations.json`; no second rule store
was introduced. The visual editor and model tool share the same validation,
revision checks and execution claims. Actions run outside the engine lock and
outside the GUI thread, through the existing permission-gated registry. Polling
checks the background-monitoring opt-in between rules. Runtime snapshots are
detached copies; periodic UI refresh preserves unsaved edits. Activity events
record the action/source/outcome without notification text or parameter contents.

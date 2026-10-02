# Automation Manager

Open **Controls > PERMISSIONS / PRIVACY / ACTIVITY > Automations**. The visual
editor uses the existing `config/automations.json` store and engine.

## Create and manage a rule

1. Click **New** and enter a name. New rules in the UI start disabled.
2. Set the first **WHEN** row and optionally add **AND** conditions. Select an
   additional row's header to remove it. Every condition must match.
3. Choose how long the conditions must remain true and a cooldown between runs.
4. Choose a notification, application, computer status, or a safe computer setting.
   Use Advanced action only for another registered low-risk tool and its parameters.
5. Save, then enable the rule when ready. Enabling Background monitoring in Privacy
   starts automatic checks while JARVIS runs, normally about every five seconds.

The form scrolls to expose action details on smaller windows. Select a saved rule
to edit it. **Save** applies edits, **Enable / disable** changes its saved enabled
state, and **Delete** removes the definition. Periodic status refresh preserves
unsaved edits. The **Refresh** button explicitly reloads the selected saved record.
If another editor or tool changes the rule, stale saves are rejected.

**Run now** uses the saved definition, skipping its conditions and hold duration.
It requires the rule to be enabled and honors the cooldown, skill settings and
action permissions. It works while background monitoring is off because it is an
explicit one-time request. Save form changes before using Run now.

## Conditions and timing

- Battery, CPU and RAM: numeric percentages from 0 to 100; less than, greater than,
  or equals.
- Charger and network-interface state: equals `true` or `false`. Network state is
  an interface-up check, not proof of internet connectivity.
- Foreground process: equals the exact process name. This context is currently
  supplied on Windows; it does not monitor all process starts or detect crashes.

A rule fires once while its conditions remain true. They must stop matching
before another automatic run, and cooldown still applies. A failed action does
not retry on every poll while the same trigger remains true. Editing or toggling
a rule resets its partial hold duration but retains its session cooldown.
Pausing background monitoring resets partial durations. Turning it off during a
batch stops remaining rules; an already executing action is not forcibly killed.

The next-check time is an estimate. Long actions can delay the next poll. Current
states, last run, cooldowns and errors are session-only; rule definitions persist
across restarts. Restarting can trigger an enabled rule whose conditions match.

## Results, permissions and privacy

Notifications appear in the JARVIS activity log. They are not native OS reminders;
use the Reminders page for alerts that should run while JARVIS is closed.

The selected rule shows trigger state and its most recent result or error.
`returned` means the handler returned text; it does not independently prove an
external action succeeded. `blocked_or_failed` and `error` expose recognized
denials/failures. `confirmation_requested` records that a desktop approval was
requested, not that the action completed. Resolve that request in the HUD and
check Activity for the eventual action result. Disabling/deleting a rule does
not dismiss a previously displayed approval; cancel it separately in the HUD.

Only low-risk tools and local notifications can be saved. Saved definitions are
validated again when read and executed. File edits cannot turn a rule into an
unchecked terminal, messaging or destructive action. Every registered action
still passes through the existing permission manager. The trusted desktop button
is an explicit user request; model-driven rule changes require the existing
automation-management approval.

Invalid rule files fail closed and are not silently overwritten. Valid legacy
rules load with revision zero; subsequent edits gain revision numbers. Keep their
generated IDs when editing; omit the ID to create a new rule. Up to 200 rules and
a 1 MiB definition file are supported. The private file and temporary write file
are excluded from Git/release packaging. Activity audit entries exclude rule
text and parameter contents; the local rule file itself contains plaintext data.

Filesystem/download/headphone/crash event adapters, future-event prediction,
persistent run history and interruption of arbitrary blocking tools remain
unimplemented. Automated tests use temporary files and controlled dispatchers;
no new monitoring or real computer actions were enabled during development.

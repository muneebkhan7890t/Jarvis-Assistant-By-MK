# Tasks, notes and reminders

Open the HUD Controls drawer, then **PERMISSIONS / PRIVACY / ACTIVITY**. The
management window now includes **Tasks**, **Notes** and **Reminders** tabs.

## Tasks and notes

Click **New**, enter the fields and **Save**. Select a row to edit it. Tasks support
priority, due date, project, tags, completion/reopening and archive/restore. Notes
support searchable content, categories, tags, projects and pins. Search includes
titles, content and metadata. Created date and revision appear below a selected
record. The status filter exposes completed or archived records.

Task due dates are labels; use Reminders to schedule notifications. Tags are
comma-separated in the editor. **Undo last change** uses the assistant's shared,
session-only undo stack (up to ten operations); hover over it to see the last
operation. It can undo a change from another tab or tool. An undo refuses to
overwrite an item whose contents changed subsequently. There is no durable undo
history across app restarts.

The existing `notes` and `task_manager` tools expose editing and metadata to the
voice assistant. `list tasks`, `list notes` and `list reminders` are also local
text commands. Free-form voice creation still uses the existing Gemini Live
connection; this addition does not supply offline speech recognition.

## Managed reminders

Use a future date (`YYYY-MM-DD`) and time (`HH:MM`) in the computer's local timezone.
Select none, daily, weekly or weekdays for repetition. Weekly repeats follow the
weekday of the initial date. Snooze reschedules from now by the selected number
of minutes. For repeating reminders, subsequent occurrences follow the snoozed
time. **Complete** and **Cancel reminder** both stop further repeats, with distinct
states in history. **History** shows the selected reminder's latest 100 events,
or the latest 100 events overall when nothing is selected.

All new reminder IDs, generations, due times and outcomes persist in
`memory/productivity.db`. Updates disable the previous generation before native
cleanup, so a stale OS job cannot deliver a cancelled reminder. Duplicate native
invocations share an atomic delivery claim. A failed replacement registration
restores the previous schedule if it is still pending and in the future.

The existing adapters use Windows Task Scheduler, macOS launchd, or Linux user
systemd timers with an `at` fallback. They require the corresponding scheduler,
notification service and user session. They can run while JARVIS is closed; they
do not guarantee delivery while the PC is off or the user is logged out. Windows
requests a catch-up run when available. Missed repeat intervals are skipped after
the next successful delivery rather than emitting every missed notification.

Minute-resolution native timers are guarded against early delivery, including
snoozes with nonzero seconds. Local wall time is used when calculating the next
repeat. A timezone change does not rewrite an already registered OS job; edit
pending reminders after changing the computer timezone. Keep the project,
database and interpreter paths available until their reminders finish.

“Delivered” means the notification backend accepted the request, not that the
user read it. Failed notification/registration states remain visible. On startup,
jobs interrupted in scheduling/delivery for over five minutes are marked failed,
not replayed automatically; inspect History and snooze to retry. Do not retry a
possibly delivered reminder automatically. Native completed job entries may remain
in the OS scheduler, but their generation/state prevents duplicate delivery.

## Migration and privacy

Back up `memory/productivity.db` before upgrading. The migration adds columns
and tables in a transaction; it preserves existing task/note IDs and contents.
New reminder scripts load their message from the database rather than embedding
the message in generated source. The database contains private plaintext content
and is excluded from source releases.

Older reminders had unique native job names but no database records. They remain
scheduled and will not appear in the new manager. Manage those entries in the OS
scheduler; replacing one in the new UI without removing the old job could create
two notifications. No old jobs are removed or silently guessed during migration.

Testing uses temporary databases, mocked native registration/notifications, and
real offscreen Qt editors. Actual notification display, logged-out behavior, and
fresh macOS/Linux scheduling have not been verified in this workspace.

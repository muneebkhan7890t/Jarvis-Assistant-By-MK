# Continue my work

Save a work checkpoint with a project folder, what you completed, where you stopped,
next steps, selected apps and up to eight HTTPS pages. Reopen the chosen items after
reviewing an exact plan. This feature works locally without a cloud conversation.

## Use it

1. Click **CONTINUE WORK** in MARK LIV's header, or type **continue my work** into
   its text command box. `resume my work` and `mera kaam jari rakho` also open the
   local page. It is available under **Controls → Continue Work** too.
2. Choose **New**, name the workspace, and select its folder. Fill in **Where I
   stopped** and **Next steps**. Select any apps and HTTPS pages you want to reopen.
   **Import project** copies context from an existing project record into an
   unsaved checkpoint; the original record remains unchanged.
3. Click **Save checkpoint**. Saving does not launch anything.
4. Later, select the checkpoint and click **Continue my work**. Read the folder,
   apps and page addresses, then accept or cancel. Notes and next steps are already
   displayed, even if you choose not to reopen anything.
5. Edit the notes and save again when you stop. **Delete** removes the checkpoint
   and its reopening history without deleting project files.

The latest saved checkpoint appears first. Saving detects conflicting edits from
another window; reload before replacing a newer checkpoint. Unsaved edits are not
silently discarded by New, Refresh, selection changes or closing the control panel.
They must be saved before reopening a workspace.

The direct desktop entry point is `launch.py --workspaces`; it opens the settings
window without starting another assistant or cloud microphone session.

## What reopening means

The folder opens in the system file manager. Supported apps are VS Code, Chrome,
Firefox, Notepad, Calculator and Spotify; each uses its own existing session behavior.
Saved HTTPS pages open through the default browser. Pages with embedded username/
password credentials, file/JavaScript links, arbitrary application names and shell
commands are refused. A folder is local and existing, never a drive root or UNC share.

This does not reconstruct unsaved editor buffers, cursor positions, window layouts,
private browser tabs, terminals or running servers. It does not infer your progress
from screenshots or monitor your activity. Next steps are your saved text, not a
claim that tasks were automatically completed. No background restoration occurs.

The exact plan and revision are checked again before opening each item. Memory,
file-read, app-opening and browser Deny settings remain authoritative. The PC review
grants this specific reopening operation; it cannot grant unrelated actions. If a
permission or checkpoint changes, or an adapter fails, later items stop. Already
opened windows are not closed or undone. Browser pages and apps can have their own
network activity and session behavior.

Results show adapter responses as **returned / unverified**; requesting a launch is
not independent proof that the intended window appeared. Up to ten reopening records
are retained per workspace. If the app exits mid-operation, its saved in-progress
status says the outcome is unknown; it is never automatically replayed.

## Storage and privacy

Checkpoints and reopening results use encrypted tables in `memory/remote.db`, with
the existing Windows-account DPAPI-protected key. Remote access does not need to be
enabled. Workspace IDs, revisions, timestamps and run statuses are metadata; content
is encrypted. Deletion is logical deletion, not a secure disk wipe. Losing the key
or its Windows account can make checkpoints unreadable.

There are no new HTTP routes or model tools to read, edit or reopen these workspaces.
The exact typed local commands open the PC editor. Voice-triggered or phone workspace
restoration remains separate work. No checkpoint is sent to a cloud model by this
feature.

Tests use temporary encrypted databases and mocked launch adapters. They cover
validation, conflict detection, no-op cancellation, denied/changed permissions,
changed plans, missing folders, partial failures, saved results, local command
routing and UI editing. Native app restoration still depends on installed apps and
their launch behavior.

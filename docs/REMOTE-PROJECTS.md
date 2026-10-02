# Reviewed project commands, workflows and notifications

The phone can now run commands explicitly reviewed on the PC, run saved low-risk
workflows, control existing automations, and read saved completion notifications.
Remote access and each feature still require PC approval and device permission.

## Approve a project command

1. Restart MARK LIV to load the new code. Open **Remote Projects** in the control
   panel and create a profile with a name, existing project directory, absolute
   executable path, and arguments (one argument per line).
2. Select Task for a finite build/test command, or Server for a long-running
   development server. Set a timeout and, for a server, its local port.
3. Check approval and choose **Review and Save**. Read the complete command and
   directory before accepting. Unapproved profiles cannot run from the phone.
4. Grant Projects in Remote Devices, both globally and to the trusted phone.
   On the phone, open Projects and run the approved command. Jobs shows output,
   exit status and Stop. Notifications retains its completion result.

For example, a test profile can use a project's absolute Python executable with
the arguments `-m` and `pytest` on separate lines. Use the interpreter and test
command appropriate to that project; this example does not install dependencies.

These commands run with your Windows account's access. **This is not a sandbox.**
Approval covers executing that project, including its scripts and dependencies
as they subsequently change. The executable hash and profile revision are checked,
but the project's full source tree is not hashed. Terminal permission set to Deny
blocks launch. Otherwise the explicit PC profile approval grants that fixed
command without repeated desktop confirmation. The phone cannot supply replacement
arguments, executable paths or project directories, or create approved profiles.

## Execution and stopping

Windows workers use an owned Job Object, attach a suspended process before running
it, and terminate its process tree on cancellation, timeout, revocation, disabled
access or service shutdown. Only processes launched by that worker are targeted.
An already occupied configured server port is rejected before launch.
See [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Two project workers can run concurrently; the same profile cannot overlap itself.
Task timeouts are at most one hour; server timeouts are at most 24 hours. Output is
bounded to approximately 64 KiB per receipt. Exit code zero means the process
completed successfully, not that its business outcome was independently verified.
Port reachability is a connection check, not proof of server identity or health.
Stopping cannot undo files already changed or requests sent to external services.
After a crash, orphaned jobs have unknown outcomes and are not automatically rerun.
Stable request IDs prevent a network retry from launching the same request twice.

## Saved workflows and automations

Workflows executes saved PC definitions whose steps are LOW risk and already
allowed by PC policy. Definition versions and device permissions are rechecked;
editing a workflow requires refreshing before another run. Stop takes effect
between steps; an action already executing is not rolled back. Legacy action
text is recorded as returned/unverified rather than a verified success.

Automations lists existing rules and supports enable, disable and run now using
revision checks. Existing cooldown, enabled-state and concurrency rules still
apply. Monitoring set to Deny blocks these controls. Phone execution is restricted
to allowed low-risk actions. Definition editing remains on the PC.

## Notifications and limits

The inbox stores device-scoped completion/failure messages, Normal or Important
priority, and read state in the encrypted remote database. It displays the latest
100 messages after reconnecting. Optional [Web Push alerts](PHONE-REPLIES-AND-ALERTS.md)
can now announce future results after subscribing on the phone.

Physical-phone/mobile-data/push validation, call-style alerts, email OAuth,
dedicated Git diff review and automated repair, file writes, mouse/keyboard control,
and critical-action biometric confirmation remain separate unfinished phases.
See [remote setup and current boundaries](REMOTE-COMMAND-CENTER.md).

Automated tests use temporary projects and real harmless Python child processes
to check output, exit codes, timeout, server ports, cancellation and process-tree
cleanup. Workflow actions and automation notifications use test adapters. Browser
validation uses temporary trust data and a temporary project, not user projects.

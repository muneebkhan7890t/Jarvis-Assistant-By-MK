# Permissions and confirmation

`core/permission_manager.py` is the policy authority for model dispatch, action
and plugin registries, local commands, workflow steps, automation actions and
phone project endpoints. `policy_for()` returns name, category, risk, required
permissions, confirmation requirement, voice sufficiency and interaction metadata.
Policies are code-defined; model parameters cannot lower them.

States are Allow, Ask, Deny, Allow While Active and Always Ask. Malformed policy
files fail closed. Settings are persisted atomically in `config/permissions.json`.
High/critical interactive control, sends, installs and generated execution keep
mandatory UI confirmation regardless of an Allow setting. Unknown plugins are
critical by default. Low-risk app aliases/settings remain quick.

An approval captures a deep copy of the action arguments and a SHA-256 identity,
has a 90-second expiry, is one-shot, and cannot be replaced by a second request.
The complete draft/recipient is scrollable in the desktop banner. Permission is
rechecked immediately before the captured handler runs. A policy deny after a
request prevents execution. Confirmation is not a model or remote API operation.
No voice identity can approve a critical action.

Generic browser/desktop input can have sensitive effects, so these actions always
ask. This is intentionally conservative. In-process plugins are trusted Python;
malicious plugins or local malware are outside this boundary. Do not install
untrusted Python plugins. Desktop input is not a guarantee of remote delivery.

Microphone streaming accepts Allow/Allow While Active; Ask/Deny/Always Ask block
it until changed in the trusted settings UI. Screen/camera cloud vision needs
both capture and cloud-vision permission. While Active for a core screen request
uses the assistant wake state. Registry calls are deliberate active requests.
Workflow/automation validation excludes sensitive replay. No per-contact permanent
send permission or biometric authorization has been implemented.

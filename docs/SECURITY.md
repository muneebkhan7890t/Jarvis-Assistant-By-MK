# Security changes and limits

The September remote upgrade uses persistent approved device keys and signed,
nonce-bound requests. The legacy token dashboard is disabled by default. See
[Remote Command Center](REMOTE-COMMAND-CENTER.md) for its threat boundaries,
encrypted receipt storage, restricted shared cloud session and private-network
setup. This implementation is not a security certification or malware guarantee.

Removed the nonempty bundled API credential and TLS private key/certificate.
Rotate the old credential with its provider. Existing environment credentials
were not printed, modified or revoked. Config/keyring fallback and self-signed
TLS are documented in INSTALLATION.md.

Source archives use an allowlist and a credential-pattern check. Runtime config,
permissions, personal memory, databases, workflows, logs, uploads, certificates,
browser sessions, environments and bytecode are excluded. The local environment
and user databases were retained on the computer, not deleted.

Approval gates bind action parameters and never accept model confirmation flags.
Structured audit records omit argument values, transcripts, clipboard content,
credentials and message bodies. Existing UI logs still display user-requested
results and legacy action diagnostics; they are not a fully audited private-log
redaction system. Do not share raw runtime logs without review.

Generated desktop code is parsed and interpreted in a small bounded grammar.
There is no Python eval/exec, module import, arbitrary attribute access, file API,
loop, network API or subprocess API. Allowed GUI input still affects the host and
requires a source-code review banner. It is not an OS security sandbox.
Generated full programs require an explicitly configured container. They never
run through the host interpreter. Read-only bind mounts, no network, limited
resources, no inherited environment credentials, and forced container removal
reduce exposure. A malicious container image/runtime or kernel exploit is outside
this defense. Container execution has not been hardware-tested here.

Phone access is opt-in and loopback-only unless LAN access is enabled. HTTP routes
have bounded requests, throttling and security headers. Bearer sessions expire;
device secrets rotate and expire. Revoke-all invalidates bearer tokens and closes
connected sockets. WebSockets validate browser Origin and recheck expiration.
Uploads are limited to 25 MiB and allow document/media extensions, reject reserved Windows names, use
exclusive creation and constrain download resolution to the upload folder.
These checks are not antivirus or full file-format/MIME inspection.

The QR route still uses a short-lived, one-use URL secret for compatibility.
Responses forbid caching and referrer forwarding; raw access logging is disabled
by the server log level. The frontend retains its older optional AES-CBC wrapper;
TLS is the transport security boundary, not that wrapper. Device sessions are
memory-only and do not survive restart; per-device management is incomplete.

Do not expose this personal assistant directly to the public internet. Security
here is defense in depth, not a claim that all legacy application behavior has
received a complete penetration test.

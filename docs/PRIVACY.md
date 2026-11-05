# Network privacy and safe sharing

## New network controls

- Personal network names, profile identifiers, adapter names, and passwords are
  runtime data. No workstation-specific values belong in source or fixtures.
- Passwords are masked by default. **Show / Hide** deliberately reveals only the
  text you are currently entering, so hide it before screenshots or screen sharing.
  Reveal state resets on empty/disabled fields, submission, cancellation, security
  changes, and navigation. Passwords are cleared when submitting or leaving the
  form; neither draft credentials nor reveal preferences are persisted in config.
- The shell sends requests through an anonymous stdin pipe to a short-lived
  Python helper. Passwords never enter process arguments, inherited environment
  variables, temporary credential files, or helper diagnostic messages.
- The helper uses typed GVariant constructors and the local system D-Bus to
  communicate with NetworkManager. It does not parse a shell command or call
  `GetSecrets`. Saved-profile output is a whitelist of UI metadata, not the
  complete settings dictionary.
- NetworkManager owns saved credentials and its normal authorization/storage
  rules still apply. “Saved” intentionally means NetworkManager may store the
  password on disk; this shell does not create its own password database.
- Error messages may include fixed stage/category codes such as
  `update-profile/local-timeout`. These contain no SSID, password, profile ID,
  object path, or raw diagnostic text. They distinguish profile authorization,
  configuration rejection, and activation failure without exposing credentials.
- Native diagnostic text is not forwarded to the GUI or logs. GIO message-body
  debugging (`G_DBUS_DEBUG`) is rejected, and the helper disables core dumps.
  This is not guaranteed memory zeroization and does not defend against root,
  a privileged debugger, compromised system services, or whole-shell memory
  dumps. Python, QML, GLib, and NetworkManager necessarily handle credentials in
  memory while connecting.
- Network names are rendered as plain text, not rich text containing images or
  links. Merely displaying an SSID must not cause an external resource request.
- Hidden Wi-Fi is not anonymous. Connecting can send directed probes containing
  the SSID; automatic connection is off by default in the hidden-network form.
- Disconnect, Forget, and auto-connect changes verify the exact Wi-Fi profile or
  interface. They do not target Ethernet or weaken NetworkManager authorization.

## Sharing the repository

The automated fixtures use only synthetic identities, network names, UUIDs, and
password-like sentinels. Local screenshots/evidence are kept outside the source
checkout or in ignored test-output directories. The repository ignores Python
bytecode, local environment files, NetworkManager profile exports, and designated
test-evidence directories. Ignore rules are a guardrail, not a replacement for
reviewing a staged diff: forced-added or already-tracked files remain publishable.

Before publishing, review `git status --short`, `git diff --cached`, and the
tracked-file list. Never add real `.env` values, exported `.nmconnection` files,
keyring databases, runtime shell configuration, crash dumps, chat history,
clipboard exports, raw network diagnostics, or screenshots of real credentials.
Redact SSIDs, IPs, profile IDs, file paths, and account names when sharing evidence.
The current working-tree review is not a complete audit of Git history.

## Existing non-network boundaries

The network work is not a whole-application security certification. Separate
pre-existing source paths need their own hardening before treating all runtime
logs, chats, or process metadata as safe to share:

- The AI `/key get` command can display an API key in chat, and chat history can
  subsequently be persisted. Some AI request builders expand API keys into curl
  arguments. These are not real secret literals checked into this repository,
  but using those features can expose runtime credentials.
- The lock/keyring integration has a password-in-environment handoff that needs
  an independent review. Its live behavior was not exercised for this task.
- Thumbnail, wallpaper, search, and clipboard diagnostics elsewhere may contain
  local paths or other personal metadata. Do not publish raw logs indiscriminately.

No real credential literals were identified in the inspected working tree.
That observation is scoped to the source/content review, not a promise that
all other app features or historical commits are leak-free.

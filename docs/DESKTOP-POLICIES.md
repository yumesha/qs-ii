# Night Light and Keep awake

## Manual Night Light stays manual

A normal click selects **manual on** or **manual off** and saves both
`light.night.manualEnabled` and `light.night.automatic=false`. This choice survives
Quickshell/configuration reloads and time changes. It is not reset at midnight or
the next scheduled boundary. Right-click explicitly toggles Auto; enabling Auto
resumes the configured schedule immediately. Disabling Auto preserves the current
requested state as a manual choice.

The service waits for configuration readiness before applying anything, and
serializes backend requests. Automatic windows include their start and exclude
their end, including overnight schedules. Equal start/end retains the existing
full-day convention. The backend uses Hyprsunset's `identity` IPC command for
neutral Off, not a 6500 K color transform. On explicitly applies its temperature
and verifies the numeric readback: the numeric value alone cannot distinguish
identity mode from an active transform. It does not repeatedly kill/relaunch a
working Hyprsunset process. Backend failures are shown in the toggle's tooltip.

## Keep awake survives shell reloads

Keep awake is scoped to the current Hyprland compositor session. It survives
Quickshell reloads and crashes, but starts off in a new compositor/login session.
It is not a permanent policy that silently disables locking after the next login.

The authoritative state is a private, atomically written marker under
`$XDG_RUNTIME_DIR/qs-ii/idle/`, keyed to the compositor instance. Both on and off
are recorded, so an old mirrored preference cannot re-enable a choice that was
turned off. The old saved idle flag is imported only once for the same session.
The UI reconciles on component initialization as well as readiness notifications;
it no longer relies on catching one transient `readyChanged` signal.

An independent systemd user service holds a **logind idle-only block inhibitor**.
It is not tied to the Quickshell PID. It checks the compositor's lifetime and
releases its inhibitor when the session ends or the marker turns off. The UI
confirms the real logind inhibitor rather than assuming that a requested toggle
or running process is sufficient. A mapped, input-transparent 1×1 Wayland surface
provides complementary compositor inhibition.

Only automatic idle policy is suppressed. **Manual Lock, manual suspend/shutdown,
and the existing before-sleep lock remain available.** Other programs that issue
an explicit lock command are not overridden. A missing/invalid state marker does
not silently disable normal locking. Errors appear in the Keep awake tooltip.

## Hypridle integration

The independent inhibitor works with Hypridle 0.1.6's supported systemd inhibition.
For protection even across an inhibitor-process gap, guard the *automatic*
`on-timeout` commands in your existing Hypridle configuration. Keep your existing
timeouts. Do not replace `general.lock_cmd`, `before_sleep_cmd`, manual shortcuts,
or `on-resume` commands with these guards.

Inside the existing `general` block, retain/add:

```ini
ignore_systemd_inhibit = false
```

Replace the command in each relevant existing listener:

| Automatic timeout | Replacement `on-timeout` command |
| --- | --- |
| Lock | `python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard lock` |
| Screen off | `python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard dpms-off` |
| Suspend | `python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard suspend` |

Adjust the path if your shell is installed elsewhere. The script does not require
an executable file bit. Dependencies are Python 3, systemd user services,
`systemd-inhibit`, `systemd-run`, `systemctl`, `busctl`, and `hyprctl`.

Hypridle 0.1.6 reads configuration at startup. Restart the existing idle daemon
or log in again to apply changed listeners; do not launch a second copy. Do not
use SIGHUP as a reload command. Its `--help` flag is also not a safe diagnostic:
that version ignores unknown flags and may start a second daemon.

The Hypridle configuration is separate from this Quickshell repository, so
copying only the repository does not automatically replace another machine's
idle-policy configuration.

## Non-disruptive checks

```bash
qs -c ii ipc call nightLight status
qs -c ii ipc call idle status
python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py status
python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard lock --dry-run
python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard dpms-off --dry-run
python3 -B ~/.config/quickshell/ii/scripts/session/keep-awake.py guard suspend --dry-run
```

`--dry-run` never executes an idle action, even when Keep awake is off. While on,
status should report `inhibit:true`, `backendActive:true`, and no error; each guard
should report `skipped:true`. While off, a dry run reports `skipped:false` without
locking, blanking, or suspending anything.

Tests use temporary state, fake backend commands, and isolated offscreen QML
engines. They cover saved manual on/off, fresh-engine reload, time transitions,
early/late readiness, stale-state migration, session isolation, backend failures,
independent service lifecycle, and safe automatic-action dispatch. They do not
lock/suspend the real desktop or substitute for a multi-day idle soak test.

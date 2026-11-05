# qs-ii

## Features

- Image and video wallpapers, including MOV, MP4, and WebM.
- Individual wallpapers for numbered and named workspaces.
- Automatic video pause for fullscreen windows, screen locking, and low battery.
- Playback speed, volume, fit, and manual pause controls.
- Settings panel, workspace bar, and system tray.

## Run

With the configuration installed as `ii`, start the shell:

```bash
QT_IM_MODULE=wayland qs -c ii --no-duplicate --daemonize
```

Open Settings from the repository root:

```bash
QT_IM_MODULE=wayland qs -p settings.qml --no-duplicate --daemonize
```

Changes normally reload automatically. Reopen Settings if it still shows the
previous version. QML edits do not require a NixOS rebuild.

## Manual testing

Open **Settings → Wallpaper** and use an image and a short video.

| Check | Expected result |
| --- | --- |
| Choose a default wallpaper | Unassigned workspaces use it. |
| Assign different wallpapers to workspaces | Each workspace shows its own image or video. |
| Click **Use default** | The selected workspace returns to the default. |
| Pause and resume | Playback stops and continues from the same position. |
| Maximize or fullscreen a window | Video pauses when the corresponding smart-pause option is enabled. |
| Switch away from a maximized window | It does not pause video on another workspace. |
| Lock and unlock | Video follows the pause-on-lock setting. |
| Change volume, speed, and fit | Playback follows the selected controls. |
| Disable video playback | A static thumbnail remains. |
| Reopen Settings or log in again | Preferences and workspace assignments are preserved. |
| Check settings and tray icons | Icons render without text fragments or checkerboards. |
| Click Settings repeatedly after a shell crash/restart | One Settings window opens; no extra bars or wallpapers appear. |

Playback controls apply to all video wallpapers. Each monitor follows its own
active workspace. Switching to a different video starts it from the beginning.
Settings save automatically.

## Night Light and Keep awake

- A normal **Night Light** click selects persistent manual on/off mode. It survives
  reloads and stays manual until you explicitly right-click to enable **Auto**.
  Automatic mode still follows the configured start/end times.
- **Keep awake** survives Quickshell reloads/crashes within the current Hyprland
  session. It uses an independent systemd user idle inhibitor and reports backend
  failures instead of silently claiming protection.
- Automatic idle lock, screen-off, and suspend commands can additionally consult
  the session marker. Manual lock and before-sleep locking remain unchanged.
  A new compositor/login starts with Keep awake off.

See [desktop-policy integration and checks](docs/DESKTOP-POLICIES.md), especially
when installing this repository on another machine: hypridle integration is
separate from the Quickshell files.

## Wi-Fi controls

Selecting a network with one matching saved profile activates it using its
stored credentials; it does not rewrite the password or require permission to
edit the profile. New secured networks show a password prompt. **Use saved**
appears when a saved profile exists. New profiles are user-owned; changing a
protected system-wide profile still requires separate system authorization.
Run a standard Polkit authentication agent in the graphical session (for example,
Hyprpolkitagent) to display administrator prompts. Administrator group membership
alone does not provide that dialog. Protected updates/removals allow up to two
minutes for authorization; no passwordless Polkit rule is installed by this project.
**Details** opens built-in saved-network management, not an external app.

- **Hidden…** accepts an exact SSID, Personal/Open security type, password, and
  adapter selection when needed. Hidden auto-connect defaults to off because
  directed probes can reveal the network name to nearby observers.
- **Details / Saved** lists profiles even when out of range, connects a selected
  profile, toggles automatic connection, and forgets it only after confirmation.
- Hover the network toggle to see the connected Wi-Fi SSID and/or Ethernet profile
  name. Both are shown when both interfaces are connected. Names are live local
  UI data rendered as plain text, not stored in source or diagnostic output;
  bridges and loopback connections are excluded from name selection.
- Credentials travel through an anonymous stdin pipe and typed local D-Bus calls
  directly to NetworkManager: not command arguments, environment variables,
  temporary files, config JSON, or diagnostic messages. Fields clear on submit
  and navigation. NetworkManager stores saved credentials under its own policy.
- Dependencies: Python 3.10+, installed GLib/GIO libraries, NetworkManager and
  nmcli. No extra Python packages or Plasma settings launcher are required.
  Manual enterprise/certificate and WEP setup are outside this form's scope;
  already-configured enterprise profiles can be activated from Saved. On Nix,
  runtime library discovery can use the installed nmcli package's libnm dependency
  paths; no compiler in the desktop's PATH or hard-coded store path is required.

See [network privacy and sharing boundaries](docs/PRIVACY.md) before distributing
runtime logs, screenshots, or configuration files. Source-sharing checks are not
an assurance that unrelated application subsystems never handle sensitive data.

- **Disconnect** disconnects only the selected Wi-Fi interface and keeps the
  saved profile/password. It prevents automatic reconnection until you connect
  again manually.
- **Forget** appears for saved networks and asks for confirmation before removing
  the displayed number of saved profiles. Removing an active profile also
  disconnects that Wi-Fi connection. Cancellation removes nothing.
- Both operations recheck the interface/profile type and exact SSID. Forget uses
  the confirmed UUIDs, not connection display names, and reports partial failures.
  They do not disconnect Ethernet or change NetworkManager authorization rules.
- Wi-Fi and Ethernet can be connected at the same time. A checkmark means Wi-Fi
  is connected, not that it is the preferred route. When Ethernet is unplugged,
  connected, working Wi-Fi normally takes over; otherwise connect it manually.

## Regression tests

```bash
node --test tests/*.test.cjs
G_DEBUG=fatal-warnings python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use fake commands/mocks: they do not connect, disconnect, or forget real
networks, change the live color temperature, or lock/suspend the desktop. QML
lifecycle tests launch isolated offscreen engines with fake backends when `qs` is
available. Live Wi-Fi action testing should use a disposable profile, especially
for Forget. These bounded checks do not replace a multi-day idle soak test.

## Troubleshooting

Check the network helper in the actual desktop shell's environment (read-only):

```bash
qs -c ii ipc call network refreshBackendStatus
qs -c ii ipc call network backendStatus
```

The refresh is asynchronous; query again after it finishes. The response includes
only readiness/counts and safe error categories—not SSIDs, profile IDs, addresses,
credentials, or environment values. `startup-library-*` indicates a helper loader
problem before any Wi-Fi authentication attempt.

After a Quickshell crash, child processes can inherit private crash-recovery
variables that cause `qs` to reopen the desktop instead of the requested window.
The shell's launch helper clears these variables for Settings, other shell
utilities, and IPC calls. Settings also uses `--no-duplicate`.
If a terminal inherited the same variables, clear them before running `qs`:

```bash
unset __QUICKSHELL_CRASH_DUMP_PID __QUICKSHELL_CRASH_INFO_FD
```

Check running instances and recent logs:

```bash
qs list --all
qs -c ii log --tail 100 --no-color
```

Inspect wallpaper selection and playback state:

```bash
qs -c ii ipc call videoWallpaper wallpapers | jq
qs -c ii ipc call videoWallpaper status | jq
```

A paused video may be intentional: check its `reason` before troubleshooting.
An empty video-status list is normal when the visible wallpapers are images or
video playback is disabled.

For bug reports, include reproduction steps, expected and actual behavior, and
a screenshot or relevant log excerpt.

## License

qs-ii is independently maintained by yumesha and licensed under the
[GNU General Public License v3](LICENSE).

[Repository](https://github.com/yumesha/qs-ii) · [Report an issue](https://github.com/yumesha/qs-ii/issues)

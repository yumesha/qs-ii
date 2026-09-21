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

Playback controls apply to all video wallpapers. Each monitor follows its own
active workspace. Switching to a different video starts it from the beginning.
Settings save automatically.

## Troubleshooting

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

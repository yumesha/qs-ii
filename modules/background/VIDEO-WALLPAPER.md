# Video wallpaper

Open Settings → Wallpaper (between Quick and General), select **Default** or a
workspace, then **Choose image or video**.
The shell plays local MP4, WebM, MKV, MOV, AVI, and M4V files through the
already-installed Qt Multimedia backend. No mpvpaper or Plasma session is
needed. Each monitor follows its active workspace independently. Unassigned
workspaces use the default wallpaper. Numbered and named workspaces are
supported; special scratchpads keep the underlying workspace's wallpaper.
Use **Use default** to remove a workspace assignment. Assignments are restored
at login, and videos restart when switching to a different video file.

Defaults: loop, mute, normal speed, fill screen; pause for fullscreen/maximized
windows on the visible workspace, a locked screen, or battery at/below 20%.
Screen-off always pauses. The page also offers pause for any visible window,
manual pause/resume, volume, speed, fit mode, and **Restore image**.
Only one monitor plays audio when unmuted. Disabling playback keeps the
thumbnail as a static wallpaper.

Shared playback settings are persisted under `background.video`, and workspace
assignments under `background.workspaceWallpapers`, in
`~/.config/illogical-impulse/config.json`. Preview images are cached under
`$XDG_CACHE_HOME/quickshell/video-wallpapers` (normally `~/.cache`). Video
selection keeps the current color palette; the existing Quick page's palette
controls regenerate colors from the default wallpaper's thumbnail. Changing a
workspace wallpaper does not change the default or the shell's color palette.

Implementation:

- `VideoWallpaper.qml`: local player and video output.
- `../../services/SmartVideoWallpaper.qml`: per-monitor pause decisions and
  runtime status (`qs -c ii ipc call videoWallpaper status`), plus active image
  and video assignments (`qs -c ii ipc call videoWallpaper wallpapers`).
- `../common/functions/VideoWallpaperPolicy.js`: visible-workspace filtering
  and pause rules.
- `../settings/VideoWallpaperConfig.qml`: settings page.
- `../../scripts/colors/video-thumbnail.py`: validated thumbnail generation.

Validation covered page loading, selection and persistent settings, video
decoding, manual pause/resume, invalid files, special characters in filenames,
browser thumbnails, and live Hyprland maximize/fullscreen pause/resume. Battery,
screen-off, lock and multiple-monitor decisions were checked with simulated
state; the development machine has one monitor and no battery.
Workspace validation covered saved image/video assignments, invalid-file
handling, removing an override, named workspace IDs, independent monitor
selection, and live image → video → default → video transitions.

## Stalled playback

A player can report `Playing` even when decoding has stopped. The shell checks
playback progress and video-frame delivery every two seconds. After roughly
15 seconds without progress while playback is wanted, it recreates the media
player and attempts to resume near the previous position. Once playback is
established, the stall threshold is four seconds; a new file gets fifteen
seconds to load. A stall near the end of a clip restarts from the beginning
instead of seeking back into the stalled loop boundary. Intentional pauses
(manual, covered window, locked screen, screen off, or low battery) do not
trigger recovery.

Recovery is limited to three consecutive attempts with increasing delays.
Thirty seconds of healthy playback resets that budget. If all attempts fail,
Settings shows an error; manually pause/resume, select another file, or toggle
video playback to retry. Status IPC includes `recovering`, `recoveryCount`,
`lastRecoveryReason`, `progressAgeMs`, and `frameAgeMs` for diagnosis. Recovery
messages are recorded in the Quickshell log.

Tests cover repeated looping, unexpected stops, injected position/frame stalls,
intentional pauses, source changes during recovery, and the retry limit. These
short tests do not substitute for a multi-day playback test.

On the AMD/NVIDIA system, Qt logged `EGL_BAD_MATCH` when importing AMD VAAPI
frames into NVIDIA rendering. The shell sets
`QT_DISABLE_HW_TEXTURES_CONVERSION=1` to use Qt's compatible frame-upload path
while keeping hardware decoding available. This can increase frame-copy/CPU
cost. The option takes effect when the Quickshell process starts; a QML reload
alone is insufficient. The status field `compatibleTextureUpload` confirms
the launch setting. This is a workaround for the observed graphics errors,
not proof that every long-running decoder issue is resolved.

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

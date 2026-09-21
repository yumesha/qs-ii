pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs
import qs.modules.common
import "../modules/common/functions/VideoWallpaperPolicy.js" as Policy

Singleton {
    id: root
    readonly property bool selected: Policy.isVideo(Config.options.background.wallpaperPath)
    readonly property bool anyVideo: selected || Config.options.background.workspaceWallpapers.some(item => Policy.isVideo(item.path))
    readonly property var options: Config.options.background.video
    property var players: ({})
    property var backgrounds: ({})
    readonly property string audioMonitor: HyprlandData.monitors.find(monitor =>
        Policy.isVideo(Wallpapers.forWorkspace(Policy.workspaceKey(monitor.activeWorkspace)).path))?.name ?? ""

    function reasonForMonitor(name, safety) {
        return Policy.pauseReason(options, {
            monitor: HyprlandData.monitors.find(m => m.name === name),
            clients: HyprlandData.windowList,
            locked: GlobalStates.screenLocked,
            overview: GlobalStates.overviewOpen,
            safety: safety,
            onBattery: Battery.available && !Battery.isPluggedIn,
            batteryPercent: Battery.percentage * 100
        });
    }

    function registerPlayer(name, player) { players[name] = player; }
    function unregisterPlayer(name, player) {
        if (players[name] === player) delete players[name];
    }
    function registerBackground(name, background) { backgrounds[name] = background; }
    function unregisterBackground(name, background) {
        if (backgrounds[name] === background) delete backgrounds[name];
    }

    // Query after a burst settles. The shared data service may already have a
    // request in flight when the final fullscreen/workspace event arrives.
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (root.anyVideo || Config.options.background.workspaceWallpapers.length) refreshTimer.restart();
        }
    }
    Timer {
        id: refreshTimer
        interval: 150
        onTriggered: {
            HyprlandData.updateWindowList();
            HyprlandData.updateMonitors();
        }
    }

    // Hyprland does not emit a dedicated DPMS event on every version.
    Timer {
        interval: 3000
        running: root.anyVideo && root.options.enabled
        repeat: true
        onTriggered: {
            HyprlandData.updateWindowList();
            HyprlandData.updateMonitors();
        }
    }

    // Status is queried by the separate settings process; it never creates players.
    IpcHandler {
        target: "videoWallpaper"
        function status(): string {
            return JSON.stringify(Object.keys(root.players).map(name => {
                const player = root.players[name];
                return { monitor: name, playing: player.playing, reason: player.pauseReason,
                    workspace: player.workspace, path: player.sourcePath,
                    error: player.error, position: player.position, hasVideo: player.hasVideo };
            }));
        }
        function wallpapers(): string {
            return JSON.stringify(Object.keys(root.backgrounds).map(name => {
                const background = root.backgrounds[name];
                return { monitor: name, workspace: background.wallpaperWorkspace,
                    path: background.selectedWallpaper.path, overridden: background.selectedWallpaper.overridden,
                    video: background.wallpaperIsVideo };
            }));
        }
    }
}

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
    readonly property var options: Config.options.background.video
    property var players: ({})
    readonly property string audioMonitor: HyprlandData.monitors[0]?.name ?? ""

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

    // Query after a burst settles. The shared data service may already have a
    // request in flight when the final fullscreen/workspace event arrives.
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (root.selected) refreshTimer.restart();
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
        running: root.selected && root.options.enabled
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
                    error: player.error, position: player.position, hasVideo: player.hasVideo };
            }));
        }
    }
}

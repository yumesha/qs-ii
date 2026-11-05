pragma Singleton
pragma ComponentBehavior: Bound

import qs
import qs.modules.common
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    property bool inhibit: false
    property bool ready: false
    property bool backendActive: false
    property string error: ""
    readonly property bool busy: controlProc.running
    readonly property string helper: Quickshell.shellPath("scripts/session/keep-awake.py")

    // Defer until Persistent's own ready handler has captured the previous
    // compositor identity. Also handle a singleton loaded AFTER it became ready.
    Component.onCompleted: Qt.callLater(root.initialize)
    Connections {
        target: Persistent
        function onReadyChanged() { Qt.callLater(root.initialize); }
    }
    function load() { Qt.callLater(root.initialize); }
    function initialize() {
        if (root.ready || root.busy || !Persistent.ready) return;
        const signature = Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") || "";
        const state = Persistent.states.idle;
        // A different shell/settings process can update the shared global session
        // signature first. Once migrated, use this idle choice's own session tag.
        const sameSession = state.instanceSignature ? state.instanceSignature === signature
            : !Persistent.isNewHyprlandInstance;
        root.run("restore", sameSession && state.inhibit);
    }
    function run(action, legacyOn = false) {
        if (root.busy) return;
        controlProc.result = "";
        const command = ["python3", "-B", root.helper, action];
        if (action === "restore" && legacyOn) command.push("--legacy-on");
        controlProc.exec(command);
    }
    function toggleInhibit() {
        if (!root.ready || root.busy) return;
        root.run(root.inhibit ? "off" : "on");
    }

    Process {
        id: controlProc
        property string result: ""
        stdout: StdioCollector { onStreamFinished: controlProc.result = text }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(result);
                if (typeof response.inhibit !== "boolean" || typeof response.backendActive !== "boolean") throw new Error();
                root.inhibit = response.inhibit;
                root.backendActive = response.backendActive;
                root.error = exitCode === 0 && exitStatus === 0 && response.ok ? "" :
                    (response.error || "Could not confirm the idle inhibitor.");
                // A mirror for existing UI/state consumers, not the authoritative
                // marker used by automatic-lock guards or future reloads.
                const signature = Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") || "";
                if (Persistent.ready && signature) {
                    Persistent.states.idle.inhibit = root.inhibit;
                    Persistent.states.idle.instanceSignature = signature;
                }
            } catch (_) { root.error = "Could not read the keep-awake service response."; }
            root.ready = true;
        }
    }

    // Reconcile an unexpectedly stopped backend; never tie its lifetime to this
    // QML component. The separate user service survives shell reloads/crashes.
    Timer {
        interval: 30000
        running: root.ready
        repeat: true
        onTriggered: if (!root.busy) root.run("restore")
    }

    // Keep the native backend in a separate, conditional source so headless
    // controller tests do not resolve a PanelWindow without a Wayland backend.
    LazyLoader {
        active: root.inhibit && !!Quickshell.env("WAYLAND_DISPLAY")
        source: Quickshell.env("WAYLAND_DISPLAY") ? Qt.resolvedUrl("idle/AwakeSurface.qml") : ""
    }

    IpcHandler {
        target: "idle"
        function status(): string {
            return JSON.stringify({ ready: root.ready, inhibit: root.inhibit,
                backendActive: root.backendActive, busy: root.busy, error: root.error });
        }
    }
}

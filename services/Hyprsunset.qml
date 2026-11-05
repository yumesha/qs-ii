pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import qs.modules.common
import "../modules/common/functions/NightLightPolicy.js" as Policy
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    readonly property var options: Config.options.light.night
    readonly property bool automatic: options.automatic
    readonly property int colorTemperature: options.colorTemperature
    readonly property bool desiredActive: Config.ready && Policy.desired(options, DateTime.clock.hours, DateTime.clock.minutes)
    readonly property bool applying: applyProc.running
    property bool active: false
    property string error: ""
    property bool applyAgain: false

    onDesiredActiveChanged: reEvaluate()
    onAutomaticChanged: reEvaluate()
    onColorTemperatureChanged: reEvaluate()
    Component.onCompleted: reEvaluate()
    Connections {
        target: Config
        function onReadyChanged() { root.reEvaluate(); }
    }

    function load() { root.reEvaluate(); }
    function fetchState() { root.reEvaluate(); }
    function reEvaluate() { if (Config.ready) Qt.callLater(root.applyState); }

    function setManual(enabled) {
        if (!Config.ready) return;
        // Set both fields before the coalesced config write/apply. Manual choice
        // is authoritative until the user explicitly opts back into the schedule.
        root.options.manualEnabled = enabled;
        root.options.automatic = false;
        root.reEvaluate();
    }
    function toggle() { root.setManual(!root.desiredActive); }
    function toggleAutomatic() {
        if (!Config.ready) return;
        if (root.automatic) root.options.manualEnabled = root.desiredActive;
        root.options.automatic = !root.automatic;
        root.reEvaluate();
    }

    function applyState() {
        if (!Config.ready) return;
        if (applyProc.running) { root.applyAgain = true; return; }
        applyProc.result = "";
        applyProc.requested = root.desiredActive;
        applyProc.requestedTemperature = root.colorTemperature;
        applyProc.exec(["python3", "-B", Quickshell.shellPath("scripts/session/night-light.py"),
            root.desiredActive ? "on" : "off", String(root.colorTemperature)]);
    }

    Process {
        id: applyProc
        property string result: ""
        property bool requested: false
        property int requestedTemperature: 5000
        stdout: StdioCollector { onStreamFinished: applyProc.result = text }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(result);
                if (exitCode !== 0 || exitStatus !== 0 || !response.ok) {
                    root.error = response.error || "Could not apply the night-light preference.";
                } else {
                    root.active = response.active;
                    root.error = "";
                }
            } catch (_) { root.error = "Could not read the night-light service response."; }
            if (root.applyAgain || requested !== root.desiredActive || requestedTemperature !== root.colorTemperature) {
                root.applyAgain = false;
                root.reEvaluate();
            }
        }
    }

    // Repair a backend restart without forgetting a saved manual choice.
    Timer {
        interval: 60000
        repeat: true
        running: Config.ready
        onTriggered: root.reEvaluate()
    }

    IpcHandler {
        target: "nightLight"
        function status(): string {
            return JSON.stringify({ automatic: root.automatic, manualEnabled: root.options.manualEnabled,
                desiredActive: root.desiredActive, active: root.active, applying: root.applying, error: root.error });
        }
    }
}

pragma Singleton
pragma ComponentBehavior: Bound

// Took many bits from https://github.com/caelestia-dots/shell (GPLv3)

import Quickshell
import Quickshell.Io
import QtQuick
import "./network"
import "./network/WifiConnection.js" as WifiConnection

/**
 * Network service with nmcli.
 */
Singleton {
    id: root

    property bool wifi: true
    property bool ethernet: false
    
    property bool wifiEnabled: false
    property bool wifiScanning: false
    readonly property bool wifiConnecting: wifiActionProc.running && (wifiAction === "connect" || wifiAction === "activate")
    property WifiAccessPoint wifiConnectTarget
    readonly property bool wifiBusy: wifiActionProc.running
    property WifiAccessPoint wifiActionTarget
    property string wifiAction: ""
    property var savedWifiProfiles: []
    property var wifiAdapters: []
    property string wifiPageError: ""
    property string wifiPageMessage: ""
    readonly property bool wifiProfilesLoading: wifiProfilesProc.running
    property string wifiProfilesError: ""
    readonly property string wifiProfilesScript: Quickshell.shellPath("scripts/network/wifi-profiles.py")
    readonly property list<WifiAccessPoint> wifiNetworks: []
    readonly property WifiAccessPoint active: wifiNetworks.find(n => n.active) ?? null

    property string wiredConnectionName: ""
    property string wifiConnectionName: ""
    property string wifiDevice: ""
    property var wifiScanSnapshot: []
    readonly property string activeWifiName: WifiConnection.connectedWifiName(root.wifiScanSnapshot, root.wifiDevice)
    readonly property string networkName: root.ethernet ? root.wiredConnectionName
        : root.wifi ? (root.activeWifiName || root.wifiConnectionName) : ""
    property int networkStrength
    property string materialSymbol: ethernet ? "lan" :
        wifiEnabled ? (
        Network.networkStrength > 80 ? "signal_wifi_4_bar" :
        Network.networkStrength > 60 ? "network_wifi_3_bar" :
        Network.networkStrength > 40 ? "network_wifi_2_bar" :
        Network.networkStrength > 20 ? "network_wifi_1_bar" :
        "signal_wifi_0_bar"
    ) : "signal_wifi_off"

    // Control
    function enableWifi(enabled = true): void {
        const cmd = enabled ? "on" : "off";
        enableWifiProc.exec(["nmcli", "radio", "wifi", cmd]);
    }

    function toggleWifi(): void {
        enableWifi(!wifiEnabled);
    }

    function rescanWifi(): void {
        wifiScanning = true;
        rescanProcess.running = true;
    }

    function requestWifiConnection(accessPoint: WifiAccessPoint): void {
        if (!accessPoint || root.wifiBusy || accessPoint.active) return;
        accessPoint.connectionError = "";
        const saved = WifiConnection.matchingSavedProfiles(accessPoint, root.savedWifiProfiles);
        if (root.wifiEnabled && saved.length === 1) {
            // Selecting a known network is activation, not a password/profile edit.
            // Rewriting a system-wide profile can require unrelated administrator authorization.
            root.startWifiAction(accessPoint, "activate", {ssid: accessPoint.ssid,
                uuid: saved[0].uuid, device: accessPoint.device});
            return;
        }
        if (saved.length > 1) {
            accessPoint.connectionError = "Several saved profiles match. Select one in Details.";
            return;
        }
        if (root.wifiEnabled && accessPoint.isSecure && !WifiConnection.isEnterprise(accessPoint.security)) {
            accessPoint.askingPassword = true;
        } else {
            root.connectToWifiNetwork(accessPoint);
        }
    }

    function connectToWifiNetwork(accessPoint: WifiAccessPoint, password = undefined): void {
        if (!accessPoint || root.wifiBusy || accessPoint.active) return;
        accessPoint.connectionError = "";
        if (!root.wifiEnabled) {
            accessPoint.connectionError = "Turn on Wi-Fi before connecting.";
            return;
        }
        root.startWifiAction(accessPoint, "connect", WifiConnection.connectRequest(accessPoint, password));
    }

    function disconnectWifiNetwork(network = root.active): void {
        if (!network || !network.active || root.wifiBusy) return;
        root.startWifiAction(network, "disconnect", { ssid: network.ssid, device: network.device });
    }

    function forgetWifiNetwork(network: WifiAccessPoint): void {
        if (!network || root.wifiBusy || !network.confirmingForget || !network.forgetProfileIds.length) return;
        // The confirmation pins exact UUIDs. A newly added profile is never
        // silently included just because it has the same name or SSID.
        const payload = { ssid: network.ssid, uuids: network.forgetProfileIds.slice() };
        network.confirmingForget = false;
        network.forgetProfileIds = [];
        root.startWifiAction(network, "forget", payload);
    }

    function connectHiddenWifi(request) {
        if (root.wifiBusy) return;
        root.startWifiAction(null, "connect", { ssid: request.ssid, security: request.security,
            password: request.password, device: request.device, hidden: true, autoconnect: request.autoconnect });
    }

    function activateSavedWifi(profile, device = "") {
        root.startWifiAction(null, "activate", { ssid: profile.ssid, uuid: profile.uuid, device: device });
    }

    function setSavedWifiAutoconnect(profile, enabled) {
        root.startWifiAction(null, "set-autoconnect", { ssid: profile.ssid, uuid: profile.uuid, enabled: enabled });
    }

    function forgetSavedWifi(profile, confirmed = false) {
        if (!confirmed) return;
        root.startWifiAction(null, "forget", { ssid: profile.ssid, uuids: [profile.uuid] });
    }

    function clearWifiPageFeedback() { root.wifiPageError = ""; root.wifiPageMessage = ""; }

    function startWifiAction(network, action, payload) {
        if (root.wifiBusy) return;
        if (network) {
            network.askingPassword = false;
            network.connectionError = "";
        }
        root.clearWifiPageFeedback();
        root.wifiConnectTarget = action === "connect" || action === "activate" ? network : null;
        root.wifiActionTarget = network;
        root.wifiAction = action;
        wifiActionProc.result = "";
        // Secrets go only to an anonymous stdin pipe, never command arguments,
        // environment variables, temporary files, or console messages.
        wifiActionProc.payload = JSON.stringify(payload);
        wifiActionProc.stdinEnabled = true;
        wifiActionProc.exec(["python3", "-B", root.wifiProfilesScript, action]);
    }

    function refreshWifiProfiles() { wifiProfilesRefresh.restart(); }

    function openPublicWifiPortal() {
        Quickshell.execDetached(["xdg-open", "https://nmcheck.gnome.org/"]) // From some StackExchange thread, seems to work
    }

    function changePassword(network: WifiAccessPoint, password: string): void {
        if (!network || root.wifiBusy) return;
        if (!password.length) {
            network.connectionError = "Enter the Wi-Fi password.";
            network.askingPassword = true;
            return;
        }
        root.connectToWifiNetwork(network, password);
    }

    Process {
        id: enableWifiProc
    }

    Process {
        id: wifiActionProc
        property string payload: ""
        property string result: ""
        onRunningChanged: {
            if (running) {
                write(payload);
                payload = "";
                stdinEnabled = false;
            }
        }
        stdout: StdioCollector { onStreamFinished: wifiActionProc.result = text }
        onExited: (exitCode, exitStatus) => {
            let error = "The Wi-Fi action could not be completed. Refresh and try again.";
            let code = "";
            try {
                const response = JSON.parse(result);
                error = exitCode === 0 && exitStatus === 0 && response.ok ? "" : (response.error || error);
                code = response.code || "";
            } catch (_) {}
            if (root.wifiActionTarget) {
                root.wifiActionTarget.connectionError = error;
                root.wifiActionTarget.askingPassword = !!error &&
                    ["password-required", "invalid-password", "authentication"].includes(code);
            }
            root.wifiPageError = error;
            root.wifiPageMessage = error ? "" : (root.wifiAction === "connect" || root.wifiAction === "activate"
                ? "Wi-Fi connected." : "Wi-Fi settings updated.");
            payload = "";
            result = "";
            root.wifiConnectTarget = null;
            root.wifiActionTarget = null;
            root.wifiAction = "";
            root.update();
        }
    }

    Timer {
        id: wifiProfilesRefresh
        interval: 250
        onTriggered: {
            if (wifiProfilesProc.running) restart();
            else wifiProfilesProc.running = true;
        }
    }
    Process {
        id: wifiProfilesProc
        running: true
        property string result: ""
        command: ["python3", "-B", root.wifiProfilesScript, "list-details"]
        onRunningChanged: if (running) result = ""
        stdout: StdioCollector { onStreamFinished: wifiProfilesProc.result = text }
        onExited: (exitCode, exitStatus) => {
            let failure = "Could not load saved networks. Check that NetworkManager and GLib/GIO are available.";
            try {
                const response = JSON.parse(result);
                if (exitCode !== 0 || !response.ok || !Array.isArray(response.profiles)) {
                    failure = response.error || failure;
                    throw new Error();
                }
                root.savedWifiProfiles = response.profiles;
                root.wifiAdapters = response.adapters || [];
                root.wifiProfilesError = "";
            } catch (_) {
                root.savedWifiProfiles = [];
                root.wifiAdapters = [];
                root.wifiProfilesError = failure;
            }
        }
    }

    Process {
        id: rescanProcess
        command: ["nmcli", "dev", "wifi", "list", "--rescan", "yes"]
        onExited: {
            root.wifiScanning = false;
            getNetworks.running = true;
        }
    }

    // Read-only diagnostics intentionally exclude network names, addresses,
    // profile identifiers, process environment values, and credentials.
    IpcHandler {
        target: "network"
        function refreshBackendStatus(): void { root.refreshWifiProfiles(); }
        function backendStatus(): string {
            return JSON.stringify({ loading: root.wifiProfilesLoading,
                savedProfileCount: root.savedWifiProfiles.length,
                adapterCount: root.wifiAdapters.length, error: root.wifiProfilesError,
                ethernetConnected: root.ethernet, wifiConnected: root.wifi,
                wiredNameAvailable: root.wiredConnectionName.length > 0,
                wifiNameAvailable: (root.activeWifiName || root.wifiConnectionName).length > 0,
                liveSsidAvailable: root.activeWifiName.length > 0 });
        }
    }

    // Status update
    function update() {
        updateConnectionType.startCheck();
        wifiStatusProcess.running = true
        updateNetworkStrength.running = true;
        getNetworks.running = true;
        root.refreshWifiProfiles();
    }

    Process {
        id: subscriber
        running: true
        command: ["nmcli", "monitor"]
        stdout: SplitParser {
            onRead: root.update()
        }
    }

    Process {
        id: updateConnectionType
        property string snapshot: ""
        property bool refreshAgain: false
        command: ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"]
        environment: ({ LANG: "C", LC_ALL: "C" })
        running: true
        function startCheck() {
            // Do not clear an in-flight result when NM emits a burst of events.
            if (running) { refreshAgain = true; return; }
            snapshot = "";
            running = true;
        }
        stdout: StdioCollector { onStreamFinished: updateConnectionType.snapshot = text }
        onExited: (exitCode, exitStatus) => {
            const state = WifiConnection.activeConnectionInfo(exitCode === 0 ? snapshot : "");
            root.wiredConnectionName = state.ethernetName;
            root.wifiConnectionName = state.wifiName;
            root.wifiDevice = state.wifiDevice;
            root.ethernet = state.ethernet;
            root.wifi = state.wifi;
            if (refreshAgain) {
                refreshAgain = false;
                Qt.callLater(updateConnectionType.startCheck);
            }
        }
    }

    Process {
        id: updateNetworkStrength
        running: true
        command: ["sh", "-c", "nmcli -f IN-USE,SIGNAL,SSID device wifi | awk '/^\*/{if (NR!=1) {print $2}}'"]
        stdout: SplitParser {
            onRead: data => {
                root.networkStrength = parseInt(data);
            }
        }
    }

    Process {
        id: wifiStatusProcess
        command: ["nmcli", "radio", "wifi"]
        Component.onCompleted: running = true
        environment: ({
            LANG: "C",
            LC_ALL: "C"
        })
        stdout: StdioCollector {
            onStreamFinished: {
                root.wifiEnabled = text.trim() === "enabled";
            }
        }
    }

    Process {
        id: getNetworks
        running: true
        command: ["nmcli", "-g", "ACTIVE,SIGNAL,FREQ,SSID,BSSID,SECURITY,DEVICE", "device", "wifi", "list", "--rescan", "no"]
        environment: ({
            LANG: "C",
            LC_ALL: "C"
        })
        stdout: StdioCollector {
            onStreamFinished: {
                const allNetworks = text.trim().split("\n").map(n => {
                    const net = WifiConnection.splitFields(n);
                    return {
                        active: net[0] === "yes",
                        strength: parseInt(net[1]),
                        frequency: parseInt(net[2]),
                        ssid: net[3],
                        bssid: net[4] || "",
                        security: net[5] || "",
                        device: net[6] || ""
                    };
                }).filter(n => n.ssid && n.ssid.length > 0);

                // Group networks by SSID and prioritize connected ones
                const networkMap = new Map();
                for (const network of allNetworks) {
                    const existing = networkMap.get(network.ssid);
                    if (!existing) {
                        networkMap.set(network.ssid, network);
                    } else {
                        // Prioritize active/connected networks
                        if (network.active && !existing.active) {
                            networkMap.set(network.ssid, network);
                        } else if (!network.active && !existing.active) {
                            // If both are inactive, keep the one with better signal
                            if (network.strength > existing.strength) {
                                networkMap.set(network.ssid, network);
                            }
                        }
                        // If existing is active and new is not, keep existing
                    }
                }

                const wifiNetworks = Array.from(networkMap.values());
                root.wifiScanSnapshot = wifiNetworks;

                const rNetworks = root.wifiNetworks;

                // Keep the row stable while connecting or entering a password,
                // including when a scan temporarily loses the AP or selects another BSSID.
                const destroyed = rNetworks.filter(rn => rn !== root.wifiConnectTarget && rn !== root.wifiActionTarget &&
                    !rn.askingPassword && !rn.confirmingForget && !rn.connectionError && !wifiNetworks.some(n => n.ssid === rn.ssid));
                for (const network of destroyed)
                    rNetworks.splice(rNetworks.indexOf(network), 1).forEach(n => n.destroy());

                for (const network of wifiNetworks) {
                    const match = rNetworks.find(n => n.ssid === network.ssid);
                    if (match) {
                        const becameActive = network.active && !match.active;
                        match.lastIpcObject = network;
                        if (becameActive) {
                            match.askingPassword = false;
                            match.connectionError = "";
                        }
                    } else {
                        rNetworks.push(apComp.createObject(root, {
                            lastIpcObject: network
                        }));
                    }
                }
            }
        }
    }

    Component {
        id: apComp

        WifiAccessPoint {}
    }
}

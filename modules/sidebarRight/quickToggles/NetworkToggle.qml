import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions
import "../"
import qs
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

QuickToggleButton {
    toggled: Network.wifiEnabled
    buttonIcon: Network.materialSymbol
    onClicked: Network.toggleWifi()
    altAction: () => {
        Quickshell.execDetached(["bash", "-c", `${Network.ethernet ? Config.options.apps.networkEthernet : Config.options.apps.network}`])
        GlobalStates.sidebarRightOpen = false
    }
    StyledToolTip {
        objectName: "networkStatusTooltip"
        textFormat: Text.PlainText // SSIDs and profile names are untrusted text, not markup.
        text: {
            const lines = [];
            if (Network.ethernet)
                lines.push(Translation.tr("Ethernet: %1").arg(Network.wiredConnectionName || Translation.tr("Connected")));
            if (Network.wifi)
                lines.push(Translation.tr("Wi-Fi: %1").arg(Network.activeWifiName || Network.wifiConnectionName || Translation.tr("Connected")));
            if (!lines.length)
                lines.push(Network.wifiEnabled ? Translation.tr("Wi-Fi: Not connected") : Translation.tr("Wi-Fi: Off"));
            lines.push(Translation.tr("Right-click to configure"));
            return lines.join("\n");
        }
    }
}

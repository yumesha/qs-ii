import qs
import qs.services
import qs.services.network
import qs.modules.common
import qs.modules.common.widgets
import QtQuick
import QtQuick.Layouts
import Quickshell

WindowDialog {
    id: root
    property string page: "available"
    onPageChanged: {
        Network.clearWifiPageFeedback();
        if (page === "saved") Network.refreshWifiProfiles();
    }
    Connections {
        target: root
        function onShowChanged() {
            if (!root.show) {
                hiddenForm.clearPrivateFields();
                root.page = "available";
            }
        }
    }

    WindowDialogTitle {
        text: root.page === "hidden" ? Translation.tr("Connect to hidden Wi-Fi")
            : root.page === "saved" ? Translation.tr("Network settings") : Translation.tr("Connect to Wi-Fi")
    }
    WindowDialogSeparator { visible: !Network.wifiScanning && !Network.wifiBusy }
    StyledIndeterminateProgressBar {
        visible: Network.wifiScanning || Network.wifiBusy
        Layout.fillWidth: true
        Layout.topMargin: -8
        Layout.bottomMargin: -8
        Layout.leftMargin: -Appearance.rounding.large
        Layout.rightMargin: -Appearance.rounding.large
    }
    StyledText {
        Layout.fillWidth: true
        visible: root.page !== "available" && (Network.wifiPageError.length > 0 || Network.wifiPageMessage.length > 0 || Network.wifiProfilesError.length > 0)
        text: Translation.tr(Network.wifiPageError || Network.wifiProfilesError || Network.wifiPageMessage)
        wrapMode: Text.WordWrap
        color: Network.wifiPageError || Network.wifiProfilesError ? Appearance.m3colors.m3error : Appearance.colors.colSubtext
        font.pixelSize: Appearance.font.pixelSize.small
    }
    ListView {
        visible: root.page === "available"
        Layout.fillHeight: true
        Layout.fillWidth: true
        Layout.topMargin: -15
        Layout.bottomMargin: -16
        Layout.leftMargin: -Appearance.rounding.large
        Layout.rightMargin: -Appearance.rounding.large
        clip: true
        spacing: 0
        model: ScriptModel {
            values: [...Network.wifiNetworks].sort((a, b) => {
                if (a.active && !b.active) return -1;
                if (!a.active && b.active) return 1;
                return b.strength - a.strength;
            })
        }
        delegate: WifiNetworkItem {
            required property WifiAccessPoint modelData
            wifiNetwork: modelData
            anchors.left: parent?.left
            anchors.right: parent?.right
        }
    }
    HiddenWifiForm {
        id: hiddenForm
        visible: root.page === "hidden"
        Layout.fillHeight: true
        Layout.fillWidth: true
    }
    SavedWifiNetworks {
        visible: root.page === "saved"
        Layout.fillHeight: true
        Layout.fillWidth: true
    }
    WindowDialogSeparator {}
    WindowDialogButtonRow {
        DialogButton {
            buttonText: root.page === "available" ? Translation.tr("Details") : Translation.tr("Back")
            onClicked: root.page = root.page === "available" ? "saved" : "available"
        }
        DialogButton {
            buttonText: root.page === "hidden" ? Translation.tr("Saved") : Translation.tr("Hidden…")
            onClicked: root.page = root.page === "hidden" ? "saved" : "hidden"
        }
        Item { Layout.fillWidth: true }
        DialogButton {
            buttonText: Translation.tr("Done")
            onClicked: root.dismiss()
        }
    }
}

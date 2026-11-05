import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import QtQuick
import QtQuick.Layouts

ListView {
    id: root
    property string selectedDevice: ""
    property var pendingForget: null
    clip: true
    spacing: 12
    model: Network.savedWifiProfiles
    onVisibleChanged: if (!visible) pendingForget = null

    header: ColumnLayout {
        width: root.width
        spacing: 10
        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Saved Wi-Fi profiles, including networks that are currently out of range.")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colSubtext
        }
        StyledText {
            Layout.fillWidth: true
            visible: Network.wifiProfilesLoading || Network.savedWifiProfiles.length === 0
            text: Network.wifiProfilesLoading ? Translation.tr("Loading saved networks…") : Translation.tr("No saved Wi-Fi networks.")
            wrapMode: Text.WordWrap
        }
        ConfigSelectionArray {
            visible: Network.wifiAdapters.length > 1
            currentValue: root.selectedDevice
            options: Network.wifiAdapters.map(adapter => ({displayName: adapter.device, value: adapter.device}))
            onSelected: value => root.selectedDevice = value
        }
        Item { Layout.preferredHeight: 4 }
    }

    delegate: Rectangle {
        id: row
        required property var modelData
        readonly property bool confirming: root.pendingForget?.uuid === modelData.uuid
        width: root.width
        height: content.implicitHeight + 20
        radius: Appearance.rounding.small
        color: Appearance.colors.colLayer2
        ColumnLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 8
            StyledText {
                Layout.fillWidth: true
                text: row.modelData.name || row.modelData.ssid
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                font.weight: Font.Medium
            }
            StyledText {
                Layout.fillWidth: true
                visible: row.modelData.name !== row.modelData.ssid
                text: row.modelData.ssid
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: Appearance.colors.colSubtext
            }
            StyledText {
                Layout.fillWidth: true
                text: (row.modelData.active ? Translation.tr("Connected") : Translation.tr("Saved")) +
                    (row.modelData.hidden ? " · " + Translation.tr("Hidden network") : "")
                wrapMode: Text.WordWrap
                color: Appearance.colors.colSubtext
                font.pixelSize: Appearance.font.pixelSize.small
            }
            RowLayout {
                visible: !row.confirming
                Layout.fillWidth: true
                DialogButton {
                    buttonText: Translation.tr("Connect")
                    enabled: !Network.wifiBusy && Network.wifiEnabled && !row.modelData.active &&
                        (Network.wifiAdapters.length <= 1 || root.selectedDevice.length > 0)
                    onClicked: Network.activateSavedWifi(row.modelData, root.selectedDevice)
                }
                DialogButton {
                    buttonText: Translation.tr("Forget")
                    enabled: !Network.wifiBusy
                    onClicked: root.pendingForget = {uuid: row.modelData.uuid, ssid: row.modelData.ssid}
                }
                Item { Layout.fillWidth: true }
            }
            DialogButton {
                visible: !row.confirming
                buttonText: row.modelData.autoconnect ? Translation.tr("Auto-connect: On") : Translation.tr("Auto-connect: Off")
                enabled: !Network.wifiBusy
                onClicked: Network.setSavedWifiAutoconnect(row.modelData, !row.modelData.autoconnect)
            }
            StyledText {
                Layout.fillWidth: true
                visible: row.modelData.hidden && !row.confirming
                text: Translation.tr("Auto-connect may send probes containing this hidden network's name.")
                wrapMode: Text.WordWrap
                color: Appearance.colors.colSubtext
                font.pixelSize: Appearance.font.pixelSize.small
            }
            StyledText {
                Layout.fillWidth: true
                visible: row.confirming
                text: Translation.tr("Forget this saved profile and its password? Its Wi-Fi connection will disconnect if active. Ethernet is unaffected.")
                wrapMode: Text.WordWrap
            }
            RowLayout {
                visible: row.confirming
                Layout.fillWidth: true
                DialogButton {
                    buttonText: Translation.tr("Cancel")
                    onClicked: root.pendingForget = null
                }
                DialogButton {
                    buttonText: Translation.tr("Forget network")
                    colEnabled: Appearance.m3colors.m3error
                    enabled: !Network.wifiBusy
                    onClicked: {
                        Network.forgetSavedWifi(root.pendingForget, true);
                        root.pendingForget = null;
                    }
                }
            }
        }
    }
}

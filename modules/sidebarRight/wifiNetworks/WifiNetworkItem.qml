import qs
import qs.modules.common
import qs.modules.common.widgets
import qs.services
import qs.services.network
import QtQuick
import QtQuick.Layouts

DialogListItem {
    id: root
    required property WifiAccessPoint wifiNetwork
    property bool passwordVisible: false
    readonly property bool connecting: Network.wifiConnecting && Network.wifiConnectTarget === wifiNetwork
    readonly property bool acting: Network.wifiBusy && Network.wifiActionTarget === wifiNetwork
    readonly property var savedProfiles: Network.savedWifiProfiles.filter(profile => profile.ssid === root.wifiNetwork?.ssid)

    function requestForget() {
        if (Network.wifiBusy || !root.savedProfiles.length) return;
        root.wifiNetwork.forgetProfileIds = root.savedProfiles.map(profile => profile.uuid);
        root.wifiNetwork.askingPassword = false;
        root.wifiNetwork.connectionError = "";
        root.wifiNetwork.confirmingForget = true;
    }

    function cancelForget() {
        if (!root.wifiNetwork) return;
        root.wifiNetwork.confirmingForget = false;
        root.wifiNetwork.forgetProfileIds = [];
    }

    onVisibleChanged: if (!visible) { root.cancelForget(); root.passwordVisible = false; }

    function clearPassword() {
        root.passwordVisible = false;
        passwordField.clear();
    }
    function submitPassword() {
        if (Network.wifiBusy || !passwordField.text.length) return;
        Network.changePassword(root.wifiNetwork, passwordField.text);
        root.clearPassword();
    }

    active: (wifiNetwork?.askingPassword || wifiNetwork?.active || wifiNetwork?.confirmingForget) ?? false
    onClicked: {
        if (!Network.wifiBusy && !wifiNetwork?.askingPassword && !wifiNetwork?.confirmingForget)
            Network.requestWifiConnection(wifiNetwork);
    }

    contentItem: ColumnLayout {
        anchors {
            fill: parent
            topMargin: root.verticalPadding
            bottomMargin: root.verticalPadding
            leftMargin: root.horizontalPadding
            rightMargin: root.horizontalPadding
        }
        spacing: 0

        RowLayout {
            // Name
            spacing: 10
            MaterialSymbol {
                iconSize: Appearance.font.pixelSize.larger
                property int strength: root.wifiNetwork?.strength ?? 0
                text: strength > 80 ? "signal_wifi_4_bar" : strength > 60 ? "network_wifi_3_bar" : strength > 40 ? "network_wifi_2_bar" : strength > 20 ? "network_wifi_1_bar" : "signal_wifi_0_bar"
                color: Appearance.colors.colOnSurfaceVariant
            }
            StyledText {
                Layout.fillWidth: true
                color: Appearance.colors.colOnSurfaceVariant
                elide: Text.ElideRight
                text: root.wifiNetwork?.ssid ?? Translation.tr("Unknown")
                textFormat: Text.PlainText
            }
            MaterialSymbol {
                visible: (root.wifiNetwork?.isSecure || root.wifiNetwork?.active) ?? false
                text: root.wifiNetwork?.active ? "check" : Network.wifiConnectTarget === root.wifiNetwork ? "settings_ethernet" : "lock"
                iconSize: Appearance.font.pixelSize.larger
                color: Appearance.colors.colOnSurfaceVariant
            }
        }

        StyledText {
            Layout.fillWidth: true
            Layout.topMargin: 6
            visible: root.wifiNetwork?.active ?? false
            text: Network.ethernet
                ? Translation.tr("Wi-Fi connected · Ethernet also connected")
                : Translation.tr("Wi-Fi connected")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colSubtext
            font.pixelSize: Appearance.font.pixelSize.small
        }

        StyledText {
            Layout.fillWidth: true
            Layout.topMargin: 6
            visible: root.connecting || root.acting || (root.wifiNetwork?.connectionError.length ?? 0) > 0
            text: root.connecting ? Translation.tr("Connecting…")
                : root.acting ? (Network.wifiAction === "forget" ? Translation.tr("Forgetting…") : Translation.tr("Disconnecting…"))
                : Translation.tr(root.wifiNetwork?.connectionError ?? "")
            wrapMode: Text.WordWrap
            color: root.connecting || root.acting ? Appearance.colors.colSubtext : Appearance.m3colors.m3error
            font.pixelSize: Appearance.font.pixelSize.small
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            visible: !root.wifiNetwork?.confirmingForget && ((root.wifiNetwork?.active ?? false) || root.savedProfiles.length > 0)

            DialogButton {
                buttonText: Translation.tr("Disconnect")
                visible: root.wifiNetwork?.active ?? false
                enabled: !Network.wifiBusy
                onClicked: Network.disconnectWifiNetwork(root.wifiNetwork)
                StyledToolTip { text: Translation.tr("Disconnect Wi-Fi but keep its saved password. Ethernet is unaffected.") }
            }
            DialogButton {
                buttonText: Translation.tr("Forget")
                visible: root.savedProfiles.length > 0
                enabled: !Network.wifiBusy && !Network.wifiProfilesLoading
                onClicked: root.requestForget()
            }
            Item { Layout.fillWidth: true }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: 8
            visible: root.wifiNetwork?.confirmingForget ?? false
            StyledText {
                Layout.fillWidth: true
                text: Translation.tr("Forget this network?")
                font.weight: Font.Medium
            }
            StyledText {
                Layout.fillWidth: true
                text: Translation.tr("Remove %1 saved Wi-Fi profile(s) and their passwords. If connected, this Wi-Fi will disconnect. Ethernet is unaffected.")
                    .arg(root.wifiNetwork?.forgetProfileIds.length ?? 0)
                wrapMode: Text.WordWrap
                color: Appearance.colors.colSubtext
                font.pixelSize: Appearance.font.pixelSize.small
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                DialogButton {
                    buttonText: Translation.tr("Cancel")
                    onClicked: root.cancelForget()
                }
                DialogButton {
                    buttonText: Translation.tr("Forget network")
                    colEnabled: Appearance.m3colors.m3error
                    enabled: !Network.wifiBusy
                    onClicked: Network.forgetWifiNetwork(root.wifiNetwork)
                }
            }
        }

        ColumnLayout { // Password
            id: passwordPrompt
            Layout.topMargin: 8
            visible: root.wifiNetwork?.askingPassword ?? false
            enabled: !Network.wifiBusy
            onVisibleChanged: if (!visible) root.clearPassword()

            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                MaterialTextField {
                    id: passwordField
                    objectName: "wifiPassword"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    placeholderText: Translation.tr("Password")
                    echoMode: root.passwordVisible ? TextInput.Normal : TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    onTextChanged: if (!text.length) root.passwordVisible = false
                    onAccepted: root.submitPassword()
                }
                DialogButton {
                    objectName: "wifiPasswordVisibility"
                    focusPolicy: Qt.TabFocus // Mouse reveal should not steal the text cursor.
                    buttonText: root.passwordVisible ? Translation.tr("Hide") : Translation.tr("Show")
                    Accessible.name: root.passwordVisible ? Translation.tr("Hide password") : Translation.tr("Show password")
                    enabled: !Network.wifiBusy && passwordField.text.length > 0
                    onEnabledChanged: if (!enabled) root.passwordVisible = false
                    onClicked: root.passwordVisible = !root.passwordVisible
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Item {
                    Layout.fillWidth: true
                }

                DialogButton {
                    objectName: "wifiPasswordCancel"
                    buttonText: Translation.tr("Cancel")
                    onClicked: {
                        root.wifiNetwork.askingPassword = false;
                        root.wifiNetwork.connectionError = "";
                        root.clearPassword();
                    }
                }

                DialogButton {
                    buttonText: Translation.tr("Use saved")
                    visible: root.savedProfiles.length > 0
                    enabled: !Network.wifiBusy
                    onClicked: {
                        Network.connectToWifiNetwork(root.wifiNetwork);
                        root.clearPassword();
                    }
                }

                DialogButton {
                    buttonText: Translation.tr("Connect")
                    enabled: passwordField.text.length > 0 && !Network.wifiBusy
                    onClicked: root.submitPassword()
                }
            }
        }

        ColumnLayout { // Public wifi login page
            id: publicWifiPortal
            Layout.topMargin: 8
            visible: (root.wifiNetwork?.active && (root.wifiNetwork?.security ?? "").trim().length === 0) ?? false

            RowLayout {
                DialogButton {
                    Layout.fillWidth: true
                    buttonText: Translation.tr("Open network portal")
                    colBackground: Appearance.colors.colLayer4
                    colBackgroundHover: Appearance.colors.colLayer4Hover
                    colRipple: Appearance.colors.colLayer4Active
                    onClicked: {
                        Network.openPublicWifiPortal()
                        GlobalStates.sidebarRightOpen = false
                    }
                }
            }
        }

        Item {
            Layout.fillHeight: true
        }
    }
}

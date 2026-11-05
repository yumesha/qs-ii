import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string security: "wpa-psk"
    property string selectedDevice: ""
    property bool autoConnect: false
    property bool passwordVisible: false

    function clearPassword() {
        root.passwordVisible = false;
        passwordField.clear();
    }
    function clearPrivateFields() {
        ssidField.clear();
        root.clearPassword();
    }
    onVisibleChanged: if (!visible) clearPrivateFields()
    Component.onDestruction: clearPrivateFields()

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Flickable {
            id: viewport
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: form.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ColumnLayout {
                id: form
                width: viewport.width
                spacing: 10
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Enter the exact network name. Personal or open Wi-Fi only; enterprise setup needs a dedicated editor.")
                    wrapMode: Text.WordWrap
                    color: Appearance.colors.colSubtext
                    font.pixelSize: Appearance.font.pixelSize.small
                }
                MaterialTextField {
                    id: ssidField
                    objectName: "hiddenWifiSsid"
                    Layout.fillWidth: true
                    placeholderText: Translation.tr("Network name (SSID)")
                    inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    enabled: !Network.wifiBusy
                }
                StyledText { text: Translation.tr("Security") }
                ConfigSelectionArray {
                    currentValue: root.security
                    enabled: !Network.wifiBusy
                    options: [
                        {displayName: "WPA/WPA2", value: "wpa-psk"},
                        {displayName: "WPA3", value: "sae"},
                        {displayName: Translation.tr("Open"), value: "open"}
                    ]
                    onSelected: value => { root.security = value; root.clearPassword(); }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: root.security !== "open"
                    onVisibleChanged: if (!visible) root.clearPassword()
                    MaterialTextField {
                        id: passwordField
                        objectName: "hiddenWifiPassword"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        placeholderText: Translation.tr("Password")
                        enabled: !Network.wifiBusy
                        echoMode: root.passwordVisible ? TextInput.Normal : TextInput.Password
                        inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                        onTextChanged: if (!text.length) root.passwordVisible = false
                    }
                    DialogButton {
                        objectName: "hiddenWifiPasswordVisibility"
                        focusPolicy: Qt.TabFocus // Mouse reveal should not steal the text cursor.
                        buttonText: root.passwordVisible ? Translation.tr("Hide") : Translation.tr("Show")
                        Accessible.name: root.passwordVisible ? Translation.tr("Hide password") : Translation.tr("Show password")
                        enabled: !Network.wifiBusy && passwordField.text.length > 0
                        onEnabledChanged: if (!enabled) root.passwordVisible = false
                        onClicked: root.passwordVisible = !root.passwordVisible
                    }
                }
                StyledText {
                    visible: Network.wifiAdapters.length > 1
                    text: Translation.tr("Wi-Fi adapter")
                }
                ConfigSelectionArray {
                    visible: Network.wifiAdapters.length > 1
                    currentValue: root.selectedDevice
                    enabled: !Network.wifiBusy
                    options: Network.wifiAdapters.map(adapter => ({displayName: adapter.device, value: adapter.device}))
                    onSelected: value => root.selectedDevice = value
                }
                ConfigSwitch {
                    text: Translation.tr("Connect automatically")
                    buttonIcon: "wifi"
                    checked: root.autoConnect
                    enabled: !Network.wifiBusy
                    onCheckedChanged: root.autoConnect = checked
                }
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Hidden names may be sent in Wi-Fi probes. Auto-connect is off by default. Saved passwords stay with NetworkManager.")
                    wrapMode: Text.WordWrap
                    font.pixelSize: Appearance.font.pixelSize.small
                    color: Appearance.colors.colSubtext
                }
                StyledText {
                    Layout.fillWidth: true
                    visible: !Network.wifiEnabled
                    text: Translation.tr("Turn on Wi-Fi before connecting.")
                    color: Appearance.m3colors.m3error
                    wrapMode: Text.WordWrap
                }
            }
        }
        DialogButton {
            objectName: "hiddenWifiConnect"
            Layout.alignment: Qt.AlignRight
            buttonText: Network.wifiBusy ? Translation.tr("Connecting…") : Translation.tr("Connect")
            enabled: Network.wifiEnabled && !Network.wifiBusy && ssidField.text.length > 0 &&
                (root.security === "open" || passwordField.text.length > 0) &&
                (Network.wifiAdapters.length <= 1 || root.selectedDevice.length > 0)
            onClicked: {
                Network.connectHiddenWifi({ssid: ssidField.text, password: passwordField.text,
                    security: root.security, device: root.selectedDevice, autoconnect: root.autoConnect});
                root.clearPassword();
            }
        }
    }
}

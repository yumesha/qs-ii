import qs.modules.common
import qs.modules.common.functions
import "./notification_utils.js" as NotificationUtils
import Qt5Compat.GraphicalEffects
import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.Notifications

Rectangle {
    id: root
    property var appIcon: ""
    property string appName: ""
    property var summary: ""
    property var urgency: NotificationUrgency.Normal
    property var image: ""
    property real scale: 1
    property real size: 38 * scale
    property real materialIconScale: 0.57
    property real appIconScale: 0.8
    property real smallAppIconScale: 0.49
    property real materialIconSize: size * materialIconScale
    property real appIconSize: size * appIconScale
    property real smallAppIconSize: size * smallAppIconScale

    readonly property string appIconSource: NotificationUtils.resolveAppIcon(root.appIcon,
        name => Quickshell.iconPath(name, true))
    readonly property string notificationImageSource: {
        const value = String(root.image || "");
        if (value.startsWith("image://icon/"))
            return NotificationUtils.resolveAppIcon(value, name => Quickshell.iconPath(name, true));
        if (value.startsWith("/")) return NotificationUtils.localImageUrl(value);
        return value;
    }
    readonly property bool imageReady: notifImage.status === Image.Ready
    readonly property bool appIconReady: appIconImage.status === Image.Ready
    readonly property string fallbackSymbol: {
        const guessed = NotificationUtils.findSuitableMaterialSymbol(root.summary, root.appName);
        return root.urgency == NotificationUrgency.Critical && guessed === "chat" ? "release_alert" : guessed;
    }

    implicitWidth: size
    implicitHeight: size
    radius: Appearance.rounding.full
    color: Appearance.colors.colSecondaryContainer

    MaterialSymbol {
        anchors.fill: parent
        visible: !root.imageReady && !root.appIconReady
        text: root.fallbackSymbol
        color: root.urgency == NotificationUrgency.Critical
            ? ColorUtils.mix(Appearance.m3colors.m3onSecondary, Appearance.m3colors.m3onSecondaryContainer, 0.1)
            : Appearance.m3colors.m3onSecondaryContainer
        iconSize: root.materialIconSize
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    Image {
        id: notifImage
        anchors.fill: parent
        visible: root.imageReady
        source: root.notificationImageSource
        fillMode: Image.PreserveAspectCrop
        cache: false
        antialiasing: true
        asynchronous: true
        sourceSize.width: root.width
        sourceSize.height: root.height
        layer.enabled: root.imageReady
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: root.width
                height: root.height
                radius: Appearance.rounding.full
            }
        }
    }

    IconImage {
        id: appIconImage
        visible: root.appIconReady
        source: root.appIconSource
        implicitSize: root.imageReady ? root.smallAppIconSize : root.appIconSize
        x: root.imageReady ? root.width - width : (root.width - width) / 2
        y: root.imageReady ? root.height - height : (root.height - height) / 2
        asynchronous: true
    }
}

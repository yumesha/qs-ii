import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions
import QtQuick
import Quickshell
import Quickshell.Services.SystemTray
import Quickshell.Widgets
import Qt5Compat.GraphicalEffects

MouseArea {
    id: root
    required property SystemTrayItem item
    property bool targetMenuOpen: false
    readonly property string fallbackSymbol: {
        const id = root.item.id.toLowerCase();
        if (id === "fcitx" || id === "fcitx5") return "keyboard";
        if (id === "udiskie") return "usb";
        return "";
    }
    readonly property bool missingThemeIcon: {
        const url = String(root.item.icon);
        // App-provided pixmaps and private icon directories must stay intact.
        if (!root.fallbackSymbol || !url.startsWith("image://icon/") || url.includes("path=")) return false;
        const name = decodeURIComponent(url.slice("image://icon/".length).split("?")[0]);
        return !name || Quickshell.iconPath(name, true).length === 0;
    }
    readonly property bool usingFallback: fallbackSymbol.length > 0 &&
        (!root.item.icon || missingThemeIcon || trayIcon.status === Image.Error)

    signal menuOpened(qsWindow: var)
    signal menuClosed()

    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    implicitWidth: 20
    implicitHeight: 20
    onPressed: (event) => {
        switch (event.button) {
        case Qt.LeftButton:
            item.activate();
            break;
        case Qt.RightButton:
            if (item.hasMenu) menu.open();
            break;
        }
        event.accepted = true;
    }
    onEntered: {
        tooltip.text = item.tooltipTitle.length > 0 ? item.tooltipTitle
                : (item.title.length > 0 ? item.title : item.id);
        if (item.tooltipDescription.length > 0) tooltip.text += " • " + item.tooltipDescription;
        if (Config.options.bar.tray.showItemId) tooltip.text += "\n[" + item.id + "]";
    }

    Loader {
        id: menu
        function open() {
            menu.active = true;
        }
        active: false
        sourceComponent: SysTrayMenu {
            Component.onCompleted: this.open();
            trayItemMenuHandle: root.item.menu
            anchor {
                window: root.QsWindow.window
                rect.x: root.x + (Config.options.bar.vertical ? 0 : QsWindow.window?.width)
                rect.y: root.y + (Config.options.bar.vertical ? QsWindow.window?.height : 0)
                rect.height: root.height
                rect.width: root.width
                edges: Config.options.bar.bottom ? (Edges.Top | Edges.Left) : (Edges.Bottom | Edges.Right)
                gravity: Config.options.bar.bottom ? (Edges.Top | Edges.Left) : (Edges.Bottom | Edges.Right)
            }
            onMenuOpened: (window) => root.menuOpened(window);
            onMenuClosed: {
                root.menuClosed();
                menu.active = false;
            }
        }
    }

    IconImage {
        id: trayIcon
        visible: !root.usingFallback && !Config.options.bar.tray.monochromeIcons
        source: root.missingThemeIcon ? "" : root.item.icon
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
    }

    Loader {
        active: !root.usingFallback && Config.options.bar.tray.monochromeIcons
        anchors.fill: trayIcon
        sourceComponent: Item {
            Desaturate {
                id: desaturatedIcon
                visible: false // There's already color overlay
                anchors.fill: parent
                source: trayIcon
                desaturation: 0.8 // 1.0 means fully grayscale
            }
            ColorOverlay {
                anchors.fill: desaturatedIcon
                source: desaturatedIcon
                color: ColorUtils.transparentize(Appearance.colors.colOnLayer0, 0.9)
            }
        }
    }

    MaterialSymbol {
        anchors.centerIn: parent
        visible: root.usingFallback
        text: root.fallbackSymbol
        iconSize: Math.min(root.width, root.height)
        color: Appearance.colors.colOnLayer0
    }

    PopupToolTip {
        id: tooltip
        extraVisibleCondition: root.containsMouse
        alternativeVisibleCondition: extraVisibleCondition
        anchorEdges: (!Config.options.bar.bottom && !Config.options.bar.vertical) ? Edges.Bottom : Edges.Top
    }

}

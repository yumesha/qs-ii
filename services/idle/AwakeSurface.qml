import QtQuick
import Quickshell
import Quickshell.Wayland

// Complement logind inhibition without taking input or reserving screen space.
PanelWindow {
    id: root
    visible: true
    implicitWidth: 1
    implicitHeight: 1
    exclusiveZone: 0
    color: "transparent"
    WlrLayershell.namespace: "quickshell:keepAwake"
    anchors { right: true; bottom: true }
    mask: Region { item: null }
    IdleInhibitor { enabled: true; window: root }
}

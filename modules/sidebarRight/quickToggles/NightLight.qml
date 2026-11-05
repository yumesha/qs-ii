import QtQuick
import qs.modules.common
import qs.modules.common.widgets
import qs
import qs.services

QuickToggleButton {
    id: nightLightButton
    enabled: Config.ready && !Hyprsunset.applying
    toggled: Hyprsunset.desiredActive
    buttonIcon: Hyprsunset.error ? "error" : Hyprsunset.automatic ? "night_sight_auto" : "bedtime"
    onClicked: Hyprsunset.toggle()
    altAction: () => Hyprsunset.toggleAutomatic()

    StyledToolTip {
        text: Hyprsunset.error || ((Hyprsunset.automatic ? Translation.tr("Night Light: Automatic")
            : Hyprsunset.desiredActive ? Translation.tr("Night Light: Manual on") : Translation.tr("Night Light: Manual off"))
            + "\n" + Translation.tr("Click for manual control | Right-click to toggle Auto"))
    }
}

import qs.modules.common.widgets
import qs
import qs.services

QuickToggleButton {
    id: root
    enabled: Idle.ready && !Idle.busy
    toggled: Idle.inhibit
    buttonIcon: Idle.error ? "error" : "coffee"
    onClicked: Idle.toggleInhibit()
    StyledToolTip {
        text: Idle.error ? Translation.tr(Idle.error)
            : !Idle.ready ? Translation.tr("Restoring keep-awake state…")
            : Idle.inhibit ? Translation.tr("Keep awake: On\nAutomatic locking, screen-off and idle suspend are inhibited. Manual lock still works.")
            : Translation.tr("Keep awake: Off")
    }
}

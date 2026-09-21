import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import "../common/functions/VideoWallpaperPolicy.js" as Policy

ContentPage {
    id: root
    forceWidth: true
    baseWidth: Math.min(600, Math.max(280, width - 40))
    readonly property var options: Config.options.background.video
    property string selectedWorkspace: ""
    readonly property var selectedWallpaper: Wallpapers.forWorkspace(selectedWorkspace)
    readonly property bool hasVideo: Policy.isVideo(selectedWallpaper.path)
    readonly property var workspaceChoices: {
        let names = Array.from({length: 10}, (_, index) => String(index + 1));
        for (const workspace of HyprlandData.workspaces) {
            names.push(Policy.workspaceKey(workspace));
        }
        for (const entry of Config.options.background.workspaceWallpapers) names.push(String(entry.workspace));
        names = [...new Set(names)].filter(name => name && !name.startsWith("special:"));
        names.sort((a, b) => {
            const aNumber = /^\d+$/.test(a), bNumber = /^\d+$/.test(b);
            if (aNumber && bNumber) return Number(a) - Number(b);
            if (aNumber !== bNumber) return aNumber ? -1 : 1;
            return a.localeCompare(b);
        });
        return [{displayName: Translation.tr("Default"), value: ""}, ...names.map(name => ({displayName: name, value: name}))];
    }
    property var playbackStatus: []

    function statusText(status) {
        if (status.error) return status.error;
        const reasons = {
            "manual": Translation.tr("Paused by you"),
            "covered": Translation.tr("Paused — fullscreen or maximized window"),
            "window": Translation.tr("Paused — window on this workspace"),
            "locked": Translation.tr("Paused — screen locked"),
            "display-off": Translation.tr("Paused — display off"),
            "battery": Translation.tr("Paused — low battery"),
            "hidden": Translation.tr("Paused — wallpaper hidden"),
            "waiting": Translation.tr("Waiting for display")
        };
        return reasons[status.reason] || (status.playing ? Translation.tr("Playing") : Translation.tr("Loading video…"));
    }

    FileDialog {
        id: videoPicker
        property string workspace: ""
        title: root.selectedWorkspace ? Translation.tr("Choose wallpaper for workspace") + " " + root.selectedWorkspace : Translation.tr("Choose default wallpaper")
        fileMode: FileDialog.OpenFile
        options: FileDialog.DontUseNativeDialog
        currentFolder: Directories.pictures
        nameFilters: [Translation.tr("Wallpapers (*.png *.jpg *.jpeg *.webp *.avif *.bmp *.svg *.mp4 *.webm *.mkv *.mov *.avi *.m4v *.PNG *.JPG *.JPEG *.MP4 *.MOV *.MKV *.WEBM)"), Translation.tr("All files (*)")]
        onAccepted: Wallpapers.applyToWorkspace(Policy.localPath(selectedFile), workspace)
    }

    Process {
        id: queryStatus
        command: ["qs", "-c", "ii", "ipc", "call", "videoWallpaper", "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.playbackStatus = JSON.parse(text); }
                catch (error) { root.playbackStatus = []; }
            }
        }
    }
    Timer {
        interval: 1500
        running: root.visible && root.hasVideo && root.options.enabled
        triggeredOnStart: true
        repeat: true
        onTriggered: if (!queryStatus.running) queryStatus.running = true
    }

    ContentSection {
        icon: "video_file"
        title: Translation.tr("Workspace Wallpapers")

        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Give each workspace its own image or video. Unassigned workspaces use the default wallpaper.")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colSubtext
        }

        ContentSubsection {
            title: Translation.tr("Choose workspace")
            ConfigSelectionArray {
                currentValue: root.selectedWorkspace
                options: root.workspaceChoices
                onSelected: value => { root.selectedWorkspace = value; Wallpapers.lastError = ""; }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            StyledText {
                Layout.fillWidth: true
                text: root.selectedWorkspace
                    ? (root.selectedWallpaper.overridden ? Translation.tr("Custom wallpaper for workspace") : Translation.tr("Using default for workspace")) + " " + root.selectedWorkspace
                    : Translation.tr("Default wallpaper for unassigned workspaces")
                wrapMode: Text.WordWrap
                color: Appearance.colors.colSubtext
                font.pixelSize: Appearance.font.pixelSize.small
            }
            RippleButtonWithIcon {
                materialIcon: "my_location"
                mainText: Translation.tr("Current workspace")
                onClicked: root.selectedWorkspace = Policy.workspaceKey(HyprlandData.activeWorkspace)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 210
            radius: Appearance.rounding.normal
            color: Appearance.colors.colLayer2
            clip: true
            Image {
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                source: Policy.fileUrl(root.hasVideo ? root.selectedWallpaper.thumbnail : root.selectedWallpaper.path)
                sourceSize.width: 600
                sourceSize.height: 210
                asynchronous: true
                cache: false
            }
            Rectangle {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 12
                width: previewLabel.implicitWidth + 24
                height: 32
                radius: 16
                color: Appearance.colors.colLayer1
                StyledText {
                    id: previewLabel
                    anchors.centerIn: parent
                    text: root.hasVideo ? Translation.tr("Video preview") : Translation.tr("Image wallpaper")
                    font.pixelSize: Appearance.font.pixelSize.small
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            text: root.selectedWallpaper.path ? Policy.localPath(root.selectedWallpaper.path).split("/").pop() : Translation.tr("Choose an image or video")
            elide: Text.ElideMiddle
            font.weight: Font.Medium
        }

        RowLayout {
            Layout.fillWidth: true
            RippleButtonWithIcon {
                Layout.fillWidth: true
                materialIcon: "folder_open"
                mainText: Wallpapers.applying ? Translation.tr("Applying…") : Translation.tr("Choose image or video")
                enabled: !Wallpapers.applying
                onClicked: {
                    videoPicker.workspace = root.selectedWorkspace;
                    videoPicker.open();
                }
            }
            RippleButtonWithIcon {
                materialIcon: root.options.paused ? "play_arrow" : "pause"
                mainText: root.options.paused ? Translation.tr("Resume") : Translation.tr("Pause")
                enabled: root.hasVideo && root.options.enabled
                StyledToolTip { text: Translation.tr("Pause or resume video wallpapers on all workspaces.") }
                onClicked: root.options.paused = !root.options.paused
            }
            RippleButtonWithIcon {
                materialIcon: root.selectedWorkspace ? "undo" : "image"
                mainText: root.selectedWorkspace ? Translation.tr("Use default") : Translation.tr("Restore image")
                enabled: !Wallpapers.applying && (root.selectedWorkspace ? root.selectedWallpaper.overridden : root.hasVideo && root.options.lastImagePath.length > 0)
                onClicked: {
                    if (root.selectedWorkspace) Wallpapers.clearWorkspace(root.selectedWorkspace);
                    else Wallpapers.apply(root.options.lastImagePath);
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            visible: Wallpapers.lastError.length > 0
            text: Wallpapers.lastError
            wrapMode: Text.WordWrap
            color: Appearance.m3colors.m3error
        }

        Repeater {
            model: root.hasVideo && root.options.enabled ? root.playbackStatus.filter(status => !root.selectedWorkspace || status.workspace === root.selectedWorkspace) : []
            StyledText {
                required property var modelData
                Layout.fillWidth: true
                text: modelData.monitor + " · " + root.statusText(modelData)
                wrapMode: Text.WordWrap
                color: modelData.error ? Appearance.m3colors.m3error : Appearance.colors.colSubtext
                font.pixelSize: Appearance.font.pixelSize.small
            }
        }

        ConfigSwitch {
            buttonIcon: "play_circle"
            text: Translation.tr("Enable video playback")
            checked: root.options.enabled
            onCheckedChanged: root.options.enabled = checked
            StyledToolTip { text: Translation.tr("When disabled, the video thumbnail stays as your wallpaper.") }
        }
    }

    ContentSection {
        icon: "energy_savings_leaf"
        title: Translation.tr("Smart pause · all video wallpapers")

        ContentSubsection {
            title: Translation.tr("Pause when")
            ConfigSelectionArray {
                currentValue: root.options.pauseMode
                onSelected: value => root.options.pauseMode = value
                options: [
                    { displayName: Translation.tr("Fullscreen / maximized"), value: "covered" },
                    { displayName: Translation.tr("Any visible window"), value: "any-window" },
                    { displayName: Translation.tr("Never for windows"), value: "never" }
                ]
            }
        }
        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Only windows on the visible workspace of each monitor affect playback. It resumes when the desktop is visible again.")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colSubtext
            font.pixelSize: Appearance.font.pixelSize.small
        }
        ConfigSwitch {
            buttonIcon: "lock"
            text: Translation.tr("Pause when the screen is locked")
            checked: root.options.pauseWhenLocked
            onCheckedChanged: root.options.pauseWhenLocked = checked
        }
        ConfigSwitch {
            buttonIcon: "battery_saver"
            text: Translation.tr("Pause on low battery")
            checked: root.options.pauseOnBattery
            onCheckedChanged: root.options.pauseOnBattery = checked
        }
        ConfigSpinBox {
            Layout.fillWidth: true
            enabled: root.options.pauseOnBattery
            text: Translation.tr("Battery threshold (%)")
            value: root.options.batteryThreshold
            from: 5
            to: 100
            stepSize: 5
            onValueChanged: root.options.batteryThreshold = value
        }
    }

    ContentSection {
        icon: "tune"
        title: Translation.tr("Playback · all video wallpapers")

        ContentSubsection {
            title: Translation.tr("Video fit")
            ConfigSelectionArray {
                currentValue: root.options.fillMode
                onSelected: value => root.options.fillMode = value
                options: [
                    { displayName: Translation.tr("Fill screen"), value: "crop" },
                    { displayName: Translation.tr("Fit entire video"), value: "fit" }
                ]
            }
        }
        ContentSubsection {
            title: Translation.tr("Speed")
            ConfigSelectionArray {
                currentValue: root.options.speed
                onSelected: value => root.options.speed = value
                options: [0.5, 0.75, 1, 1.25, 1.5, 2].map(value => ({ displayName: value + "×", value: value }))
            }
        }
        ConfigSwitch {
            buttonIcon: "volume_off"
            text: Translation.tr("Mute video audio")
            checked: root.options.muted
            onCheckedChanged: root.options.muted = checked
        }
        ConfigSpinBox {
            Layout.fillWidth: true
            enabled: !root.options.muted
            text: Translation.tr("Volume (%)")
            value: root.options.volume
            from: 0
            to: 100
            stepSize: 5
            onValueChanged: root.options.volume = value
        }
        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Each monitor follows its active workspace. Videos loop and restart when you enter their workspace. Playback controls are shared, and audio plays from one monitor only.")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colSubtext
            font.pixelSize: Appearance.font.pixelSize.small
        }
    }
}

import QtQuick
import QtMultimedia
import "../common/functions/VideoWallpaperPolicy.js" as Policy

// Independent of shell state so both the wallpaper and a preview can use it.
Item {
    id: root
    property string sourcePath: ""
    property string pauseReason: ""
    property bool muted: true
    property real volume: 0.2
    property real speed: 1.0
    property string fit: "crop"
    readonly property bool playing: player.playing
    readonly property int position: player.position
    readonly property string error: player.errorString
    readonly property bool hasVideo: player.hasVideo

    function syncPlayback() {
        if (!sourcePath || player.error !== MediaPlayer.NoError) {
            if (player.playbackState !== MediaPlayer.StoppedState) player.stop();
        } else if (pauseReason) {
            if (player.playing) player.pause();
        } else if (player.mediaStatus === MediaPlayer.LoadedMedia ||
                   player.mediaStatus === MediaPlayer.BufferedMedia ||
                   player.mediaStatus === MediaPlayer.EndOfMedia) {
            if (!player.playing) player.play();
        }
    }

    onPauseReasonChanged: syncPlayback()
    Component.onCompleted: syncPlayback()

    MediaPlayer {
        id: player
        source: Policy.fileUrl(root.sourcePath)
        loops: MediaPlayer.Infinite
        playbackRate: Math.max(0.25, Math.min(2, root.speed))
        videoOutput: output
        audioOutput: AudioOutput {
            muted: root.muted
            volume: Math.max(0, Math.min(1, root.volume))
        }
        onMediaStatusChanged: root.syncPlayback()
        onErrorOccurred: (error, errorString) => console.warn("Video wallpaper:", errorString)
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: root.fit === "fit" ? VideoOutput.PreserveAspectFit : VideoOutput.PreserveAspectCrop
    }
}

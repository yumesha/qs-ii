import QtQuick
import QtMultimedia
import "../common/functions/VideoWallpaperPolicy.js" as Policy

// Independent of shell state so the player can be checked without a full shell.
Item {
    id: root
    property string sourcePath: ""
    property string pauseReason: ""
    property bool muted: true
    property real volume: 0.2
    property real speed: 1.0
    property string fit: "crop"
    readonly property var player: playerLoader.item
    readonly property bool playing: player?.playing ?? false
    readonly property int position: player?.position ?? resumePosition
    readonly property string error: recoveryExhausted
        ? "Video playback stopped after repeated failures. Pause and resume to retry."
        : player?.errorString ?? ""
    readonly property bool hasVideo: player?.hasVideo ?? false
    readonly property int mediaStatus: player?.mediaStatus ?? MediaPlayer.NoMedia
    readonly property int playbackState: player?.playbackState ?? MediaPlayer.StoppedState
    readonly property bool wantsPlayback: sourcePath.length > 0 && pauseReason.length === 0
    readonly property bool recovering: recoveryTimer.running || recoveryPending

    // These bounds prevent an unreadable file or bad decoder from retrying forever.
    property int stallTimeoutMs: 15000
    property int playbackStallTimeoutMs: 4000
    property int maxRecoveryAttempts: 3
    property int recoveryAttempts: 0
    property int recoveryCount: 0
    property bool recoveryExhausted: false
    property bool recoveryPending: false
    property bool manualRetryRequested: false
    property bool reloadReady: false
    property int resumePosition: 0
    property int resumeAtLoad: 0
    property real lastProgressAt: Date.now()
    property int lastObservedPosition: -1
    property int lastObservedFrames: 0
    property real lastFrameAt: Date.now()
    property real healthySince: Date.now()
    property int framesObserved: 0
    property bool playbackEstablished: false
    property string lastRecoveryReason: ""

    function resetProgressClock(resetEstablished = true) {
        const now = Date.now();
        lastProgressAt = now;
        lastFrameAt = now;
        healthySince = now;
        framesObserved = 0;
        if (resetEstablished) playbackEstablished = false;
        lastObservedFrames = 0;
        lastObservedPosition = player?.position ?? -1;
    }

    function setSource() {
        recoveryTimer.stop();
        recoveryPending = false;
        recoveryExhausted = false;
        manualRetryRequested = false;
        recoveryAttempts = 0;
        resumePosition = 0;
        resumeAtLoad = 0;
        resetProgressClock();
        playerLoader.active = sourcePath.length > 0;
        if (player) player.source = Policy.fileUrl(sourcePath);
    }

    function syncPlayback() {
        if (!player || recovering || recoveryExhausted) return;
        if (!wantsPlayback) {
            if (player.playing) player.pause();
            return;
        }
        if (player.error !== MediaPlayer.NoError) return;
        if (player.mediaStatus === MediaPlayer.LoadedMedia ||
            player.mediaStatus === MediaPlayer.BufferedMedia ||
            player.mediaStatus === MediaPlayer.EndOfMedia) {
            if (resumeAtLoad > 0 && player.seekable) {
                player.position = Math.min(resumeAtLoad, Math.max(0, player.duration - 250));
                resumeAtLoad = 0;
            }
            if (!player.playing) player.play();
        }
    }

    function recover(reason) {
        if (!wantsPlayback || recovering || recoveryExhausted) return;
        if (recoveryAttempts >= maxRecoveryAttempts) {
            recoveryExhausted = true;
            if (player) player.stop();
            console.warn("Video wallpaper: recovery limit reached; pause/resume to retry.");
            return;
        }
        // Restart at the beginning if the decoder stuck near the loop boundary.
        resumePosition = player && player.duration > 0 && player.duration - position < 1000 ? 0 : position;
        recoveryAttempts++;
        recoveryCount++;
        lastRecoveryReason = reason;
        recoveryPending = true;
        resetProgressClock();
        console.warn("Video wallpaper: recreating stalled player (" + reason + "), attempt " + recoveryAttempts);
        // Recreate the backend, not just play() on the same stuck decoder.
        playerLoader.active = false;
        recoveryTimer.interval = [250, 1000, 4000][Math.min(recoveryAttempts - 1, 2)];
        recoveryTimer.restart();
    }

    onSourcePathChanged: if (reloadReady) setSource()
    onPauseReasonChanged: {
        resetProgressClock(false);
        if (pauseReason === "manual") manualRetryRequested = true;
        Qt.callLater(syncPlayback);
    }
    onWantsPlaybackChanged: {
        if (wantsPlayback && recoveryExhausted && manualRetryRequested) {
            recoveryExhausted = false;
            recoveryAttempts = 0;
            recover("manual retry");
        } else {
            Qt.callLater(syncPlayback);
        }
        if (wantsPlayback) manualRetryRequested = false;
    }
    Component.onCompleted: { reloadReady = true; setSource(); }

    Timer {
        id: recoveryTimer
        onTriggered: {
            // A source change cancels this timer. An intentional pause may keep
            // the replacement loaded, but must never make it start playing.
            resumeAtLoad = resumePosition;
            root.recoveryPending = false;
            playerLoader.active = root.sourcePath.length > 0;
        }
    }

    Timer {
        interval: Math.max(100, Math.min(2000, root.stallTimeoutMs / 3))
        running: root.reloadReady && root.wantsPlayback && !root.recovering && !root.recoveryExhausted
        repeat: true
        onTriggered: {
            const now = Date.now();
            const moved = root.position !== root.lastObservedPosition;
            const newFrames = root.framesObserved !== root.lastObservedFrames;
            if (moved || newFrames) {
                root.lastProgressAt = now;
                root.playbackEstablished = true;
            }
            root.lastObservedPosition = root.position;
            root.lastObservedFrames = root.framesObserved;
            const timeout = root.playbackEstablished
                ? Math.min(root.stallTimeoutMs, root.playbackStallTimeoutMs) : root.stallTimeoutMs;
            const noProgress = now - root.lastProgressAt >= timeout;
            const noFrames = root.visible && root.framesObserved > 0 && now - root.lastFrameAt >= timeout;
            if (noProgress || noFrames) {
                root.recover(noFrames ? "video frames stopped" : "playback position stopped");
            } else if (root.recoveryAttempts > 0 && now - root.healthySince >= 30000 &&
                       now - root.lastProgressAt < 3000 && (!root.visible || now - root.lastFrameAt < 3000)) {
                root.recoveryAttempts = 0;
            }
        }
    }

    Loader {
        id: playerLoader
        active: false
        onLoaded: {
            root.resetProgressClock();
            item.source = Policy.fileUrl(root.sourcePath);
        }
        sourceComponent: MediaPlayer {
            loops: MediaPlayer.Infinite
            playbackRate: Math.max(0.25, Math.min(2, root.speed))
            videoOutput: output
            audioOutput: AudioOutput {
                muted: root.muted
                volume: Math.max(0, Math.min(1, root.volume))
            }
            onMediaStatusChanged: Qt.callLater(root.syncPlayback)
            onPlaybackStateChanged: Qt.callLater(root.syncPlayback)
            onErrorOccurred: (error, errorString) => console.warn("Video wallpaper:", errorString)
        }
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: root.fit === "fit" ? VideoOutput.PreserveAspectFit : VideoOutput.PreserveAspectCrop
    }
    Connections {
        target: output.videoSink
        function onVideoFrameChanged() {
            root.lastFrameAt = Date.now();
            root.framesObserved++;
        }
    }
}

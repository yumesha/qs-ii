.pragma library

function isVideo(path) {
    return /\.(mp4|webm|mkv|avi|mov|m4v)$/i.test(String(path || ""));
}

function localPath(url) {
    const value = String(url || "");
    return value.startsWith("file://") ? decodeURIComponent(value.slice(7)) : value;
}

function fileUrl(path) {
    const value = localPath(path);
    return value ? "file://" + value.split("/").map(encodeURIComponent).join("/") : "";
}

// Keep decisions monitor-local: hidden workspaces and other outputs cannot pause it.
function pauseReason(options, state) {
    if (!options.enabled) return "disabled";
    if (options.paused) return "manual";
    if (state.locked && options.pauseWhenLocked) return "locked";
    if (state.safety) return "hidden";
    const monitor = state.monitor;
    if (!monitor) return "waiting";
    if (monitor.dpmsStatus === false || monitor.disabled === true) return "display-off";
    if (options.pauseOnBattery && state.onBattery && state.batteryPercent <= options.batteryThreshold)
        return "battery";
    // The desktop is displayed above windows on the lock screen and in overview.
    if (state.locked || state.overview || options.pauseMode === "never") return "";
    const active = monitor.activeWorkspace?.id;
    const special = monitor.specialWorkspace?.id;
    const windows = (state.clients || []).filter(win =>
        win.mapped !== false && !win.hidden && win.monitor === monitor.id &&
        (win.pinned || win.workspace?.id === active || (special && win.workspace?.id === special)));
    if (options.pauseMode === "any-window" && windows.length) return "window";
    if (options.pauseMode === "covered" && windows.some(win => Number(win.fullscreen) > 0))
        return "covered";
    return "";
}

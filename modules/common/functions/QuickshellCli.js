.pragma library

// A restarted shell can pass its private crash bootstrap to child processes.
// Clear it before invoking qs, or it may restore shell.qml instead of honoring
// the requested settings window or IPC command. Keep argv separate from a shell.
function command(args) {
    return [
        "env", "-u", "__QUICKSHELL_CRASH_DUMP_PID",
        "-u", "__QUICKSHELL_CRASH_INFO_FD", "qs"
    ].concat(args);
}

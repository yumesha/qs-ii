.pragma library

function minutes(value) {
    const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    if (!match) return null;
    const hour = Number(match[1]), minute = Number(match[2]);
    return hour < 24 && minute < 60 ? hour * 60 + minute : null;
}

function scheduled(hour, minute, from, to) {
    const start = minutes(from), end = minutes(to);
    if (start === null || end === null || hour < 0 || hour > 23 || minute < 0 || minute > 59) return false;
    const now = hour * 60 + minute;
    if (start === end) return true; // Preserve the existing full-day schedule convention.
    return start < end ? now >= start && now < end : now >= start || now < end;
}

function desired(options, hour, minute) {
    return options.automatic
        ? scheduled(hour, minute, options.from, options.to)
        : options.manualEnabled === true;
}

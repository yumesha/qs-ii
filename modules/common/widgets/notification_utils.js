
/**
 * @param { string } summary 
 * @returns { string }
 */
function findSuitableMaterialSymbol(summary = "", appName = "") {
    const app = String(appName || "").toLowerCase();
    if (app === "udiskie") return "usb";
    if (app.includes("blueman") || app.includes("bluetooth")) return "bluetooth";
    summary = String(summary || "");
    const defaultType = 'chat';
    if(summary.length === 0) return defaultType;

    const keywordsToTypes = {
        'reboot': 'restart_alt',
        'record': 'screen_record',
        'battery': 'power',
        'power': 'power',
        'screenshot': 'screenshot_monitor',
        'welcome': 'waving_hand',
        'time': 'scheduleb',
        'installed': 'download',
        'configuration reloaded': 'reset_wrench',
        'config': 'reset_wrench',
        'update': 'update',
        'ai response': 'neurology',
        'control': 'settings',
        'upsca': 'compare',
        'install': 'deployed_code_update',
        'startswith:file': 'folder_copy', // Declarative startsWith check
    };

    const lowerSummary = summary.toLowerCase();

    for (const [keyword, type] of Object.entries(keywordsToTypes)) {
        if (keyword.startsWith('startswith:')) {
            const startsWithKeyword = keyword.replace('startswith:', '');
            if (lowerSummary.startsWith(startsWithKeyword)) {
                return type;
            }
        } else if (lowerSummary.includes(keyword)) {
            return type;
        }
    }

    return defaultType;
}

// App icons may be theme names, local paths, or already-resolved Qt sources.
// Never ask the icon provider for a missing theme icon: it returns a magenta
// checkerboard with Image.Ready, not Image.Error.
function localImageUrl(path) {
    try { return "file://" + path.split("/").map(encodeURIComponent).join("/"); }
    catch (_) { return ""; }
}

function resolveAppIcon(value, lookupTheme) {
    const icon = String(value || "");
    if (!icon) return "";
    if (icon.startsWith("/")) return localImageUrl(icon);
    if (icon.startsWith("image://icon/")) {
        // Preserve app-provided private icon directories.
        if (icon.includes("?path=")) return icon;
        const parts = icon.slice("image://icon/".length).split("?fallback=");
        try {
            const found = lookupTheme(decodeURIComponent(parts[0]));
            if (found) return found;
            return parts[1] && parts[1] !== "image-missing" ? lookupTheme(decodeURIComponent(parts[1])) : "";
        } catch (_) { return ""; }
    }
    if (/^(file|qrc|image):/.test(icon)) return icon;
    // Do not turn an arbitrary app-icon URL into a network request.
    if (/^[a-z][a-z0-9+.-]*:/i.test(icon)) return "";
    return lookupTheme(icon);
}

/**
 * @param { number | string | Date } timestamp 
 * @returns { string }
 */
const getFriendlyNotifTimeString = (timestamp) => {
    if (!timestamp) return '';
    const messageTime = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - messageTime.getTime();

    // Less than 1 minute
    if (diffMs < 60000) 
        return 'Now';
    
    // Same day - show relative time
    if (messageTime.toDateString() === now.toDateString()) {
        const diffMinutes = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        
        if (diffHours > 0) {
            return `${diffHours}h`;
        } else {
            return `${diffMinutes}m`;
        }
    }
    
    // Yesterday
    if (messageTime.toDateString() === new Date(now.getTime() - 86400000).toDateString()) 
        return 'Yesterday';
    
    // Older dates
    return Qt.formatDateTime(messageTime, "MMMM dd");
};
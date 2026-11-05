.pragma library

function isEnterprise(security) {
    return /802\.1x|eap/i.test(String(security || ""));
}

function securityType(security) {
    const value = String(security || "").toUpperCase();
    if (isEnterprise(value)) return "wpa-eap";
    if (value.includes("WPA3") && !value.includes("WPA2")) return "sae";
    if (value.includes("WPA")) return "wpa-psk";
    if (value.includes("WEP")) return "wep";
    return "open";
}

function matchingSavedProfiles(network, profiles) {
    const security = securityType(network.security);
    return profiles.filter(profile => profile.ssid === network.ssid && profile.security === security);
}

function connectRequest(network, password) {
    // JSON for an anonymous stdin pipe, never a shell command or argv array.
    const request = { ssid: network.ssid, bssid: network.bssid || "",
        device: network.device || "", security: securityType(network.security), hidden: false };
    if (password !== undefined && password !== null) request.password = password;
    return request;
}

function activeConnectionInfo(text) {
    const result = { ethernet: false, wifi: false, ethernetName: "", wifiName: "", wifiDevice: "" };
    for (const line of String(text || "").split("\n")) {
        if (!line) continue;
        const fields = splitFields(line);
        if (fields.length < 3) continue;
        if (fields[1] === "802-3-ethernet" && !result.ethernet) {
            result.ethernet = true;
            result.ethernetName = fields[0];
        } else if (fields[1] === "802-11-wireless" && !result.wifi) {
            result.wifi = true;
            result.wifiName = fields[0];
            result.wifiDevice = fields[2];
        }
    }
    return result;
}

function connectedWifiName(networks, device) {
    const active = networks.find(network => network.active && (!device || network.device === device));
    return active ? active.ssid : "";
}

// nmcli -g escapes both colons and backslashes, including those inside SSIDs.
function splitFields(line) {
    const fields = [];
    let field = "";
    let escaped = false;
    for (const character of line) {
        if (escaped) {
            field += character;
            escaped = false;
        } else if (character === "\\") {
            escaped = true;
        } else if (character === ":") {
            fields.push(field);
            field = "";
        } else {
            field += character;
        }
    }
    if (escaped) field += "\\";
    fields.push(field);
    return fields;
}

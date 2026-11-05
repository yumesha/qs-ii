"""Credential-safe NetworkManager operations over the local system D-Bus.

Credentials arrive through the caller's stdin and go directly to NetworkManager.
Never log requests, settings dictionaries, D-Bus errors, or passwords. Only
NetworkManager persists saved credentials; this module never calls GetSecrets.
"""

import os
import pwd
import time
import uuid

from gio_dbus import DBusError, SystemBus, Variant

ROOT = "/org/freedesktop/NetworkManager"
MANAGER = "org.freedesktop.NetworkManager"
SETTINGS = MANAGER + ".Settings"
CONNECTION = SETTINGS + ".Connection"
DEVICE = MANAGER + ".Device"
WIRELESS = DEVICE + ".Wireless"
AP = MANAGER + ".AccessPoint"
ACTIVE = MANAGER + ".Connection.Active"
PROPERTIES = "org.freedesktop.DBus.Properties"
STAGES = frozenset(("request", "read-state", "read-profile", "list-profiles", "list-devices",
                    "read-access-points", "update-profile", "activate-existing", "add-and-activate",
                    "monitor-active", "read-device-state", "cancel-activation",
                    "startup-debug-policy", "startup-library-discovery", "startup-library-load",
                    "startup-library-symbols", "startup-system-bus"))
MISSING_ACTIVE_ERRORS = frozenset(("org.freedesktop.DBus.Error.UnknownObject",
                                  "org.freedesktop.DBus.Error.UnknownInterface",
                                  "org.freedesktop.DBus.Error.UnknownMethod"))


class NetworkError(Exception):
    def __init__(self, message, code="failed"):
        super().__init__(message)
        self.code = code


def value(mapping, key, default=None):
    item = mapping.get(key)
    return item.value if isinstance(item, Variant) else default


def stage_call(bus, stage, path, interface, method, signature, arguments):
    try:
        if stage == "update-profile":
            # Editing a system-wide profile may wait for a Polkit admin dialog.
            return bus.call(path, interface, method, signature, arguments, timeout_ms=120000)
        return bus.call(path, interface, method, signature, arguments)
    except DBusError as error:
        # Fixed stage names only; never attach paths, settings, or credential values.
        error.stage = stage if stage in STAGES else "request"
        raise


def properties(bus, path, interface, stage="read-state"):
    return stage_call(bus, stage, path, PROPERTIES, "GetAll", "(s)", (interface,))[0]


def settings_for(bus, path):
    return stage_call(bus, "read-profile", path, CONNECTION, "GetSettings", "()", ())[0]


def ssid_of(settings):
    raw = value(settings.get("802-11-wireless", {}), "ssid", [])
    try:
        return bytes(raw).decode("utf-8", errors="strict")
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def all_profiles(bus):
    paths = stage_call(bus, "list-profiles", ROOT + "/Settings", SETTINGS, "ListConnections", "()", ())[0]
    result = []
    for path in paths:
        try:
            settings = settings_for(bus, path)
        except DBusError as error:
            if error.name in ("org.freedesktop.DBus.Error.UnknownObject", "org.freedesktop.NetworkManager.Settings.UnknownConnection"):
                continue  # A profile can disappear during an asynchronous refresh.
            raise  # Authorization failures must not become duplicate new profiles.
        connection = settings.get("connection", {})
        if value(connection, "type") == "802-11-wireless":
            result.append((path, settings))
    return result


def devices(bus):
    paths = stage_call(bus, "list-devices", ROOT, MANAGER, "GetDevices", "()", ())[0]
    result = []
    for path in paths:
        details = properties(bus, path, DEVICE)
        if value(details, "DeviceType") == 2:
            result.append((path, details))
    return result


def list_details(bus):
    adapters = []
    active_uuids = set()
    for path, details in devices(bus):
        adapters.append({"device": value(details, "Interface", ""), "state": value(details, "State", 0)})
        active = value(details, "ActiveConnection", "/")
        if active != "/":
            try:
                active_uuids.add(value(properties(bus, active, ACTIVE), "Uuid", ""))
            except DBusError:
                pass
    profiles = []
    for _, settings in all_profiles(bus):
        connection = settings["connection"]
        wireless = settings.get("802-11-wireless", {})
        security = settings.get("802-11-wireless-security", {})
        ssid = ssid_of(settings)
        if ssid is None:
            continue
        profile_uuid = value(connection, "uuid", "")
        profiles.append({
            "uuid": profile_uuid, "ssid": ssid,
            "name": value(connection, "id", ssid),
            "autoconnect": value(connection, "autoconnect", True),
            "hidden": value(wireless, "hidden", False),
            "security": value(security, "key-mgmt", "open"),
            "active": profile_uuid in active_uuids,
        })
    return {"profiles": profiles, "adapters": adapters}


def checked_ssid(payload):
    ssid = payload.get("ssid")
    try:
        valid = isinstance(ssid, str) and "\0" not in ssid and 1 <= len(ssid.encode("utf-8")) <= 32
    except UnicodeEncodeError:
        valid = False
    if not valid:
        raise NetworkError("Enter the exact network name (1–32 UTF-8 bytes).", "invalid-input")
    return ssid


def checked_bool(payload, key, default):
    item = payload.get(key, default)
    if not isinstance(item, bool):
        raise NetworkError("Invalid network option.", "invalid-input")
    return item


def choose_device(bus, requested=""):
    if not value(properties(bus, ROOT, MANAGER), "WirelessEnabled", False):
        raise NetworkError("Turn on Wi-Fi before connecting.", "disabled")
    if not isinstance(requested, str):
        raise NetworkError("Select a Wi-Fi adapter.", "invalid-input")
    candidates = [(path, details) for path, details in devices(bus)
                  if not requested or value(details, "Interface") == requested]
    if len(candidates) != 1:
        raise NetworkError("Select an available Wi-Fi adapter.", "unavailable")
    path, details = candidates[0]
    if value(details, "State", 0) < 30:
        raise NetworkError("The Wi-Fi adapter is unavailable. Check its radio or hardware switch.", "unavailable")
    return path


def access_point(bus, device, ssid, bssid):
    if not bssid:
        return "/"
    if not isinstance(bssid, str):
        raise NetworkError("Invalid access point.", "invalid-input")
    for path in stage_call(bus, "read-access-points", device, WIRELESS, "GetAccessPoints", "()", ())[0]:
        details = properties(bus, path, AP)
        if value(details, "HwAddress", "").lower() == bssid.lower():
            if bytes(value(details, "Ssid", [])).decode("utf-8", errors="replace") == ssid:
                return path
    raise NetworkError("That access point is no longer available. Scan again.", "unavailable")


def find_profile(bus, profile_uuid, ssid):
    try:
        canonical = str(uuid.UUID(profile_uuid))
    except (ValueError, TypeError, AttributeError):
        raise NetworkError("Select a saved Wi-Fi profile.", "invalid-input") from None
    for path, settings in all_profiles(bus):
        if value(settings["connection"], "uuid") == canonical:
            if ssid_of(settings) != ssid:
                raise NetworkError("The saved profile changed. Refresh and try again.", "stale-profile")
            return path, settings
    raise NetworkError("That saved Wi-Fi profile no longer exists.", "stale-profile")


def activation_failure(details):
    # These are Device.StateReason values, NOT ActiveConnection.StateChanged reasons.
    state_reason = value(details, "StateReason", (0, 0))
    reason = state_reason[1] if isinstance(state_reason, (tuple, list)) and len(state_reason) == 2 else 0
    if reason == 7:
        return NetworkError("NetworkManager could not obtain the required Wi-Fi credentials. Enter the password again. [monitor-active/no-secrets]", "password-required")
    if reason == 8:
        return NetworkError("Wi-Fi authentication was interrupted. Check the router security and signal. [monitor-active/supplicant-disconnected]", "authentication")
    if reason == 9:
        return NetworkError("The Wi-Fi authentication configuration was rejected. [monitor-active/supplicant-config]", "configuration")
    if reason == 10:
        return NetworkError("The Wi-Fi authentication service failed. [monitor-active/supplicant-failed]")
    if reason == 11:
        return NetworkError("The Wi-Fi authentication service timed out. Check signal and router security. [monitor-active/supplicant-timeout]", "timeout")
    if reason == 39:
        return NetworkError("The Wi-Fi attempt was cancelled or disconnected. [monitor-active/cancelled]", "cancelled")
    return NetworkError("Wi-Fi activation ended before connecting. Check the network and try again. [monitor-active/activation-ended]")


def wait_for_activation(bus, active_path, device_path, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = value(properties(bus, active_path, ACTIVE, "monitor-active"), "State", 0)
        except DBusError as error:
            if error.name not in MISSING_ACTIVE_ERRORS:
                raise
            # NM can unexport a failed activation before our next poll. On GDBus
            # this may be UnknownMethod, not just UnknownObject. Inspect the
            # device instead of hiding the underlying failure behind a bus error.
            details = properties(bus, device_path, DEVICE, "read-device-state")
            current = value(details, "ActiveConnection", "/")
            if value(details, "State", 0) == 100 and current == active_path:
                return {}
            if current not in ("/", active_path):
                raise NetworkError("Another Wi-Fi attempt replaced this one. [monitor-active/replaced]", "cancelled")
            raise activation_failure(details) from None
        if state == 2:
            return {}
        if state == 4:
            raise activation_failure(properties(bus, device_path, DEVICE, "read-device-state"))
        time.sleep(0.25)
    try:
        # Cancel only the activation started by this request, never another device.
        stage_call(bus, "cancel-activation", ROOT, MANAGER, "DeactivateConnection", "(o)", (active_path,))
    except DBusError:
        pass
    raise NetworkError("Connection timed out. Check the network name, password, and signal. [monitor-active/timeout]", "timeout")


def activate(bus, payload):
    ssid = checked_ssid(payload)
    path, _ = find_profile(bus, payload.get("uuid"), ssid)
    device = choose_device(bus, payload.get("device", ""))
    active = stage_call(bus, "activate-existing", ROOT, MANAGER, "ActivateConnection", "(ooo)", (path, device, "/"))[0]
    return wait_for_activation(bus, active, device)


def security_settings(security, password):
    if security == "open":
        if password:
            raise NetworkError("Open networks do not use a password.", "invalid-input")
        return None
    if security not in ("wpa-psk", "sae"):
        raise NetworkError("Manual setup supports Open, WPA/WPA2 Personal, and WPA3 Personal networks. Enterprise and WEP need a dedicated editor.", "unsupported-security")
    if not isinstance(password, str) or "\0" in password:
        raise NetworkError("Enter the Wi-Fi password.", "password-required")
    try:
        length = len(password.encode("utf-8"))
    except UnicodeEncodeError:
        raise NetworkError("Enter a valid UTF-8 password.", "invalid-password") from None
    hex_key = length == 64 and all(c in "0123456789abcdefABCDEF" for c in password)
    if security == "wpa-psk" and not (8 <= length <= 63 or hex_key):
        raise NetworkError("WPA/WPA2 passwords need 8–63 bytes, or a 64-digit hexadecimal key.", "invalid-password")
    if security == "sae" and not 1 <= length <= 63:
        raise NetworkError("WPA3 passwords need 1–63 UTF-8 bytes.", "invalid-password")
    return {"key-mgmt": Variant("s", security), "psk": Variant("s", password), "psk-flags": Variant("u", 0)}


def connect(bus, payload):
    ssid = checked_ssid(payload)
    security = payload.get("security", "wpa-psk")
    hidden = checked_bool(payload, "hidden", False)
    if hidden and security not in ("open", "wpa-psk", "sae"):
        raise NetworkError("Manual hidden-network setup supports Personal or Open Wi-Fi only. Use Saved for a configured enterprise profile.", "unsupported-security")
    auto = checked_bool(payload, "autoconnect", not hidden)
    device = choose_device(bus, payload.get("device", ""))
    ap = access_point(bus, device, ssid, payload.get("bssid", ""))
    matches = [(path, settings) for path, settings in all_profiles(bus)
               if ssid_of(settings) == ssid and value(settings.get("802-11-wireless-security", {}), "key-mgmt", "open") == security]
    if len(matches) > 1:
        raise NetworkError("Several saved profiles match. Choose one under Saved networks.", "ambiguous-profile")
    if matches and "password" not in payload and security == "open" and not hidden and "autoconnect" not in payload:
        active = stage_call(bus, "activate-existing", ROOT, MANAGER, "ActivateConnection", "(ooo)", (matches[0][0], device, ap))[0]
        return wait_for_activation(bus, active, device)
    if "password" not in payload and security != "open":
        if not matches:
            raise NetworkError("Enter the Wi-Fi password.", "password-required")
        active = stage_call(bus, "activate-existing", ROOT, MANAGER, "ActivateConnection", "(ooo)", (matches[0][0], device, ap))[0]
        return wait_for_activation(bus, active, device)
    secrets = security_settings(security, payload.get("password", ""))
    if matches:
        path, settings = matches[0]
        if secrets:
            settings.setdefault("802-11-wireless-security", {}).update(secrets)
        if hidden:
            settings["802-11-wireless"]["hidden"] = Variant("b", True)
        if "autoconnect" in payload:
            settings["connection"]["autoconnect"] = Variant("b", auto)
        stage_call(bus, "update-profile", path, CONNECTION, "Update2", "(a{sa{sv}}ua{sv})", (settings, 1, {}))
        active = stage_call(bus, "activate-existing", ROOT, MANAGER, "ActivateConnection", "(ooo)", (path, device, ap))[0]
    else:
        user = pwd.getpwuid(os.getuid()).pw_name
        settings = {
            "connection": {"id": Variant("s", ssid), "uuid": Variant("s", str(uuid.uuid4())),
                           "type": Variant("s", "802-11-wireless"), "autoconnect": Variant("b", auto),
                           "permissions": Variant("as", ["user:" + user + ":"])},
            "802-11-wireless": {"ssid": Variant("ay", list(ssid.encode("utf-8"))),
                                "mode": Variant("s", "infrastructure"), "hidden": Variant("b", hidden)},
            "ipv4": {"method": Variant("s", "auto")},
            "ipv6": {"method": Variant("s", "auto")},
        }
        if secrets:
            settings["802-11-wireless-security"] = secrets
        _, active, _ = stage_call(bus, "add-and-activate", ROOT, MANAGER, "AddAndActivateConnection2", "(a{sa{sv}}ooa{sv})",
                                (settings, device, ap, {"persist": Variant("s", "disk")}))
    return wait_for_activation(bus, active, device)


def safe_dbus_error(error):
    # Publish only fixed labels. Never expose raw errors, paths, settings or SSIDs.
    stage = getattr(error, "stage", "request")
    if stage not in STAGES:
        stage = "request"
    suffix = (getattr(error, "name", "") or "").rsplit(".", 1)[-1]
    category = {
        "PermissionDenied": "permission", "NotAuthorized": "permission", "AccessDenied": "permission",
        "Failed": "settings-failed" if stage == "update-profile" else "failed",
        "InvalidConnection": "invalid-settings", "InvalidSetting": "invalid-settings",
        "MissingSetting": "invalid-settings", "InvalidProperty": "invalid-settings",
        "MissingProperty": "invalid-settings", "InvalidArgs": "invalid-settings",
        "UnknownObject": "missing-object", "UnknownInterface": "missing-interface",
        "UnknownMethod": "unsupported-method", "NoReply": "timeout", "Timeout": "timeout",
        "UnknownDevice": "unavailable", "ConnectionNotAvailable": "unavailable",
    }.get(suffix, "unknown")
    local = getattr(error, "category", None)
    if local in ("timeout", "cancelled", "permission", "transport"):
        category = "local-" + local
    code = "failed"
    if category in ("permission", "local-permission"):
        message = "System authorization is required for this Wi-Fi operation."
        code = "permission"
    elif category in ("timeout", "local-timeout"):
        message = "NetworkManager did not respond before the request timed out."
        code = "timeout"
    elif category == "invalid-settings":
        message = "NetworkManager rejected the Wi-Fi profile configuration."
        code = "configuration"
    else:
        message = "NetworkManager could not complete the Wi-Fi request."
    if stage in ("startup-library-discovery", "startup-library-load", "startup-library-symbols"):
        message = "The Wi-Fi helper could not load its GLib/GIO runtime libraries. No connection was attempted."
        code = "runtime-unavailable"
    elif stage == "startup-debug-policy":
        message = "The Wi-Fi helper refuses to run while D-Bus message-body debugging is enabled."
        code = "privacy-policy"
    elif stage == "startup-system-bus":
        message = "The Wi-Fi helper could not open the local system bus."
    elif stage == "update-profile" and category in ("permission", "local-permission", "settings-failed", "timeout", "local-timeout"):
        message = "Could not update this saved profile. System authorization may be required. Use saved if its stored password is still current."
    return NetworkError(message + " [" + stage + "/" + category + "]", code)

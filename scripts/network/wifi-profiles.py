#!/usr/bin/env python3
"""Read saved Wi-Fi metadata and perform explicitly targeted Wi-Fi actions.

No passwords are queried. Destructive actions recheck type and SSID, rather than
trusting a connection name or a possibly stale GUI row. Ethernet is never targeted.
"""

import json
import os
import re
import resource
import subprocess
import sys

UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


class WifiError(Exception):
    pass


class NmcliError(WifiError):
    pass


def run_nmcli(args):
    operation = args[2:] if args[:1] == ["--wait"] else args
    may_authorize = operation[:2] in (["connection", "delete"], ["connection", "modify"])
    # A normal administrator dialog needs time for a human response. Read-only
    # queries keep the short bound; this does not grant or bypass authorization.
    timeout = 130 if may_authorize else 25
    try:
        result = subprocess.run(
            ["nmcli", *args], capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NmcliError("NetworkManager could not be reached. Try again.") from error
    if result.returncode:
        if re.search(r"not authori[sz]ed|permission denied|insufficient privileges", result.stderr, re.I):
            raise NmcliError("Permission denied. This profile may require administrator authorization. Ensure a Polkit authentication agent is running.")
        raise NmcliError("The Wi-Fi action failed. Refresh the list or open Details.")
    # Preserve leading/trailing spaces and embedded newlines in the SSID.
    return result.stdout.removesuffix("\n")


def checked_uuid(value):
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        raise WifiError("The saved Wi-Fi profile changed. Refresh and try again.")
    return value.lower()


def checked_ssid(payload):
    ssid = payload.get("ssid")
    if not isinstance(ssid, str) or not ssid or len(ssid) > 256:
        raise WifiError("Select a Wi-Fi network first.")
    return ssid


def profile_ssid(profile_uuid):
    return run_nmcli([
        "--escape", "no", "-g", "802-11-wireless.ssid",
        "connection", "show", "uuid", profile_uuid,
    ])


def validate_profile(profile_uuid, ssid):
    connection_type = run_nmcli(["-g", "connection.type", "connection", "show", "uuid", profile_uuid])
    if connection_type != "802-11-wireless" or profile_ssid(profile_uuid) != ssid:
        raise WifiError("The saved connection no longer matches this Wi-Fi network. Refresh and try again.")


def list_profiles():
    profiles = []
    lines = run_nmcli(["-t", "-f", "UUID,TYPE", "connection", "show"])
    for line in lines.splitlines():
        fields = line.split(":", 1)
        if len(fields) != 2 or fields[1] != "802-11-wireless":
            continue
        profile_uuid = checked_uuid(fields[0])
        try:
            ssid = profile_ssid(profile_uuid)
        except NmcliError:
            # A profile may disappear while NetworkManager refreshes its list.
            continue
        profiles.append({"uuid": profile_uuid, "ssid": ssid})
    return profiles


def disconnect(payload):
    ssid = checked_ssid(payload)
    device = payload.get("device")
    if not isinstance(device, str) or device.startswith("-") or not re.fullmatch(r"[\w.:-]{1,64}", device):
        raise WifiError("The Wi-Fi interface is unavailable. Refresh and try again.")
    fields = run_nmcli(["-g", "GENERAL.TYPE,GENERAL.CON-UUID", "device", "show", device]).splitlines()
    if len(fields) != 2 or fields[0] != "wifi":
        raise WifiError("This is not an active Wi-Fi interface. No connection was disconnected.")
    profile_uuid = checked_uuid(fields[1])
    validate_profile(profile_uuid, ssid)
    run_nmcli(["--wait", "15", "device", "disconnect", device])
    return {}


def forget(payload):
    ssid = checked_ssid(payload)
    requested = payload.get("uuids")
    if not isinstance(requested, list) or not 1 <= len(requested) <= 32:
        raise WifiError("Select the saved Wi-Fi profiles to forget first.")
    profile_uuids = list(dict.fromkeys(checked_uuid(value) for value in requested))
    # Validate the entire confirmation snapshot BEFORE deleting anything. Never
    # discover additional matching profiles and silently add them to this action.
    for profile_uuid in profile_uuids:
        validate_profile(profile_uuid, ssid)
    deleted = []
    for profile_uuid in profile_uuids:
        try:
            run_nmcli(["--wait", "120", "connection", "delete", "uuid", profile_uuid])
        except NmcliError as error:
            prefix = "Some saved profiles were removed. " if deleted else ""
            return {"deleted": deleted, "error": prefix + str(error)}
        deleted.append(profile_uuid)
    return {"deleted": deleted}


def set_autoconnect(payload):
    ssid = checked_ssid(payload)
    profile_uuid = checked_uuid(payload.get("uuid"))
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise WifiError("Invalid automatic connection option.")
    validate_profile(profile_uuid, ssid)
    run_nmcli(["connection", "modify", "uuid", profile_uuid, "connection.autoconnect", "yes" if enabled else "no"])
    return {}


def private_action(action, payload):
    # Imported lazily so read-only nmcli tooling remains usable independently.
    from gio_dbus import DBusError, SystemBus
    from wifi_nm import NetworkError, activate, connect, list_details, safe_dbus_error
    try:
        with SystemBus() as bus:
            if action == "list-details":
                return list_details(bus)
            return connect(bus, payload) if action == "connect" else activate(bus, payload)
    except DBusError as error:
        error = safe_dbus_error(error)
        return {"error": str(error), "code": error.code}
    except NetworkError as error:
        return {"error": str(error), "code": error.code}


def main():
    # Reduce credential exposure through crash dumps; no payload is written to disk.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    try:
        action = sys.argv[1] if len(sys.argv) == 2 else ""
        if action == "list":
            result = {"profiles": list_profiles()}
        elif action == "list-details":
            result = private_action(action, {})
        elif action in ("disconnect", "forget", "connect", "activate", "set-autoconnect"):
            data = sys.stdin.read(16385)
            if len(data) > 16384:
                raise WifiError("Invalid Wi-Fi action request.")
            payload = json.loads(data)
            data = ""
            if not isinstance(payload, dict):
                raise WifiError("Invalid Wi-Fi action request.")
            if action in ("connect", "activate"):
                result = private_action(action, payload)
            else:
                result = {"disconnect": disconnect, "forget": forget, "set-autoconnect": set_autoconnect}[action](payload)
            payload.clear()
        else:
            raise WifiError("Unknown Wi-Fi action.")
        ok = not result.get("error")
        print(json.dumps({"ok": ok, **result}))
        return 0 if ok else 1
    except WifiError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    except Exception:
        # Parser/library failures must never print a traceback containing inputs.
        print(json.dumps({"ok": False, "error": "Could not process the network request. Check that NetworkManager and GLib/GIO are installed."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

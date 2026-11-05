#!/usr/bin/env python3
"""Apply the shell's saved night-light choice through Hyprsunset's IPC.

No schedule or preference is stored here; QML supplies the already-resolved
choice after its configuration is ready. Commands are argument arrays.
"""

import json
import subprocess
import sys
import time


class NightLightError(Exception):
    pass


def call(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NightLightError("Could not communicate with the night-light service.") from error


def temperature():
    result = call(["hyprctl", "hyprsunset", "temperature"])
    text = result.stdout.strip()
    if result.returncode == 0 and text.isdecimal():
        return int(text)
    diagnostic = (result.stdout + result.stderr).lower()
    if any(marker in diagnostic for marker in ("couldn't connect", "connection refused", "no such file")):
        return None
    raise NightLightError("Could not read the night-light temperature.")


def apply(enabled, requested_temperature):
    if type(enabled) is not bool or type(requested_temperature) is not int or not 1000 <= requested_temperature <= 20000:
        raise NightLightError("Choose a color temperature between 1000 and 20000 K.")
    current = temperature()
    if not enabled:
        if current is not None:
            # 6500 K is still a color transform, not the identity matrix. The
            # temperature query also retains its value while identity is active.
            result = call(["hyprctl", "hyprsunset", "identity"])
            if result.returncode != 0 or result.stdout.strip() != "ok":
                raise NightLightError("Could not apply the night-light preference.")
        return {"active": False, "temperature": None}
    target = requested_temperature
    if current is None:
        try:
            subprocess.Popen(["hyprsunset", "--temperature", str(target)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
        except OSError as error:
            raise NightLightError("Could not start the night-light service.") from error
        for _ in range(20):
            time.sleep(0.1)
            current = temperature()
            if current is not None:
                break
        if current is None:
            raise NightLightError("The night-light service did not become ready.")
    # Always leave identity mode explicitly, even if the stored Kelvin value
    # already equals the target. A numeric query cannot distinguish these modes.
    result = call(["hyprctl", "hyprsunset", "temperature", str(target)])
    if result.returncode != 0 or result.stdout.strip() != "ok":
        raise NightLightError("Could not apply the night-light preference.")
    if temperature() != target:
        raise NightLightError("The night-light service did not confirm the requested temperature.")
    return {"active": True, "temperature": target}


def main():
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ("on", "off"):
            raise NightLightError("Choose night-light on or off and a temperature.")
        result = apply(sys.argv[1] == "on", int(sys.argv[2]))
        print(json.dumps({"ok": True, **result}))
        return 0
    except (NightLightError, ValueError) as error:
        message = str(error) if isinstance(error, NightLightError) else "Invalid night-light temperature."
        print(json.dumps({"ok": False, "error": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

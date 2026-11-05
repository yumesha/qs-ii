#!/usr/bin/env python3
"""Session-scoped keep-awake state, independent inhibitor, and automatic-idle guard.

Only on/off/restore mutate state. status and guard --dry-run are read-only.
The private runtime marker is authoritative; legacy state is a one-time import.
No shell commands are constructed and command output is never forwarded.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time

SCHEMA = 1
MAX_STATE_BYTES = 4096
COMMAND_TIMEOUT = 8
HOLD_POLL_SECONDS = 5
ACTIONS = {
    "lock": ["loginctl", "lock-session"],
    "dpms-off": ["hyprctl", "dispatch", "dpms", "off"],
    "suspend": ["systemctl", "suspend"],
}


class AwakeError(Exception):
    """Messages are fixed, safe descriptions, never raw external exceptions."""


def run_command(argv):
    try:
        return subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=COMMAND_TIMEOUT,
            check=False, env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"},
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", "")
    except subprocess.TimeoutExpired:
        raise AwakeError("Command timed out") from None
    except OSError:
        raise AwakeError("Command unavailable") from None


def check_private(fd, directory=False):
    info = os.fstat(fd)
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct_type or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise AwakeError("Unsafe runtime state permissions")
    if not directory and info.st_nlink != 1:
        raise AwakeError("Unsafe runtime state file")


class StateStore:
    def __init__(self, create=False):
        self.fd = None
        self.signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.signature):
            raise AwakeError("Compositor session identity unavailable")
        self.key = hashlib.sha256(self.signature.encode()).hexdigest()[:16]
        self.filename = self.key + ".json"
        self.unit = "qs-ii-awake-" + self.key + ".service"
        self.who = "qs-ii:" + self.key
        self.runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        if not os.path.isabs(self.runtime):
            raise AwakeError("Private runtime directory unavailable")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = None
        try:
            fd = os.open(self.runtime, flags)
            check_private(fd, directory=True)
            for name in ("qs-ii", "idle"):
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                try:
                    child = os.open(name, flags, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        return
                    raise
                os.close(fd)
                fd = child
                check_private(fd, directory=True)
            self.fd, fd = fd, None
        except OSError:
            raise AwakeError("Private runtime directory unavailable") from None
        finally:
            if fd is not None:
                os.close(fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self):
        if self.fd is None:
            return None
        try:
            fd = os.open(self.filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise AwakeError("Unsafe runtime state file") from None
        try:
            check_private(fd)
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise AwakeError("Invalid keep-awake state")
            data = json.loads(raw)
            if (not isinstance(data, dict) or set(data) != {"schema", "session", "inhibit"}
                    or type(data["schema"]) is not int or data["schema"] != SCHEMA
                    or data["session"] != self.signature or type(data["inhibit"]) is not bool):
                raise AwakeError("Invalid keep-awake state")
            return data["inhibit"]
        except (ValueError, UnicodeError, OSError):
            raise AwakeError("Invalid keep-awake state") from None
        finally:
            os.close(fd)

    @contextmanager
    def locked(self):
        if self.fd is None:
            raise AwakeError("Private runtime directory unavailable")
        fd = os.open(self.key + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            check_private(fd)
            deadline = time.monotonic() + 10
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise AwakeError("Keep-awake control is busy")
                    time.sleep(0.05)
            yield
        finally:
            os.close(fd)

    def write(self, enabled):
        if type(enabled) is not bool or self.fd is None:
            raise AwakeError("Invalid keep-awake state")
        # Refuse links and unsafe ownership even when explicitly repairing bad JSON.
        try:
            existing = os.open(self.filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                               dir_fd=self.fd)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                check_private(existing)
            finally:
                os.close(existing)
        temporary = "." + self.key + "." + secrets.token_hex(8) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", closefd=False) as stream:
                json.dump({"schema": SCHEMA, "session": self.signature, "inhibit": enabled}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(fd)
            os.replace(temporary, self.filename, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass


def session_exists(store):
    result = run_command(["hyprctl", "-j", "instances"])
    if result.returncode:
        raise AwakeError("Cannot verify compositor session")
    try:
        instances = json.loads(result.stdout)
        if not isinstance(instances, list):
            raise ValueError
        return any(isinstance(item, dict) and item.get("instance") == store.signature
                   and type(item.get("pid")) is int and item["pid"] > 0 for item in instances)
    except ValueError:
        raise AwakeError("Cannot verify compositor session") from None


def unit_info(store):
    result = run_command(["systemctl", "--user", "show", store.unit,
                          "--property=LoadState,ActiveState,MainPID"])
    info = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or set(info) != {"LoadState", "ActiveState", "MainPID"}:
        raise AwakeError("Cannot inspect idle inhibitor service")
    if not info["MainPID"].isdigit():
        raise AwakeError("Cannot inspect idle inhibitor service")
    return info


def backend_active(store, info=None):
    info = unit_info(store) if info is None else info
    if info["ActiveState"] != "active" or int(info["MainPID"]) <= 0:
        return False
    # systemd-inhibit 257 has no JSON output. Query its underlying logind API.
    result = run_command([
        "busctl", "--system", "--json=short", "call", "org.freedesktop.login1",
        "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "ListInhibitors",
    ])
    if result.returncode:
        raise AwakeError("Cannot verify logind idle inhibitor")
    try:
        payload = json.loads(result.stdout)
        if payload.get("type") != "a(ssssuu)" or len(payload["data"]) != 1:
            raise ValueError
        rows = payload["data"][0]
        if not isinstance(rows, list):
            raise ValueError
        for row in rows:
            if (not isinstance(row, list) or len(row) != 6
                    or not all(isinstance(value, str) for value in row[:4])
                    or not all(type(value) is int for value in row[4:])):
                raise ValueError
        return any("idle" in row[0].split(":") and row[1] == store.who
                   and row[3] == "block" and row[4] == os.getuid()
                   and row[5] == int(info["MainPID"]) for row in rows)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AwakeError("Cannot verify logind idle inhibitor") from None


def status(store):
    enabled = False
    active = False
    try:
        enabled = store.read() is True
        active = backend_active(store)
        if enabled != active:
            raise AwakeError("Idle inhibitor is not active" if enabled else "Idle inhibitor is still active")
        return {"ok": True, "inhibit": enabled, "backendActive": active}
    except AwakeError as error:
        return {"ok": False, "inhibit": enabled, "backendActive": active, "error": str(error)}


def start_backend(store):
    info = unit_info(store)
    if info["ActiveState"] not in ("active", "activating", "reloading"):
        if info["LoadState"] == "not-found":
            inhibitor = shutil.which("systemd-inhibit")
            if not inhibitor:
                raise AwakeError("Idle inhibitor executable unavailable")
            command = [
                "systemd-run", "--user", "--collect", "--quiet", "--expand-environment=no",
                "--unit=" + store.unit,
                "--property=PartOf=graphical-session.target", "--property=Restart=on-failure",
                "--property=RestartSec=1s", "--property=TimeoutStopSec=5s",
                "--property=Type=exec", "--property=UMask=0077",
                "--setenv=XDG_RUNTIME_DIR=" + store.runtime,
                "--setenv=HYPRLAND_INSTANCE_SIGNATURE=" + store.signature,
                "--setenv=PATH=" + os.environ.get("PATH", os.defpath),
                "--", inhibitor, "--no-ask-password", "--what=idle", "--mode=block",
                "--who=" + store.who, "--why=Keep system awake",
                sys.executable, "-B", str(Path(__file__).resolve()), "hold", store.key,
            ]
        else:
            command = ["systemctl", "--user", "start", store.unit]
        if run_command(command).returncode:
            raise AwakeError("Cannot start idle inhibitor service")
    # A Type=exec unit can be active before logind has handed out its inhibitor FD.
    for attempt in range(20):
        if backend_active(store):
            return
        if attempt < 19:
            time.sleep(0.1)
    raise AwakeError("Idle inhibitor acquisition not confirmed")


def stop_backend(store):
    if unit_info(store)["LoadState"] != "not-found":
        if run_command(["systemctl", "--user", "stop", store.unit]).returncode:
            raise AwakeError("Cannot stop idle inhibitor service")


def control(store, action, legacy_on=False):
    with store.locked():
        if action == "restore":
            enabled = store.read()
            if enabled is None:
                enabled = bool(legacy_on)
                if enabled and not session_exists(store):
                    raise AwakeError("Compositor session is no longer running")
                store.write(enabled)
        else:
            enabled = action == "on"
            if enabled and not session_exists(store):
                raise AwakeError("Compositor session is no longer running")
            store.write(enabled)
        try:
            if enabled:
                if not session_exists(store):
                    raise AwakeError("Compositor session is no longer running")
                start_backend(store)
            else:
                stop_backend(store)
        except AwakeError as error:
            try:
                active = backend_active(store)
            except AwakeError:
                active = False
            return {"ok": False, "inhibit": enabled, "backendActive": active, "error": str(error)}
        return status(store)


def hold(store, key):
    if key != store.key or not re.fullmatch(r"[0-9a-f]{16}", key):
        raise AwakeError("Compositor session identity mismatch")
    while True:
        try:
            if store.read() is not True:
                return 0
        except AwakeError:
            return 0  # Invalid state fails open for normal automatic idle policy.
        if not session_exists(store):
            return 0
        time.sleep(HOLD_POLL_SECONDS)


def guard(action, dry_run=False):
    store = None
    warning = None
    try:
        store = StateStore()
        enabled = store.read() is True
    except (AwakeError, OSError):
        enabled = False
        warning = "Keep-awake state unavailable; normal idle policy applies"
    finally:
        if store is not None:
            store.close()
    result = {"ok": True, "inhibit": enabled, "skipped": enabled, "action": action, "dryRun": dry_run}
    if warning:
        result["warning"] = warning
    if not enabled and not dry_run:
        command = run_command(ACTIONS[action])
        if command.returncode and action == "suspend":
            command = run_command(["loginctl", "suspend"])
        if command.returncode:
            result.update(ok=False, error="Automatic idle action failed")
    return result


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise AwakeError("Invalid arguments")


def main(argv=None):
    store = None
    try:
        parser = QuietParser(description=__doc__)
        commands = parser.add_subparsers(dest="action", required=True, parser_class=QuietParser)
        for action in ("status", "on", "off"):
            commands.add_parser(action)
        commands.add_parser("restore").add_argument("--legacy-on", action="store_true")
        commands.add_parser("hold").add_argument("session_hash")
        guarded = commands.add_parser("guard")
        guarded.add_argument("target", choices=tuple(ACTIONS))
        guarded.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv)
        if args.action == "guard":
            result = guard(args.target, args.dry_run)
        else:
            store = StateStore(create=args.action in ("on", "off", "restore"))
            if args.action == "hold":
                return hold(store, args.session_hash)
            if args.action == "status":
                result = status(store)
            else:
                result = control(store, args.action, getattr(args, "legacy_on", False))
    except AwakeError as error:
        result = {"ok": False, "inhibit": False, "backendActive": False, "error": str(error)}
    except Exception:
        result = {"ok": False, "inhibit": False, "backendActive": False, "error": "Keep-awake operation failed"}
    finally:
        if store is not None:
            store.close()
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

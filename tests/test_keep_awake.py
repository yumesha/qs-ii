"""Offline keep-awake contracts: all commands mocked, all state temporary."""

import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("keep_awake_helper", ROOT / "scripts/session/keep-awake.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
SIGNATURE = "synthetic_compositor_123_456"


class FakeSystem:
    def __init__(self):
        self.commands = []
        self.loaded = False
        self.active = False
        self.live = True
        self.pid = 4242
        self.block = True
        self.start_fail = False
        self.stop_fail = False
        self.action_failure = False
        self.on_start = None
        self.on_stop = None
        self.inhibitor_row = None
        self.bad_bus = None

    def __call__(self, argv):
        self.commands.append(list(argv))
        code, output = 0, ""
        if argv == ["hyprctl", "-j", "instances"]:
            output = json.dumps([{"instance": SIGNATURE, "pid": 111}] if self.live else [])
        elif argv[:3] == ["systemctl", "--user", "show"]:
            output = "LoadState={}\nActiveState={}\nMainPID={}\n".format(
                "loaded" if self.loaded else "not-found", "active" if self.active else "inactive",
                self.pid if self.active else 0)
        elif argv[0] == "busctl":
            key = helper.hashlib.sha256(SIGNATURE.encode()).hexdigest()[:16]
            row = self.inhibitor_row or ["idle", "qs-ii:" + key, "Keep system awake", "block", os.getuid(), self.pid]
            output = self.bad_bus if self.bad_bus is not None else json.dumps(
                {"type": "a(ssssuu)", "data": [[row] if self.block else []]})
        elif argv[0] == "systemd-run" or argv[:3] == ["systemctl", "--user", "start"]:
            if self.on_start:
                self.on_start()
            code = int(self.start_fail)
            if not code:
                self.loaded = self.active = True
        elif argv[:3] == ["systemctl", "--user", "stop"]:
            if self.on_stop:
                self.on_stop()
            code = int(self.stop_fail)
            if not code:
                self.loaded = self.active = False
        elif argv in list(helper.ACTIONS.values()) + [["loginctl", "suspend"]]:
            code = int(self.action_failure and argv == ["systemctl", "suspend"])
        else:
            raise AssertionError("Unexpected command: " + repr(argv))
        return subprocess.CompletedProcess(argv, code, output, "")


class KeepAwakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name)
        self.env = patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": str(self.runtime), "HYPRLAND_INSTANCE_SIGNATURE": SIGNATURE,
            "PATH": "/synthetic/bin",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        # A forgotten mock must fail instead of launching any real desktop command.
        blocker = patch("subprocess.Popen", side_effect=AssertionError("Real commands forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)
        self.system = FakeSystem()
        commands = patch.object(helper, "run_command", side_effect=self.system)
        self.runner = commands.start()
        self.addCleanup(commands.stop)
        paths = patch.object(helper.shutil, "which", return_value="/synthetic/bin/systemd-inhibit")
        paths.start()
        self.addCleanup(paths.stop)
        sleeper = patch.object(helper.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def store(self, create=True):
        store = helper.StateStore(create=create)
        self.addCleanup(store.close)
        return store

    def invoke(self, *argv):
        output = io.StringIO()
        with patch.object(helper.sys, "stdout", output):
            code = helper.main(list(argv))
        text = output.getvalue()
        self.assertNotIn(SIGNATURE, text)
        self.assertNotIn(str(self.runtime), text)
        self.assertNotIn("Traceback", text)
        return code, json.loads(text)

    def state_path(self, store):
        return self.runtime / "qs-ii" / "idle" / store.filename

    def write_raw(self, store, text):
        path = self.state_path(store)
        path.write_text(text)
        path.chmod(0o600)
        return path

    def test_status_missing_state_is_readonly(self):
        code, result = self.invoke("status")
        self.assertEqual(code, 0)
        self.assertEqual(result, {"ok": True, "inhibit": False, "backendActive": False})
        self.assertEqual(list(self.runtime.iterdir()), [])
        self.assertEqual(len(self.system.commands), 1)

    def test_on_writes_private_atomic_state_before_service_start(self):
        store = self.store()
        self.system.on_start = lambda: self.assertIs(store.read(), True)
        code, result = self.invoke("on")
        self.assertEqual(code, 0)
        self.assertEqual(result, {"ok": True, "inhibit": True, "backendActive": True})
        self.assertEqual(stat.S_IMODE(self.state_path(store).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state_path(store).parent.stat().st_mode), 0o700)
        self.assertEqual(json.loads(self.state_path(store).read_text()),
                         {"schema": 1, "session": SIGNATURE, "inhibit": True})
        self.assertFalse(list(self.state_path(store).parent.glob("*.tmp")))

    def test_service_is_independent_idle_only_and_session_bound(self):
        self.invoke("on")
        command = next(cmd for cmd in self.system.commands if cmd[0] == "systemd-run")
        for option in ("--user", "--collect", "--property=PartOf=graphical-session.target",
                       "--property=Restart=on-failure", "--what=idle", "--mode=block",
                       "--no-ask-password", "--expand-environment=no", "-B"):
            self.assertIn(option, command)
        self.assertTrue(any(value.startswith("--setenv=HYPRLAND_INSTANCE_SIGNATURE=") for value in command))
        self.assertTrue(any(value.startswith("--who=qs-ii:") for value in command))
        self.assertEqual(command[-2], "hold")
        self.assertRegex(command[-1], r"^[0-9a-f]{16}$")
        self.assertFalse(any("sleep:shutdown" in value or "quickshell.service" in value for value in command))

    def test_off_persists_false_before_stopping_and_restore_cannot_revive_legacy(self):
        store = self.store()
        self.invoke("on")
        self.system.on_stop = lambda: self.assertIs(store.read(), False)
        self.assertEqual(self.invoke("off")[0], 0)
        self.assertIs(store.read(), False)
        self.system.commands.clear()
        code, result = self.invoke("restore", "--legacy-on")
        self.assertEqual(code, 0)
        self.assertFalse(result["inhibit"])
        self.assertFalse(any(cmd[0] == "systemd-run" for cmd in self.system.commands))

    def test_restore_imports_true_only_once_and_preserves_existing_true(self):
        store = self.store()
        self.assertEqual(self.invoke("restore", "--legacy-on")[0], 0)
        self.assertIs(store.read(), True)
        self.assertEqual(self.invoke("restore")[0], 0)
        self.assertIs(store.read(), True)
        self.assertEqual(sum(cmd[0] == "systemd-run" for cmd in self.system.commands), 1)

    def test_restore_without_legacy_creates_explicit_false(self):
        store = self.store()
        code, result = self.invoke("restore")
        self.assertEqual(code, 0)
        self.assertIs(store.read(), False)
        self.assertFalse(result["inhibit"])

    def test_corrupt_restore_does_not_import_legacy_over_existing_file(self):
        store = self.store()
        self.write_raw(store, "not-json")
        code, result = self.invoke("restore", "--legacy-on")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(self.state_path(store).read_text(), "not-json")
        self.assertEqual(self.system.commands, [])

    def test_explicit_off_can_repair_corrupt_owned_state(self):
        store = self.store()
        self.write_raw(store, "not-json")
        self.assertEqual(self.invoke("off")[0], 0)
        self.assertIs(store.read(), False)

    def test_new_session_does_not_read_prior_session_marker(self):
        store = self.store()
        store.write(True)
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "different_session_7"}):
            different = self.store(create=False)
            self.assertNotEqual(store.key, different.key)
            self.assertIsNone(different.read())
            self.assertFalse(self.invoke("guard", "lock", "--dry-run")[1]["skipped"])

    def test_invalid_runtime_identity_and_permissions_do_not_mutate(self):
        for changes in ({"HYPRLAND_INSTANCE_SIGNATURE": ""},
                        {"HYPRLAND_INSTANCE_SIGNATURE": "not/safe"},
                        {"XDG_RUNTIME_DIR": "relative"}):
            with self.subTest(changes=changes), patch.dict(os.environ, changes):
                self.assertEqual(self.invoke("on")[0], 1)
        self.runtime.chmod(0o755)
        self.assertEqual(self.invoke("on")[0], 1)
        self.runtime.chmod(0o700)
        self.assertEqual(list(self.runtime.iterdir()), [])
        with patch.object(helper.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(self.invoke("on")[0], 1)

    def test_state_symlink_fifo_and_hardlink_are_not_followed(self):
        store = self.store()
        outside = self.runtime / "outside"
        outside.write_text("unchanged")
        outside.chmod(0o600)
        path = self.state_path(store)
        path.symlink_to(outside)
        self.assertEqual(self.invoke("on")[0], 1)
        self.assertFalse(self.invoke("guard", "lock", "--dry-run")[1]["skipped"])
        path.unlink()
        os.mkfifo(path, 0o600)
        self.assertFalse(self.invoke("guard", "lock", "--dry-run")[1]["skipped"])
        path.unlink()
        os.link(outside, path)
        self.assertEqual(self.invoke("on")[0], 1)
        self.assertEqual(outside.read_text(), "unchanged")

    def test_symlink_state_directory_is_rejected(self):
        (self.runtime / "qs-ii").symlink_to(self.runtime, target_is_directory=True)
        self.assertEqual(self.invoke("on")[0], 1)
        self.assertEqual(self.system.commands, [])

    def test_schema_boolean_session_and_size_are_strict(self):
        store = self.store()
        invalid = ["[]", "null", "x" * 4097,
                   json.dumps({"schema": True, "session": SIGNATURE, "inhibit": True}),
                   json.dumps({"schema": 1, "session": "old", "inhibit": True}),
                   json.dumps({"schema": 1, "session": SIGNATURE, "inhibit": "true"})]
        for raw in invalid:
            with self.subTest(raw=raw[:50]):
                self.write_raw(store, raw)
                self.assertFalse(self.invoke("guard", "lock", "--dry-run")[1]["skipped"])
        self.assertEqual(self.system.commands, [])

    def test_atomic_replace_failure_preserves_old_authoritative_value(self):
        store = self.store()
        store.write(False)
        with patch.object(helper.os, "replace", side_effect=OSError("private-details")):
            self.assertEqual(self.invoke("on")[0], 1)
        self.assertIs(store.read(), False)
        self.assertEqual(list(self.state_path(store).parent.glob(".*.tmp")), [])

    def test_toggle_uses_exclusive_session_lock(self):
        store = self.store()
        with patch.object(helper.fcntl, "flock", wraps=helper.fcntl.flock) as lock:
            self.assertEqual(self.invoke("off")[0], 0)
            self.assertEqual(lock.call_args.args[1], helper.fcntl.LOCK_EX | helper.fcntl.LOCK_NB)
        self.assertTrue((self.state_path(store).parent / (store.key + ".lock")).exists())

    def test_lock_contention_has_bounded_wait(self):
        with patch.object(helper.fcntl, "flock", side_effect=BlockingIOError), \
             patch.object(helper.time, "monotonic", side_effect=[0, 11]):
            code, result = self.invoke("on")
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "Keep-awake control is busy")
        self.assertEqual(self.system.commands, [])

    def test_on_refuses_missing_compositor_and_leaves_no_state(self):
        store = self.store()
        self.system.live = False
        self.assertEqual(self.invoke("on")[0], 1)
        self.assertIsNone(store.read())

    def test_start_failure_keeps_authoritative_true_and_guard_works(self):
        self.system.start_fail = True
        code, result = self.invoke("on")
        self.assertEqual(code, 1)
        self.assertTrue(result["inhibit"])
        self.assertFalse(result["backendActive"])
        self.system.commands.clear()
        self.assertTrue(self.invoke("guard", "lock")[1]["skipped"])
        self.assertEqual(self.system.commands, [])

    def test_stop_failure_reports_remaining_inhibitor_but_keeps_false(self):
        self.invoke("on")
        self.system.stop_fail = True
        code, result = self.invoke("off")
        self.assertEqual(code, 1)
        self.assertFalse(result["inhibit"])
        self.assertTrue(result["backendActive"])
        self.assertFalse(self.invoke("guard", "lock", "--dry-run")[1]["skipped"])

    def test_active_unit_without_idle_block_is_not_confirmed(self):
        self.system.block = False
        code, result = self.invoke("on")
        self.assertEqual(code, 1)
        self.assertTrue(result["inhibit"])
        self.assertFalse(result["backendActive"])
        self.assertEqual(result["error"], "Idle inhibitor acquisition not confirmed")

    def test_backend_matches_uid_pid_who_mode_and_idle_token(self):
        store = self.store()
        self.system.loaded = self.system.active = True
        valid = ["idle:sleep", store.who, "reason", "block", os.getuid(), self.system.pid]
        self.system.inhibitor_row = valid
        self.assertTrue(helper.backend_active(store))
        for index, replacement in ((0, "sleep"), (1, "another"), (3, "delay"),
                                   (4, os.getuid() + 1), (5, self.system.pid + 1)):
            row = valid.copy()
            row[index] = replacement
            self.system.inhibitor_row = row
            self.assertFalse(helper.backend_active(store))

    def test_invalid_logind_json_is_reported_without_raw_payload(self):
        store = self.store()
        store.write(True)
        self.system.loaded = self.system.active = True
        for payload in ("private-json-garbage", "[]", '{"type":"a(ssssuu)","data":[[[]]]}'):
            self.system.bad_bus = payload
            code, result = self.invoke("status")
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "Cannot verify logind idle inhibitor")

    def test_readonly_status_does_not_reconcile_a_missing_backend(self):
        store = self.store()
        store.write(True)
        code, result = self.invoke("status")
        self.assertEqual(code, 1)
        self.assertTrue(result["inhibit"])
        self.assertFalse(result["backendActive"])
        self.assertFalse(any(cmd[0] == "systemd-run" for cmd in self.system.commands))

    def test_hold_exits_on_false_missing_or_invalid_state_without_commands(self):
        store = self.store()
        for value in (None, False, "invalid"):
            if value == "invalid":
                self.write_raw(store, "invalid")
            elif value is False:
                store.write(False)
            self.assertEqual(helper.hold(store, store.key), 0)
        self.assertEqual(self.system.commands, [])

    def test_hold_rechecks_state_and_compositor_without_qs_dependency(self):
        store = self.store()
        store.write(True)
        self.sleep.side_effect = lambda _: store.write(False)
        self.assertEqual(helper.hold(store, store.key), 0)
        self.assertEqual(self.system.commands, [["hyprctl", "-j", "instances"]])
        store.write(True)
        self.system.live = False
        self.assertEqual(helper.hold(store, store.key), 0)
        self.assertIs(store.read(), True)
        with self.assertRaises(helper.AwakeError):
            helper.hold(store, "0" * 16)

    def test_every_guard_action_skips_when_authoritative_on(self):
        self.store().write(True)
        for target in helper.ACTIONS:
            self.assertTrue(self.invoke("guard", target)[1]["skipped"])
        self.assertEqual(self.system.commands, [])

    def test_dry_run_never_spawns_even_with_missing_or_invalid_state(self):
        for target in helper.ACTIONS:
            code, result = self.invoke("guard", target, "--dry-run")
            self.assertEqual(code, 0)
            self.assertFalse(result["skipped"])
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}):
            self.assertEqual(self.invoke("guard", "lock", "--dry-run")[0], 0)
        self.assertEqual(self.system.commands, [])
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_missing_invalid_and_false_state_allow_only_fixed_actions(self):
        self.invoke("guard", "lock")
        self.assertEqual(self.system.commands, [["loginctl", "lock-session"]])
        store = self.store()
        store.write(False)
        self.invoke("guard", "dpms-off")
        self.assertEqual(self.system.commands[-1], ["hyprctl", "dispatch", "dpms", "off"])
        self.write_raw(store, "invalid")
        self.invoke("guard", "lock")
        self.assertEqual(self.system.commands[-1], ["loginctl", "lock-session"])

    def test_suspend_fallback_only_after_nonzero_systemctl_exit(self):
        self.system.action_failure = True
        self.assertEqual(self.invoke("guard", "suspend")[0], 0)
        self.assertEqual(self.system.commands, [["systemctl", "suspend"], ["loginctl", "suspend"]])
        self.system.commands.clear()
        self.system.action_failure = False
        self.invoke("guard", "suspend")
        self.assertEqual(self.system.commands, [["systemctl", "suspend"]])

    def test_suspend_timeout_does_not_issue_second_suspend(self):
        with patch.object(helper, "run_command", side_effect=helper.AwakeError("Command timed out")) as command:
            self.assertEqual(self.invoke("guard", "suspend")[0], 1)
        self.assertEqual(command.call_count, 1)

    def test_cli_rejects_unlisted_actions_and_does_not_echo_arguments(self):
        for argv in (("guard", "private-secret-value"), ("on", "--legacy-on"), ("restore", "extra")):
            code, result = self.invoke(*argv)
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "Invalid arguments")
        self.assertEqual(self.system.commands, [])
        self.assertEqual(list(self.runtime.iterdir()), [])


class CommandBoundaryTests(unittest.TestCase):
    def test_subprocess_is_bounded_captured_and_shell_free(self):
        with patch.object(helper.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            helper.run_command(["loginctl", "lock-session"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["loginctl", "lock-session"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertGreater(kwargs["timeout"], 0)

    def test_timeout_and_os_error_do_not_expose_external_details(self):
        for error in (subprocess.TimeoutExpired("private-value", 1), OSError("private-value")):
            with patch.object(helper.subprocess, "run", side_effect=error):
                with self.assertRaises(helper.AwakeError) as raised:
                    helper.run_command(["synthetic"])
                self.assertNotIn("private-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

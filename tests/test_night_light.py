"""Behavioral night-light checks; commands and delays are always mocked."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
QUERY = ["hyprctl", "hyprsunset", "temperature"]
IDENTITY = ["hyprctl", "hyprsunset", "identity"]
PRIVATE = "synthetic-private-diagnostic"


def reply(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(QUERY, code, stdout, stderr)


def absent():
    return reply(stderr="Couldn't connect: " + PRIVATE, code=1)


class NightLightTests(unittest.TestCase):
    def setUp(self):
        self.run = self.start_patch("subprocess.run", side_effect=AssertionError("Unscripted command"))
        self.popen = self.start_patch("subprocess.Popen", side_effect=AssertionError("Unscripted launch"))
        for name in ("call", "check_call", "check_output"):
            self.start_patch("subprocess." + name, side_effect=AssertionError("Unexpected subprocess API"))
        self.sleep = self.start_patch("time.sleep")
        spec = importlib.util.spec_from_file_location("night_light_helper", ROOT / "scripts/session/night-light.py")
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def tearDown(self):
        for invocation in self.run.call_args_list:
            args, kwargs = invocation
            self.assertEqual(len(args), 1)
            command = args[0]
            if command not in (QUERY, IDENTITY):
                self.assertEqual(command[:3], QUERY)
                self.assertEqual(len(command), 4)
                self.assertTrue(command[3].isdecimal())
                self.assertTrue(1000 <= int(command[3]) <= 20000)
            self.assertFalse(kwargs.get("shell", False))
            self.assertTrue(kwargs["capture_output"] and kwargs["text"])
            self.assertTrue(0 < kwargs["timeout"] <= 4)
        for invocation in self.popen.call_args_list:
            args, kwargs = invocation
            self.assertEqual(args[0][:2], ["hyprsunset", "--temperature"])
            self.assertEqual(len(args[0]), 3)
            self.assertEqual(kwargs, {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                     "stderr": subprocess.DEVNULL, "start_new_session": True, "close_fds": True})

    def commands_are(self, *commands):
        self.assertEqual([entry.args[0] for entry in self.run.call_args_list], list(commands))

    def allow_start(self):
        self.popen.side_effect = None
        self.popen.return_value = Mock(spec=[])

    def assert_safe_error(self, function, *arguments):
        with self.assertRaises(self.helper.NightLightError) as raised:
            function(*arguments)
        self.assertNotIn(PRIVATE, str(raised.exception))

    def invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(self.helper.sys, "argv", ["night-light.py", *arguments]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = self.helper.main()
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertNotIn(PRIVATE, output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        return code, json.loads(output.getvalue())

    def test_temperature_distinguishes_numeric_absent_and_invalid_responses(self):
        self.run.side_effect = [reply(" 5000\n"), absent()]
        self.assertEqual(self.helper.temperature(), 5000)
        self.assertIsNone(self.helper.temperature())
        for result in (reply(""), reply("5000 K"), reply("5000\n6500"), reply(PRIVATE), reply("5000", PRIVATE, 1)):
            self.run.side_effect = [result]
            self.assert_safe_error(self.helper.temperature)
        self.popen.assert_not_called()

    def test_on_always_exits_identity_even_when_reported_kelvin_matches(self):
        # Identity leaves the numeric query unchanged, including at 6500 K.
        for target in (1000, 5000, 6500, 20000):
            with self.subTest(target=target):
                self.run.reset_mock()
                self.run.side_effect = [reply(str(target)), reply("ok"), reply(str(target))]
                self.assertEqual(self.helper.apply(True, target), {"active": True, "temperature": target})
                self.commands_are(QUERY, QUERY + [str(target)], QUERY)
        self.popen.assert_not_called()

    def test_off_requests_identity_not_a_6500_kelvin_transform(self):
        for current in (5000, 6500):
            with self.subTest(current=current):
                self.run.reset_mock()
                self.run.side_effect = [reply(str(current)), reply("ok")]
                self.assertEqual(self.helper.apply(False, 4200), {"active": False, "temperature": None})
                self.commands_are(QUERY, IDENTITY)
        self.popen.assert_not_called()

    def test_off_with_absent_backend_does_not_start_one(self):
        self.run.side_effect = [absent()]
        self.assertEqual(self.helper.apply(False, 5000), {"active": False, "temperature": None})
        self.commands_are(QUERY)
        self.popen.assert_not_called()

    def test_on_starts_only_an_absent_backend_detached_then_applies_and_verifies(self):
        self.run.side_effect = [absent(), absent(), reply("6500"), reply("ok"), reply("5000")]
        self.allow_start()
        self.assertEqual(self.helper.apply(True, 5000), {"active": True, "temperature": 5000})
        self.commands_are(QUERY, QUERY, QUERY, QUERY + ["5000"], QUERY)
        self.popen.assert_called_once()

    def test_readiness_accepts_last_attempt_and_stops_at_its_bound(self):
        self.allow_start()
        self.run.side_effect = [absent()] * 20 + [reply("5000"), reply("ok"), reply("5000")]
        self.assertTrue(self.helper.apply(True, 5000)["active"])
        self.assertEqual(self.sleep.call_count, 20)
        self.popen.assert_called_once()
        self.run.reset_mock(); self.popen.reset_mock(); self.sleep.reset_mock()
        self.run.side_effect = [absent()] * 21
        self.assert_safe_error(self.helper.apply, True, 5000)
        self.assertEqual(self.run.call_count, 21)
        self.assertEqual(self.sleep.call_count, 20)
        self.popen.assert_called_once()

    def test_launch_and_transport_failures_do_not_leak_diagnostics(self):
        self.run.side_effect = [absent()]
        self.popen.side_effect = OSError(PRIVATE)
        self.assert_safe_error(self.helper.apply, True, 5000)
        self.sleep.assert_not_called()
        for error in (OSError(PRIVATE), subprocess.TimeoutExpired(QUERY, 4, output=PRIVATE)):
            self.run.side_effect = error
            self.assert_safe_error(self.helper.temperature)

    def test_set_requires_success_acknowledgement_for_both_modes(self):
        for enabled in (True, False):
            for response in (reply(PRIVATE, PRIVATE, 1), reply("invalid command")):
                self.run.side_effect = [reply("5000"), response]
                self.assert_safe_error(self.helper.apply, enabled, 5000)
        self.popen.assert_not_called()

    def test_on_requires_matching_readback(self):
        for response in (reply("4500"), absent(), reply(PRIVATE, PRIVATE, 1)):
            self.run.side_effect = [reply("6500"), reply("ok"), response]
            self.assert_safe_error(self.helper.apply, True, 5000)
        self.popen.assert_not_called()

    def test_invalid_inputs_fail_before_io(self):
        for enabled in (True, False):
            for target in (999, 20001, 5000.0, "5000", None, True):
                self.assert_safe_error(self.helper.apply, enabled, target)
        for enabled in (None, 0, 1, "on"):
            self.assert_safe_error(self.helper.apply, enabled, 5000)
        self.run.assert_not_called()
        self.popen.assert_not_called()

    def test_cli_returns_single_sanitized_json_response(self):
        self.run.side_effect = [reply("5000"), reply("ok"), reply("5000"), absent()]
        self.assertEqual(self.invoke("on", "5000"), (0, {"ok": True, "active": True, "temperature": 5000}))
        self.assertEqual(self.invoke("off", "5000"), (0, {"ok": True, "active": False, "temperature": None}))
        self.run.side_effect = [reply(PRIVATE, PRIVATE, 1)]
        code, response = self.invoke("on", "5000")
        self.assertEqual(code, 1)
        self.assertFalse(response["ok"])

    def test_bad_cli_arguments_never_reach_backend(self):
        for arguments in ((), (PRIVATE, "5000"), ("on",), ("on", "5000", PRIVATE), ("on", PRIVATE), ("off", "999")):
            code, response = self.invoke(*arguments)
            self.assertEqual(code, 1)
            self.assertFalse(response["ok"])
        self.run.assert_not_called()
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

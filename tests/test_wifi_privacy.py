"""Offline privacy contracts for the stdin helper and saved-profile options."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wifi_privacy_helper", ROOT / "scripts/network/wifi-profiles.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
SENTINEL = "synthetic-private-value-do-not-use"
UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        blocker = patch("subprocess.Popen", side_effect=AssertionError("Real commands forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def invoke(self, payload, action="connect", handler=None):
        output = io.StringIO()
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        with patch.object(sys, "argv", ["wifi-profiles.py", action]), \
             patch.object(sys, "stdin", io.StringIO(raw)), \
             patch.object(sys, "stdout", output), \
             patch.object(helper.resource, "setrlimit"), patch.object(helper.os, "umask"), \
             patch.object(helper, "private_action", side_effect=handler or (lambda *_: {})):
            code = helper.main()
        text = output.getvalue()
        self.assertNotIn(SENTINEL, text)
        return code, json.loads(text)

    def test_credentials_arrive_via_stdin_and_payload_is_cleared_after_dispatch(self):
        captured = []
        def handle(action, payload):
            self.assertEqual(action, "connect")
            self.assertEqual(payload["password"], SENTINEL)
            self.assertNotIn(SENTINEL, sys.argv)
            captured.append(payload)
            return {}
        code, result = self.invoke({"ssid": "Demo Hidden", "password": SENTINEL}, handler=handle)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(captured, [{}])

    def test_unexpected_native_exception_does_not_echo_credentials_or_traceback(self):
        def fail(*_):
            raise RuntimeError(SENTINEL)
        code, result = self.invoke({"password": SENTINEL}, handler=fail)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertNotIn("Traceback", json.dumps(result))

    def test_malformed_json_does_not_echo_input(self):
        code, result = self.invoke('{"password": "' + SENTINEL)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])

    def test_oversized_input_is_rejected_before_dispatch(self):
        code, result = self.invoke(SENTINEL + "x" * 17000)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])

    def test_autoconnect_only_modifies_verified_wifi_uuid(self):
        with patch.object(helper, "validate_profile") as validate, patch.object(helper, "run_nmcli", return_value="") as run:
            helper.set_autoconnect({"ssid": "Demo", "uuid": UUID, "enabled": False})
        validate.assert_called_once_with(UUID, "Demo")
        run.assert_called_once_with(["connection", "modify", "uuid", UUID, "connection.autoconnect", "no"])

    def test_autoconnect_refuses_non_boolean_and_mismatched_profile(self):
        with patch.object(helper, "run_nmcli") as run:
            with self.assertRaises(helper.WifiError):
                helper.set_autoconnect({"ssid": "Demo", "uuid": UUID, "enabled": "yes"})
            run.assert_not_called()
        with patch.object(helper, "validate_profile", side_effect=helper.WifiError("Wrong type")), patch.object(helper, "run_nmcli") as run:
            with self.assertRaises(helper.WifiError):
                helper.set_autoconnect({"ssid": "Demo", "uuid": UUID, "enabled": True})
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

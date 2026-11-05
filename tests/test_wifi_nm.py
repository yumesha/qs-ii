"""Offline contracts for native Wi-Fi operations; all identities/networks are fake.

Run with: python3 -B -m unittest discover -s tests -p 'test_wifi_nm.py' -v
No NetworkManager connection, subprocess, real user lookup, or sleep is allowed.
"""

from collections import deque
from copy import deepcopy
import ctypes
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid


NETWORK_DIR = Path(__file__).resolve().parents[1] / "scripts/network"
FORBIDDEN = AssertionError("Live processes, native libraries, and buses are forbidden in Wi-Fi tests")
ADAPTER_SPEC = importlib.util.spec_from_file_location("_wifi_nm_test_gio_dbus", NETWORK_DIR / "gio_dbus.py")
adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
with mock.patch.dict(sys.modules, {ADAPTER_SPEC.name: adapter}), \
        mock.patch.object(subprocess, "Popen", side_effect=FORBIDDEN), \
        mock.patch.object(ctypes, "CDLL", side_effect=FORBIDDEN):
    ADAPTER_SPEC.loader.exec_module(adapter)
SPEC = importlib.util.spec_from_file_location("_wifi_nm_under_test", NETWORK_DIR / "wifi_nm.py")
nm = importlib.util.module_from_spec(SPEC)
with mock.patch.dict(sys.modules, {"gio_dbus": adapter}), \
        mock.patch.object(adapter, "SystemBus", side_effect=FORBIDDEN), \
        mock.patch.object(subprocess, "Popen", side_effect=FORBIDDEN), \
        mock.patch.object(ctypes, "CDLL", side_effect=FORBIDDEN):
    SPEC.loader.exec_module(nm)

V = nm.Variant
UUID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_NEW = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PROFILE_A = nm.ROOT + "/Settings/101"
PROFILE_B = nm.ROOT + "/Settings/102"
PROFILE_NEW = nm.ROOT + "/Settings/103"
DEVICE_A = nm.ROOT + "/Devices/101"
DEVICE_B = nm.ROOT + "/Devices/102"
ETHERNET = nm.ROOT + "/Devices/103"
ACTIVE_A = nm.ROOT + "/ActiveConnection/101"
ACTIVE_OTHER = nm.ROOT + "/ActiveConnection/102"
AP_A = nm.ROOT + "/AccessPoint/101"
SSID = "  Fictional:雪  "
PASSWORD = "  fictional $(); psk  "
BSSID = "02:00:00:00:00:01"
RAW_DIAGNOSTIC = "fictional-raw-diagnostic-never-return"


class SyntheticDBusError(nm.DBusError):
    """Simulate a backend with unsafe diagnostics to check error translation."""

    def __str__(self):
        return RAW_DIAGNOSTIC


class StrictBus:
    """An ordered, exact call allowlist; unknown calls never reach a real bus."""

    def __init__(self, case):
        self.case = case
        self.pending = deque()
        self.calls = []

    def expect(self, path, interface, method, signature, args, reply=(), error=None):
        self.pending.append(((path, interface, method, signature, deepcopy(args)), deepcopy(reply), error))
        return self

    def call(self, path, interface, method, signature, args, *, timeout_ms=10000):
        self.case.assertEqual(timeout_ms, 120000 if method == "Update2" else 10000,
                              "Protected profile updates must allow time for an administrator prompt")
        self.case.assertNotEqual(method, "GetSecrets", "Secret retrieval is never permitted")
        actual = (path, interface, method, signature, args)
        self.calls.append(deepcopy(actual))
        self.case.assertTrue(self.pending, f"Unapproved D-Bus method: {interface}.{method}")
        expected, reply, error = self.pending.popleft()
        self.case.assertEqual(actual, expected)
        if error is not None:
            raise error
        return reply

    def complete(self):
        self.case.assertFalse(self.pending, "Expected D-Bus calls were not consumed")


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def device_details(interface="fixture-wifi0", kind=2, state=30, active="/"):
    return {"Interface": V("s", interface), "DeviceType": V("u", kind),
            "State": V("u", state), "ActiveConnection": V("o", active)}


def profile(profile_uuid=UUID_A, ssid=SSID, security="wpa-psk", hidden=False, auto=True, kind="802-11-wireless"):
    settings = {
        "connection": {"uuid": V("s", profile_uuid), "id": V("s", "Renamed synthetic profile"),
                       "type": V("s", kind), "autoconnect": V("b", auto),
                       "permissions": V("as", ["user:fixture-owner:"])},
        "802-11-wireless": {"ssid": V("ay", list(ssid.encode("utf-8"))), "hidden": V("b", hidden)},
        "ipv4": {"method": V("s", "auto")}, "ipv6": {"method": V("s", "auto")},
    }
    if security != "open":
        settings["802-11-wireless-security"] = {"key-mgmt": V("s", security), "psk-flags": V("u", 0)}
    return settings


def new_settings(ssid=SSID, security="wpa-psk", password=PASSWORD, hidden=False, auto=True):
    settings = {
        "connection": {"id": V("s", ssid), "uuid": V("s", UUID_NEW),
                       "type": V("s", "802-11-wireless"), "autoconnect": V("b", auto),
                       "permissions": V("as", ["user:fixture-user:"])},
        "802-11-wireless": {"ssid": V("ay", list(ssid.encode("utf-8"))),
                            "mode": V("s", "infrastructure"), "hidden": V("b", hidden)},
        "ipv4": {"method": V("s", "auto")}, "ipv6": {"method": V("s", "auto")},
    }
    if security != "open":
        settings["802-11-wireless-security"] = {
            "key-mgmt": V("s", security), "psk": V("s", password), "psk-flags": V("u", 0)}
    return settings


class NativeWifiCase(unittest.TestCase):
    def setUp(self):
        self.bus = StrictBus(self)
        self.clock = FakeClock()
        patches = [
            mock.patch.object(subprocess, "Popen", side_effect=FORBIDDEN),
            mock.patch.object(subprocess, "run", side_effect=FORBIDDEN),
            mock.patch.object(ctypes, "CDLL", side_effect=FORBIDDEN),
            mock.patch.object(socket, "socket", side_effect=FORBIDDEN),
            mock.patch.object(nm, "SystemBus", side_effect=FORBIDDEN),
            mock.patch.object(adapter, "SystemBus", side_effect=FORBIDDEN),
            mock.patch.object(nm.os, "system", side_effect=FORBIDDEN),
            mock.patch.object(nm.os, "popen", side_effect=FORBIDDEN),
            mock.patch.object(nm.os, "getuid", return_value=424242),
            mock.patch.object(nm.pwd, "getpwuid", return_value=SimpleNamespace(pw_name="fixture-user")),
            mock.patch.object(nm.uuid, "uuid4", return_value=uuid.UUID(UUID_NEW)),
            mock.patch.object(nm.time, "monotonic", side_effect=self.clock.monotonic),
            mock.patch.object(nm.time, "sleep", side_effect=self.clock.sleep),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.bus.complete()

    def props(self, path, interface, details=None, error=None):
        self.bus.expect(path, nm.PROPERTIES, "GetAll", "(s)", (interface,), (details or {},), error)

    def manager(self, enabled=True):
        self.props(nm.ROOT, nm.MANAGER, {"WirelessEnabled": V("b", enabled)})

    def devices(self, entries=None):
        if entries is None:
            entries = [(DEVICE_A, device_details())]
        self.bus.expect(nm.ROOT, nm.MANAGER, "GetDevices", "()", (), ([p for p, _ in entries],))
        for path, details in entries:
            self.props(path, nm.DEVICE, details)

    def profiles(self, entries=()):
        self.bus.expect(nm.ROOT + "/Settings", nm.SETTINGS, "ListConnections", "()", (), ([p for p, _ in entries],))
        for path, settings in entries:
            if isinstance(settings, Exception):
                self.bus.expect(path, nm.CONNECTION, "GetSettings", "()", (), error=settings)
            else:
                self.bus.expect(path, nm.CONNECTION, "GetSettings", "()", (), (settings,))

    def connect_setup(self, entries=(), ap=False):
        self.manager()
        self.devices()
        if ap:
            self.bus.expect(DEVICE_A, nm.WIRELESS, "GetAccessPoints", "()", (), ([AP_A],))
            self.props(AP_A, nm.AP, {"HwAddress": V("s", BSSID), "Ssid": V("ay", list(SSID.encode("utf-8")))})
        self.profiles(entries)

    def activate_call(self, path=PROFILE_A, ap="/", error=None):
        self.bus.expect(nm.ROOT, nm.MANAGER, "ActivateConnection", "(ooo)", (path, DEVICE_A, ap), (ACTIVE_A,), error)

    def add_call(self, settings, ap="/", error=None):
        self.bus.expect(nm.ROOT, nm.MANAGER, "AddAndActivateConnection2", "(a{sa{sv}}ooa{sv})",
                        (settings, DEVICE_A, ap, {"persist": V("s", "disk")}), (PROFILE_NEW, ACTIVE_A, {}), error)

    def update_call(self, settings, error=None):
        self.bus.expect(PROFILE_A, nm.CONNECTION, "Update2", "(a{sa{sv}}ua{sv})", (settings, 1, {}), ({},), error)

    def activated(self):
        self.props(ACTIVE_A, nm.ACTIVE, {"State": V("u", 2)})

    def assert_network_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(nm.NetworkError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(RAW_DIAGNOSTIC, str(caught.exception))
        return caught.exception


class InputValidationTests(NativeWifiCase):
    def test_exact_hidden_ssid_keeps_whitespace_unicode_and_metacharacters(self):
        for ssid in (SSID, " ", "\tfixture\n", '$(fictional);"quoted"', "a" * 32, "雪" * 10 + "ab", "é" * 16):
            with self.subTest(ssid=ssid):
                self.assertEqual(nm.checked_ssid({"ssid": ssid}), ssid)

    def test_ssid_rejects_empty_nul_wrong_type_and_more_than_32_utf8_bytes(self):
        for ssid in (None, "", 7, False, [], {}, b"fixture", "fixture\0name", "a" * 33, "雪" * 11, "é" * 17):
            with self.subTest(ssid=ssid):
                self.assert_network_error("invalid-input", nm.checked_ssid, {"ssid": ssid})

    def test_ssid_rejects_nonencodable_unicode_with_safe_network_error(self):
        self.assert_network_error("invalid-input", nm.checked_ssid, {"ssid": "\ud800"})

    def test_invalid_connect_ssid_never_queries_bus(self):
        self.assert_network_error("invalid-input", nm.connect, self.bus, {"ssid": ""})

    def test_options_require_real_booleans_not_truthy_values(self):
        self.assertTrue(nm.checked_bool({}, "hidden", True))
        self.assertFalse(nm.checked_bool({"hidden": False}, "hidden", True))
        for bad in (None, "false", 0, 1, [], {}):
            for key in ("hidden", "autoconnect"):
                with self.subTest(key=key, value=bad):
                    self.assert_network_error("invalid-input", nm.connect, self.bus, {"ssid": SSID, key: bad})

    def test_open_network_has_no_security_section_and_rejects_password(self):
        self.assertIsNone(nm.security_settings("open", ""))
        self.assert_network_error("invalid-input", nm.security_settings, "open", PASSWORD)

    def test_wpa2_accepts_exact_8_to_63_byte_passwords_and_64_hex_key(self):
        for password in ("x" * 8, "x" * 63, "aB09" * 16, PASSWORD, "é" * 4):
            with self.subTest(password=password):
                self.assertEqual(nm.security_settings("wpa-psk", password),
                                 {"key-mgmt": V("s", "wpa-psk"), "psk": V("s", password), "psk-flags": V("u", 0)})

    def test_wpa2_rejects_short_overlong_and_nonhex_64_byte_passwords(self):
        for password in ("", "x" * 7, "x" * 64, "a" * 65, "é" * 32):
            with self.subTest(password=password):
                self.assert_network_error("invalid-password", nm.security_settings, "wpa-psk", password)

    def test_wpa3_accepts_1_to_63_utf8_bytes_without_trimming(self):
        for password in ("x", " ", "x" * 63, "é" * 31 + "x", PASSWORD):
            with self.subTest(password=password):
                self.assertEqual(nm.security_settings("sae", password)["psk"], V("s", password))

    def test_wpa3_rejects_empty_overlong_and_64_digit_hex_keys(self):
        for password in ("", "x" * 64, "a" * 64, "é" * 32):
            with self.subTest(password=password):
                self.assert_network_error("invalid-password", nm.security_settings, "sae", password)

    def test_personal_security_rejects_nonstrings_and_nul(self):
        for security in ("wpa-psk", "sae"):
            for password in (None, False, 42, [], {}, b"fictional", "fictional\0password"):
                with self.subTest(security=security, password=password):
                    self.assert_network_error("password-required", nm.security_settings, security, password)

    def test_password_rejects_nonencodable_unicode_safely(self):
        for security in ("wpa-psk", "sae"):
            with self.subTest(security=security), self.assertRaises(nm.NetworkError):
                nm.security_settings(security, "\ud800")

    def test_unsupported_security_is_rejected_not_downgraded(self):
        for security in ("wep", "wpa-eap", "802.1x", "", None, [], 42):
            with self.subTest(security=security):
                self.assert_network_error("unsupported-security", nm.security_settings, security, PASSWORD)

    def test_ssid_decoder_requires_typed_and_valid_utf8_bytes(self):
        self.assertEqual(nm.ssid_of(profile()), SSID)
        for raw in ([255], [-1], [256], None):
            with self.subTest(raw=raw):
                self.assertIsNone(nm.ssid_of({"802-11-wireless": {"ssid": V("ay", raw)}}))


class DeviceSelectionTests(NativeWifiCase):
    def test_selects_only_wifi_not_ethernet(self):
        self.manager()
        self.devices([(ETHERNET, device_details("fixture-ethernet0", 1)), (DEVICE_A, device_details())])
        self.assertEqual(nm.choose_device(self.bus), DEVICE_A)

    def test_requested_ethernet_is_rejected_even_when_wifi_exists(self):
        self.manager()
        self.devices([(ETHERNET, device_details("fixture-ethernet0", 1)), (DEVICE_A, device_details())])
        self.assert_network_error("unavailable", nm.choose_device, self.bus, "fixture-ethernet0")

    def test_missing_requested_wifi_is_rejected(self):
        self.manager()
        self.devices()
        self.assert_network_error("unavailable", nm.choose_device, self.bus, "fictional-missing")

    def test_no_wifi_adapter_is_rejected(self):
        self.manager()
        self.devices([(ETHERNET, device_details("fixture-ethernet0", 1))])
        self.assert_network_error("unavailable", nm.choose_device, self.bus)

    def test_multiple_wifi_adapters_require_explicit_choice(self):
        self.manager()
        self.devices([(DEVICE_A, device_details()), (DEVICE_B, device_details("fixture-wifi1"))])
        self.assert_network_error("unavailable", nm.choose_device, self.bus)

    def test_explicit_wifi_adapter_resolves_ambiguity(self):
        self.manager()
        self.devices([(DEVICE_A, device_details()), (DEVICE_B, device_details("fixture-wifi1"))])
        self.assertEqual(nm.choose_device(self.bus, "fixture-wifi1"), DEVICE_B)

    def test_unavailable_or_unmanaged_wifi_is_rejected(self):
        for state in (0, 10, 20, 29):
            with self.subTest(state=state):
                self.manager()
                self.devices([(DEVICE_A, device_details(state=state))])
                self.assert_network_error("unavailable", nm.choose_device, self.bus)

    def test_wifi_disabled_never_enumerates_devices(self):
        self.manager(False)
        self.assert_network_error("disabled", nm.choose_device, self.bus)

    def test_invalid_requested_device_never_enumerates_devices(self):
        for requested in (None, [], 1):
            with self.subTest(requested=requested):
                self.manager()
                self.assert_network_error("invalid-input", nm.choose_device, self.bus, requested)

    def test_access_point_requires_exact_ssid_and_matching_bssid(self):
        self.bus.expect(DEVICE_A, nm.WIRELESS, "GetAccessPoints", "()", (), ([AP_A],))
        self.props(AP_A, nm.AP, {"HwAddress": V("s", BSSID), "Ssid": V("ay", list(SSID.encode("utf-8")))})
        self.assertEqual(nm.access_point(self.bus, DEVICE_A, SSID, BSSID.upper()), AP_A)

    def test_access_point_with_changed_ssid_is_rejected(self):
        self.bus.expect(DEVICE_A, nm.WIRELESS, "GetAccessPoints", "()", (), ([AP_A],))
        self.props(AP_A, nm.AP, {"HwAddress": V("s", BSSID), "Ssid": V("ay", list(SSID.strip().encode("utf-8")))})
        self.assert_network_error("unavailable", nm.access_point, self.bus, DEVICE_A, SSID, BSSID)

    def test_missing_access_point_is_rejected_without_activation(self):
        self.bus.expect(DEVICE_A, nm.WIRELESS, "GetAccessPoints", "()", (), ([],))
        self.assert_network_error("unavailable", nm.access_point, self.bus, DEVICE_A, SSID, BSSID)

    def test_invalid_access_point_type_never_scans(self):
        self.assert_network_error("invalid-input", nm.access_point, self.bus, DEVICE_A, SSID, ["fictional"])

    def test_no_bssid_uses_root_object_without_scan(self):
        self.assertEqual(nm.access_point(self.bus, DEVICE_A, SSID, ""), "/")


class SavedProfilesTests(NativeWifiCase):
    def test_saved_activation_requires_uuid_and_exact_ssid_not_display_name(self):
        settings = profile()
        self.profiles([(PROFILE_A, settings)])
        self.manager()
        self.devices()
        self.activate_call()
        self.activated()
        self.assertEqual(nm.activate(self.bus, {"uuid": UUID_A.upper(), "ssid": SSID}), {})

    def test_saved_ssid_mismatch_refuses_before_activation(self):
        self.profiles([(PROFILE_A, profile())])
        self.assert_network_error("stale-profile", nm.activate, self.bus, {"uuid": UUID_A, "ssid": SSID.strip()})

    def test_saved_ethernet_uuid_is_not_activated(self):
        self.profiles([(PROFILE_A, profile(kind="802-3-ethernet"))])
        self.assert_network_error("stale-profile", nm.activate, self.bus, {"uuid": UUID_A, "ssid": SSID})

    def test_saved_missing_uuid_does_not_fall_back_to_same_ssid(self):
        self.profiles([(PROFILE_A, profile())])
        self.assert_network_error("stale-profile", nm.activate, self.bus, {"uuid": UUID_B, "ssid": SSID})

    def test_invalid_saved_uuid_never_queries_profiles(self):
        for profile_uuid in (None, "", "fictional-not-uuid", 42, [], {}):
            with self.subTest(profile_uuid=profile_uuid):
                self.assert_network_error("invalid-input", nm.activate, self.bus, {"uuid": profile_uuid, "ssid": SSID})

    def test_multiple_matching_profiles_refuse_even_with_new_password(self):
        for extra in ({}, {"password": PASSWORD}):
            with self.subTest(extra=extra):
                self.connect_setup([(PROFILE_A, profile()), (PROFILE_B, profile(UUID_B))])
                self.assert_network_error("ambiguous-profile", nm.connect, self.bus, {"ssid": SSID, **extra})

    def test_saved_secure_no_password_activates_without_update_or_secret_query(self):
        self.connect_setup([(PROFILE_A, profile(auto=False))], ap=True)
        self.activate_call(ap=AP_A)
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "bssid": BSSID}), {})

    def test_saved_open_no_password_activates_without_profile_update(self):
        self.connect_setup([(PROFILE_A, profile(security="open", auto=False))])
        self.activate_call()
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "security": "open"}), {})

    def test_new_secure_network_requires_password_without_creating_profile(self):
        self.connect_setup()
        self.assert_network_error("password-required", nm.connect, self.bus, {"ssid": SSID})

    def test_profile_permission_failure_must_not_create_duplicate(self):
        error = SyntheticDBusError("org.freedesktop.NetworkManager.Settings.PermissionDenied")
        self.connect_setup([(PROFILE_A, error)])
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD})
        self.assertEqual(nm.safe_dbus_error(error).code, "permission")

    def test_listing_permission_failure_does_not_create_profile(self):
        self.manager()
        self.devices()
        error = SyntheticDBusError("org.freedesktop.DBus.Error.AccessDenied")
        self.bus.expect(nm.ROOT + "/Settings", nm.SETTINGS, "ListConnections", "()", (), error=error)
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD})

    def test_only_explicitly_disappeared_profiles_are_skipped(self):
        for name in ("org.freedesktop.DBus.Error.UnknownObject",
                     "org.freedesktop.NetworkManager.Settings.UnknownConnection"):
            with self.subTest(name=name):
                expected = profile(UUID_B)
                self.profiles([(PROFILE_A, SyntheticDBusError(name)), (PROFILE_B, expected)])
                self.assertEqual(nm.all_profiles(self.bus), [(PROFILE_B, expected)])

    def test_unknown_profile_read_failure_propagates_without_creating_duplicate(self):
        self.connect_setup([(PROFILE_A, nm.DBusError())])
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD})

    def test_saved_activation_with_radio_off_never_activates_profile(self):
        self.profiles([(PROFILE_A, profile())])
        self.manager(False)
        self.assert_network_error("disabled", nm.activate, self.bus, {"uuid": UUID_A, "ssid": SSID})

    def test_metadata_is_whitelisted_and_never_contains_psk(self):
        self.devices([(ETHERNET, device_details("fixture-ethernet0", 1)),
                      (DEVICE_A, device_details(active=ACTIVE_OTHER))])
        self.props(ACTIVE_OTHER, nm.ACTIVE, {"Uuid": V("s", UUID_A)})
        settings = profile(hidden=True, auto=False)
        settings["802-11-wireless-security"]["psk"] = V("s", PASSWORD)
        settings["connection"]["private-annotation"] = V("s", RAW_DIAGNOSTIC)
        malformed = profile(UUID_B)
        malformed["802-11-wireless"]["ssid"] = V("ay", [255])
        self.profiles([(PROFILE_A, settings), (PROFILE_B, malformed), (PROFILE_NEW, profile(kind="802-3-ethernet"))])
        result = nm.list_details(self.bus)
        self.assertEqual(result, {
            "adapters": [{"device": "fixture-wifi0", "state": 30}],
            "profiles": [{"uuid": UUID_A, "ssid": SSID, "name": "Renamed synthetic profile",
                          "autoconnect": False, "hidden": True, "security": "wpa-psk", "active": True}],
        })
        output = json.dumps(result)
        self.assertNotIn(PASSWORD, output)
        self.assertNotIn(RAW_DIAGNOSTIC, output)
        self.assertNotIn('"psk"', output)


class ConnectionSettingsTests(NativeWifiCase):
    def test_new_hidden_wpa2_uses_typed_settings_private_permissions_and_no_ap(self):
        self.connect_setup()
        expected = new_settings(hidden=True, auto=False)
        self.add_call(expected)
        self.activated()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD, "hidden": True}), {})
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        nm.os.getuid.assert_called_once_with()
        nm.pwd.getpwuid.assert_called_once_with(424242)
        self.assertEqual(expected["802-11-wireless-security"]["psk"].signature, "s")
        for path, interface, method, signature, args in self.bus.calls:
            self.assertNotIn(PASSWORD, path + interface + method + signature)
            if method != "AddAndActivateConnection2":
                self.assertNotIn(PASSWORD, repr(args))

    def test_new_visible_wpa3_selects_ap_and_defaults_autoconnect_true(self):
        self.connect_setup(ap=True)
        self.add_call(new_settings(security="sae", password="x"), ap=AP_A)
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "security": "sae", "password": "x", "bssid": BSSID}), {})

    def test_new_open_profile_has_no_psk_or_security_dictionary(self):
        self.connect_setup()
        self.add_call(new_settings(security="open"))
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "security": "open"}), {})

    def test_explicit_autoconnect_overrides_hidden_or_visible_default(self):
        for hidden, auto in ((True, True), (False, False)):
            with self.subTest(hidden=hidden, auto=auto):
                self.connect_setup()
                self.add_call(new_settings(hidden=hidden, auto=auto))
                self.activated()
                self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD,
                                                       "hidden": hidden, "autoconnect": auto}), {})

    def test_matching_profile_updates_password_and_hidden_without_resetting_autoconnect(self):
        original = profile(auto=True)
        original["ipv4"]["route-metric"] = V("x", 777)
        self.connect_setup([(PROFILE_A, original)])
        expected = deepcopy(original)
        expected["802-11-wireless-security"].update({"psk": V("s", PASSWORD), "psk-flags": V("u", 0)})
        expected["802-11-wireless"]["hidden"] = V("b", True)
        self.update_call(expected)
        self.activate_call()
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD, "hidden": True}), {})
        nm.pwd.getpwuid.assert_not_called()
        nm.uuid.uuid4.assert_not_called()
        self.assertTrue(expected["connection"]["autoconnect"].value)

    def test_matching_profile_preserves_autoconnect_false_when_no_option_given(self):
        original = profile(auto=False)
        self.connect_setup([(PROFILE_A, original)])
        expected = deepcopy(original)
        expected["802-11-wireless-security"]["psk"] = V("s", PASSWORD)
        self.update_call(expected)
        self.activate_call()
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD}), {})

    def test_matching_profile_honors_explicit_autoconnect_only(self):
        original = profile(auto=False)
        self.connect_setup([(PROFILE_A, original)])
        expected = deepcopy(original)
        expected["802-11-wireless-security"]["psk"] = V("s", PASSWORD)
        expected["connection"]["autoconnect"] = V("b", True)
        self.update_call(expected)
        self.activate_call()
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD, "autoconnect": True}), {})

    def test_different_security_does_not_overwrite_existing_profile(self):
        self.connect_setup([(PROFILE_A, profile(security="sae"))])
        self.add_call(new_settings())
        self.activated()
        self.assertEqual(nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD}), {})

    def test_permission_failure_updating_existing_profile_never_creates_fallback(self):
        original = profile()
        self.connect_setup([(PROFILE_A, original)])
        expected = deepcopy(original)
        expected["802-11-wireless-security"]["psk"] = V("s", PASSWORD)
        error = SyntheticDBusError("org.freedesktop.NetworkManager.Settings.PermissionDenied")
        self.update_call(expected, error=error)
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD})
        self.assertEqual(error.stage, "update-profile")
        self.assertEqual(nm.safe_dbus_error(error).code, "permission")

    def test_activation_permission_failure_does_not_create_duplicate(self):
        self.connect_setup([(PROFILE_A, profile())])
        self.activate_call(error=SyntheticDBusError("org.freedesktop.NetworkManager.PermissionDenied"))
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID})

    def test_new_profile_permission_failure_is_not_retried(self):
        self.connect_setup()
        self.add_call(new_settings(), error=SyntheticDBusError("org.freedesktop.DBus.Error.AccessDenied"))
        with self.assertRaises(nm.DBusError):
            nm.connect(self.bus, {"ssid": SSID, "password": PASSWORD})


class ActivationTests(NativeWifiCase):
    def test_activation_success_returns_without_sleep_or_cancellation(self):
        self.activated()
        self.assertEqual(nm.wait_for_activation(self.bus, ACTIVE_A, DEVICE_A), {})
        self.assertEqual(self.clock.sleeps, [])

    def test_transient_activation_polls_only_its_own_object(self):
        self.props(ACTIVE_A, nm.ACTIVE, {"State": V("u", 1)})
        self.activated()
        self.assertEqual(nm.wait_for_activation(self.bus, ACTIVE_A, DEVICE_A), {})
        self.assertEqual(self.clock.sleeps, [0.25])

    def test_device_failures_are_classified_without_blame_or_other_disconnects(self):
        for reason, expected in ((7, "password-required"), (8, "authentication"), (9, "configuration"),
                                 (10, "failed"), (11, "timeout"), (39, "cancelled")):
            with self.subTest(reason=reason):
                self.props(ACTIVE_A, nm.ACTIVE, {"State": V("u", 4)})
                self.props(DEVICE_A, nm.DEVICE, {"StateReason": V("(uu)", (120, reason)), "Diagnostic": V("s", RAW_DIAGNOSTIC)})
                self.assert_network_error(expected, nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A)

    def test_non_authentication_failure_is_not_mislabeled_as_password(self):
        self.props(ACTIVE_A, nm.ACTIVE, {"State": V("u", 4)})
        self.props(DEVICE_A, nm.DEVICE, {"StateReason": V("(uu)", (120, 99))})
        self.assert_network_error("failed", nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A)

    def test_timeout_cancels_only_exact_activation_path(self):
        for _ in range(4):
            self.props(ACTIVE_A, nm.ACTIVE, {"State": V("u", 1)})
        self.bus.expect(nm.ROOT, nm.MANAGER, "DeactivateConnection", "(o)", (ACTIVE_A,))
        self.assert_network_error("timeout", nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A, timeout=1)
        self.assertEqual(self.clock.sleeps, [0.25] * 4)
        self.assertNotIn(ACTIVE_OTHER, repr(self.bus.calls))

    def test_timeout_cancellation_error_still_reports_safe_timeout(self):
        self.bus.expect(nm.ROOT, nm.MANAGER, "DeactivateConnection", "(o)", (ACTIVE_A,),
                        error=SyntheticDBusError("org.freedesktop.DBus.Error.AccessDenied"))
        self.assert_network_error("timeout", nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A, timeout=0)

    def test_removed_activation_recovers_device_reason_for_actual_gdbus_errors(self):
        for name in ("UnknownObject", "UnknownInterface", "UnknownMethod"):
            with self.subTest(name=name):
                self.props(ACTIVE_A, nm.ACTIVE, error=SyntheticDBusError("org.freedesktop.DBus.Error." + name))
                self.props(DEVICE_A, nm.DEVICE, {"State": V("u", 30), "ActiveConnection": V("o", "/"),
                    "StateReason": V("(uu)", (30, 7))})
                self.assert_network_error("password-required", nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A)

    def test_removed_activation_does_not_claim_another_connection_as_success(self):
        self.props(ACTIVE_A, nm.ACTIVE, error=SyntheticDBusError("org.freedesktop.DBus.Error.UnknownMethod"))
        self.props(DEVICE_A, nm.DEVICE, {"State": V("u", 100), "ActiveConnection": V("o", ACTIVE_OTHER)})
        self.assert_network_error("cancelled", nm.wait_for_activation, self.bus, ACTIVE_A, DEVICE_A)

    def test_removed_activation_can_confirm_exact_connected_device(self):
        self.props(ACTIVE_A, nm.ACTIVE, error=SyntheticDBusError("org.freedesktop.DBus.Error.UnknownObject"))
        self.props(DEVICE_A, nm.DEVICE, {"State": V("u", 100), "ActiveConnection": V("o", ACTIVE_A)})
        self.assertEqual(nm.wait_for_activation(self.bus, ACTIVE_A, DEVICE_A), {})

    def test_non_missing_monitor_error_keeps_safe_stage(self):
        error = SyntheticDBusError("org.freedesktop.DBus.Error.AccessDenied")
        self.props(ACTIVE_A, nm.ACTIVE, error=error)
        with self.assertRaises(nm.DBusError):
            nm.wait_for_activation(self.bus, ACTIVE_A, DEVICE_A)
        self.assertEqual(error.stage, "monitor-active")


class SafeErrorTests(NativeWifiCase):
    def test_permission_error_names_map_without_returning_raw_diagnostics(self):
        for name in ("org.freedesktop.NetworkManager.Settings.PermissionDenied",
                     "org.freedesktop.NetworkManager.NotAuthorized", "org.freedesktop.DBus.Error.AccessDenied"):
            with self.subTest(name=name):
                result = nm.safe_dbus_error(SyntheticDBusError(name))
                self.assertEqual(result.code, "permission")
                self.assertNotIn(RAW_DIAGNOSTIC, str(result))
                self.assertNotIn(name, str(result))

    def test_generic_named_error_does_not_return_remote_error_text(self):
        result = nm.safe_dbus_error(SyntheticDBusError("org.freedesktop.DBus.Error.Failed"))
        self.assertEqual(result.code, "failed")
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_adapter_error_without_remote_name_is_safely_mapped(self):
        result = nm.safe_dbus_error(nm.DBusError())
        self.assertEqual(result.code, "failed")
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_foreign_exception_without_name_is_safely_mapped(self):
        result = nm.safe_dbus_error(RuntimeError(RAW_DIAGNOSTIC))
        self.assertEqual(result.code, "failed")
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_profile_update_timeout_is_not_reported_as_wrong_password(self):
        error = nm.DBusError(category="timeout")
        error.stage = "update-profile"
        result = nm.safe_dbus_error(error)
        self.assertEqual(result.code, "timeout")
        self.assertIn("[update-profile/local-timeout]", str(result))
        self.assertIn("authorization may be required", str(result))
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_stage_and_remote_name_are_allowlisted_not_echoed(self):
        error = SyntheticDBusError("org.example." + "SensitiveIdentifier")
        error.stage = RAW_DIAGNOSTIC
        result = nm.safe_dbus_error(error)
        self.assertIn("[request/unknown]", str(result))
        self.assertNotIn("SensitiveIdentifier", str(result))
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_fixed_stage_distinguishes_configuration_from_credentials(self):
        error = nm.DBusError("org.freedesktop.NetworkManager.Settings.InvalidConnection")
        error.stage = "add-and-activate"
        result = nm.safe_dbus_error(error)
        self.assertEqual(result.code, "configuration")
        self.assertIn("[add-and-activate/invalid-settings]", str(result))

    def test_startup_library_failure_is_not_reported_as_a_network_or_password_error(self):
        for stage in ("startup-library-discovery", "startup-library-load", "startup-library-symbols"):
            error = nm.DBusError()
            error.stage = stage
            result = nm.safe_dbus_error(error)
            self.assertEqual(result.code, "runtime-unavailable")
            self.assertIn("No connection was attempted", str(result))
            self.assertIn("[" + stage + "/unknown]", str(result))

    def test_debug_policy_failure_exposes_no_environment_value(self):
        error = nm.DBusError()
        error.stage = "startup-debug-policy"
        result = nm.safe_dbus_error(error)
        self.assertEqual(result.code, "privacy-policy")
        self.assertNotIn(RAW_DIAGNOSTIC, str(result))

    def test_settings_failure_reports_cause_as_possible_not_proven(self):
        error = nm.DBusError("org.freedesktop.NetworkManager.Settings.Failed")
        error.stage = "update-profile"
        result = nm.safe_dbus_error(error)
        self.assertIn("[update-profile/settings-failed]", str(result))
        self.assertIn("may be required", str(result))


if __name__ == "__main__":
    unittest.main()

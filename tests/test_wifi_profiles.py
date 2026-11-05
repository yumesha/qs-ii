"""Safety contracts for Wi-Fi profile actions; every nmcli call is mocked.

Run from the ii directory:
    python3 -B -m unittest discover -s tests -p 'test_wifi_profiles.py' -v
"""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock


HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts/network/wifi-profiles.py"
SPEC = importlib.util.spec_from_file_location("wifi_profiles_under_test", HELPER_PATH)
wifi_profiles = importlib.util.module_from_spec(SPEC)
# Also prohibit processes during import, before individual test guards are active.
with mock.patch("subprocess.Popen", side_effect=AssertionError("Real processes are forbidden in Wi-Fi tests")):
    SPEC.loader.exec_module(wifi_profiles)


UUID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UUID_ETHERNET = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
DEVICE = "wlan0"
SSID = '  Cafe: \\Guest "$(literal);"  '
LIST_QUERY = ["-t", "-f", "UUID,TYPE", "connection", "show"]


def device_query(device=DEVICE):
    return ["-g", "GENERAL.TYPE,GENERAL.CON-UUID", "device", "show", device]


def type_query(profile_uuid):
    return ["-g", "connection.type", "connection", "show", "uuid", profile_uuid]


def ssid_query(profile_uuid):
    return ["--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", profile_uuid]


def delete_command(profile_uuid):
    return ["--wait", "120", "connection", "delete", "uuid", profile_uuid]


def disconnect_command(device=DEVICE):
    return ["--wait", "15", "device", "disconnect", device]


class NoRealProcessesTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        blocker = mock.patch(
            "subprocess.Popen",
            side_effect=AssertionError("Real processes are forbidden in Wi-Fi tests"),
        )
        blocker.start()
        self.addCleanup(blocker.stop)


class RunNmcliTests(NoRealProcessesTestCase):
    def test_strips_exactly_one_trailing_newline_without_trimming_ssid(self):
        cases = [
            (SSID + "\n", SSID),
            (SSID, SSID),
            ("first\nsecond\n\n", "first\nsecond\n"),
            ("  \t\n", "  \t"),
            ("\n", ""),
            ("", ""),
        ]
        for stdout, expected in cases:
            with self.subTest(stdout=stdout):
                result = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
                with mock.patch.object(wifi_profiles.subprocess, "run", return_value=result):
                    self.assertEqual(wifi_profiles.run_nmcli(ssid_query(UUID_A)), expected)

    def test_passes_literal_arguments_without_shell_and_uses_stable_locale(self):
        args = ssid_query(UUID_A)
        original_args = args.copy()
        result = subprocess.CompletedProcess([], 0, stdout=SSID + "\n", stderr="")
        with mock.patch.object(wifi_profiles.subprocess, "run", return_value=result) as run:
            self.assertEqual(wifi_profiles.run_nmcli(args), SSID)
        run.assert_called_once()
        positional, kwargs = run.call_args
        self.assertEqual(positional, (["nmcli", *args],))
        self.assertEqual(args, original_args)
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertGreater(kwargs["timeout"], 0)
        self.assertEqual(kwargs["env"]["LANG"], "C")
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")

    def test_protected_changes_allow_an_admin_prompt_but_reads_stay_bounded(self):
        for args, expected in ((delete_command(UUID_A), 130),
                               (["connection", "modify", "uuid", UUID_A, "connection.autoconnect", "no"], 130),
                               (ssid_query(UUID_A), 25), (disconnect_command(), 25)):
            with self.subTest(operation=args[:4]):
                result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
                with mock.patch.object(wifi_profiles.subprocess, "run", return_value=result) as run:
                    wifi_profiles.run_nmcli(args)
                self.assertEqual(run.call_args.kwargs["timeout"], expected)

    def test_nonzero_exit_raises_nmcli_error_instead_of_returning_stdout(self):
        result = subprocess.CompletedProcess([], 10, stdout="unusable output\n", stderr="lookup failed")
        with mock.patch.object(wifi_profiles.subprocess, "run", return_value=result):
            with self.assertRaises(wifi_profiles.NmcliError):
                wifi_profiles.run_nmcli(type_query(UUID_A))

    def test_permission_failure_is_reported_without_raw_diagnostic(self):
        for stderr in (
            "Not authorized to control networking. diagnostic-token",
            "Permission denied: diagnostic-token",
            "Insufficient privileges: diagnostic-token",
        ):
            with self.subTest(stderr=stderr):
                result = subprocess.CompletedProcess([], 4, stdout="", stderr=stderr)
                with mock.patch.object(wifi_profiles.subprocess, "run", return_value=result):
                    with self.assertRaises(wifi_profiles.NmcliError) as raised:
                        wifi_profiles.run_nmcli(delete_command(UUID_A))
                self.assertIn("permission", str(raised.exception).lower())
                self.assertNotIn("diagnostic-token", str(raised.exception))

    def test_process_unavailability_and_timeout_become_nmcli_errors(self):
        for error in (FileNotFoundError("nmcli"), subprocess.TimeoutExpired("nmcli", 25)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(wifi_profiles.subprocess, "run", side_effect=error):
                    with self.assertRaises(wifi_profiles.NmcliError):
                        wifi_profiles.run_nmcli(LIST_QUERY)


class ProfileActionTestCase(NoRealProcessesTestCase):
    """Strict command allowlist: unexpected queries and writes fail immediately."""

    def setUp(self):
        super().setUp()
        self.responses = {}
        patcher = mock.patch.object(wifi_profiles, "run_nmcli", side_effect=self.fake_nmcli)
        self.nmcli = patcher.start()
        self.addCleanup(patcher.stop)

    def fake_nmcli(self, args):
        key = tuple(args)
        if key not in self.responses:
            raise AssertionError(f"Unconfirmed or unexpected nmcli command: {args!r}")
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response

    def respond(self, command, response=""):
        self.responses[tuple(command)] = response

    def profile(self, profile_uuid=UUID_A, ssid=SSID, connection_type="802-11-wireless"):
        self.respond(type_query(profile_uuid), connection_type)
        self.respond(ssid_query(profile_uuid), ssid)

    def active_device(self, profile_uuid=UUID_A, device_type="wifi", device=DEVICE):
        self.respond(device_query(device), f"{device_type}\n{profile_uuid}")

    def assert_commands(self, *commands):
        self.assertEqual(self.nmcli.call_args_list, [mock.call(command) for command in commands])

    def assert_no_mutation(self):
        for call in self.nmcli.call_args_list:
            args = call.args[0]
            self.assertTrue("show" in args and ("connection" in args or "device" in args), args)
            for forbidden in ("delete", "disconnect", "radio", "networking", "modify", "down", "--show-secrets"):
                self.assertNotIn(forbidden, args)


class DisconnectTests(ProfileActionTestCase):
    def test_only_verified_wifi_device_is_disconnected(self):
        self.active_device()
        self.profile()
        self.respond(disconnect_command())
        self.assertEqual(wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE}), {})
        self.assert_commands(device_query(), type_query(UUID_A), ssid_query(UUID_A), disconnect_command())

    def test_renamed_profile_id_is_irrelevant_to_ssid_and_uuid_selection(self):
        # This connection's display ID may be "Renamed laptop profile". No name
        # query or name-based lookup is allowed by the strict command fixture.
        self.active_device(UUID_B)
        self.profile(UUID_B, "Actual broadcast SSID")
        self.respond(disconnect_command())
        wifi_profiles.disconnect({"ssid": "Actual broadcast SSID", "device": DEVICE})
        self.assert_commands(device_query(), type_query(UUID_B), ssid_query(UUID_B), disconnect_command())

    def test_ethernet_device_is_refused_even_if_uuid_points_to_wireless_profile(self):
        self.active_device(device_type="ethernet", device="enp1s0")
        self.profile()
        with self.assertRaises(wifi_profiles.WifiError):
            wifi_profiles.disconnect({"ssid": SSID, "device": "enp1s0"})
        self.assert_commands(device_query("enp1s0"))
        self.assert_no_mutation()

    def test_ethernet_profile_on_reported_wifi_device_is_refused(self):
        self.active_device(UUID_ETHERNET)
        self.profile(UUID_ETHERNET, connection_type="802-3-ethernet")
        with self.assertRaises(wifi_profiles.WifiError):
            wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE})
        self.assert_commands(device_query(), type_query(UUID_ETHERNET))
        self.assert_no_mutation()

    def test_absent_or_noncanonical_active_uuid_is_refused(self):
        for active_uuid in ("", "--", "not-a-uuid", UUID_A.replace("-", ""), " " + UUID_A):
            with self.subTest(active_uuid=active_uuid):
                self.nmcli.reset_mock()
                self.active_device(active_uuid)
                with self.assertRaises(wifi_profiles.WifiError):
                    wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE})
                self.assert_commands(device_query())
                self.assert_no_mutation()

    def test_stale_active_uuid_lookup_failure_never_disconnects(self):
        self.active_device()
        self.respond(type_query(UUID_A), wifi_profiles.NmcliError("Profile disappeared"))
        with self.assertRaises(wifi_profiles.NmcliError):
            wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE})
        self.assert_commands(device_query(), type_query(UUID_A))
        self.assert_no_mutation()

    def test_ssid_mismatch_including_whitespace_is_refused(self):
        for requested_ssid in ("Different network", SSID.strip(), SSID + " ", SSID.lower()):
            with self.subTest(ssid=requested_ssid):
                self.nmcli.reset_mock()
                self.active_device()
                self.profile()
                with self.assertRaises(wifi_profiles.WifiError):
                    wifi_profiles.disconnect({"ssid": requested_ssid, "device": DEVICE})
                self.assert_commands(device_query(), type_query(UUID_A), ssid_query(UUID_A))
                self.assert_no_mutation()

    def test_malformed_device_metadata_is_refused(self):
        for metadata in ("wifi", "wifi\n" + UUID_A + "\nextra", "wifi-p2p\n" + UUID_A):
            with self.subTest(metadata=metadata):
                self.nmcli.reset_mock()
                self.respond(device_query(), metadata)
                with self.assertRaises(wifi_profiles.WifiError):
                    wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE})
                self.assert_commands(device_query())
                self.assert_no_mutation()

    def test_invalid_device_names_are_rejected_before_querying_nmcli(self):
        for device in (None, "", "--help", "wlan0;echo", "wlan 0", "wlan0\n", "w" * 65, 1):
            with self.subTest(device=device):
                with self.assertRaises(wifi_profiles.WifiError):
                    wifi_profiles.disconnect({"ssid": SSID, "device": device})
                self.nmcli.assert_not_called()

    def test_disconnect_permission_failure_propagates_without_fallback(self):
        self.active_device()
        self.profile()
        self.respond(disconnect_command(), wifi_profiles.NmcliError("Permission denied"))
        with self.assertRaises(wifi_profiles.NmcliError):
            wifi_profiles.disconnect({"ssid": SSID, "device": DEVICE})
        self.assert_commands(device_query(), type_query(UUID_A), ssid_query(UUID_A), disconnect_command())


class ForgetTests(ProfileActionTestCase):
    def test_prevalidates_every_selected_profile_before_any_deletion(self):
        for profile_uuid in (UUID_A, UUID_B):
            self.profile(profile_uuid)
            self.respond(delete_command(profile_uuid))
        payload = {"ssid": SSID, "uuids": [UUID_A, UUID_B]}
        self.assertEqual(wifi_profiles.forget(payload), {"deleted": [UUID_A, UUID_B]})
        self.assert_commands(
            type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_B), ssid_query(UUID_B),
            delete_command(UUID_A), delete_command(UUID_B),
        )
        self.assertEqual(payload, {"ssid": SSID, "uuids": [UUID_A, UUID_B]})

    def test_later_ethernet_profile_prevents_deleting_earlier_valid_profile(self):
        self.profile(UUID_A)
        self.profile(UUID_ETHERNET, connection_type="802-3-ethernet")
        with self.assertRaises(wifi_profiles.WifiError):
            wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_A, UUID_ETHERNET]})
        self.assert_commands(type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_ETHERNET))
        self.assert_no_mutation()

    def test_later_ssid_mismatch_prevents_all_deletions(self):
        self.profile(UUID_A)
        self.profile(UUID_B, SSID.strip())
        with self.assertRaises(wifi_profiles.WifiError):
            wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_A, UUID_B]})
        self.assert_commands(type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_B), ssid_query(UUID_B))
        self.assert_no_mutation()

    def test_later_stale_profile_prevents_all_deletions(self):
        self.profile(UUID_A)
        self.respond(type_query(UUID_B), wifi_profiles.NmcliError("Profile disappeared"))
        with self.assertRaises(wifi_profiles.NmcliError):
            wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_A, UUID_B]})
        self.assert_commands(type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_B))
        self.assert_no_mutation()

    def test_only_explicit_uuid_is_deleted_and_new_matching_profile_is_not_discovered(self):
        # A and C have the same SSID, but only B was confirmed by the user.
        for profile_uuid in (UUID_A, UUID_B, UUID_C):
            self.profile(profile_uuid)
            self.respond(delete_command(profile_uuid))
        self.respond(LIST_QUERY, "\n".join(f"{value}:802-11-wireless" for value in (UUID_A, UUID_B, UUID_C)))
        result = wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_B]})
        self.assertEqual(result, {"deleted": [UUID_B]})
        self.assert_commands(type_query(UUID_B), ssid_query(UUID_B), delete_command(UUID_B))

    def test_invalid_empty_or_oversized_uuid_lists_are_rejected_before_queries(self):
        too_many = [f"{number:08x}-0000-4000-8000-000000000000" for number in range(33)]
        invalid_lists = [
            None, [], UUID_A, (UUID_A,), {}, [None], [1], [""], ["not-a-uuid"],
            [UUID_A.replace("-", "")], ["{" + UUID_A + "}"], [" " + UUID_A],
            [UUID_A + "\n"], [UUID_A, "bad-later-entry"], too_many,
        ]
        for uuids in invalid_lists:
            with self.subTest(uuids=uuids):
                with self.assertRaises(wifi_profiles.WifiError):
                    wifi_profiles.forget({"ssid": SSID, "uuids": uuids})
                self.nmcli.assert_not_called()
        with self.assertRaises(wifi_profiles.WifiError):
            wifi_profiles.forget({"ssid": SSID})
        self.nmcli.assert_not_called()

    def test_maximum_32_selected_profiles_are_supported(self):
        uuids = [f"{number:08x}-0000-4000-8000-000000000000" for number in range(32)]
        queries = []
        for profile_uuid in uuids:
            self.profile(profile_uuid)
            self.respond(delete_command(profile_uuid))
            queries.extend([type_query(profile_uuid), ssid_query(profile_uuid)])
        self.assertEqual(wifi_profiles.forget({"ssid": SSID, "uuids": uuids}), {"deleted": uuids})
        self.assert_commands(*queries, *(delete_command(value) for value in uuids))

    def test_duplicate_uuids_are_normalized_and_processed_once_in_selection_order(self):
        for profile_uuid in (UUID_A, UUID_B):
            self.profile(profile_uuid)
            self.respond(delete_command(profile_uuid))
        result = wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_B.upper(), UUID_A, UUID_B, UUID_A]})
        self.assertEqual(result, {"deleted": [UUID_B, UUID_A]})
        self.assert_commands(
            type_query(UUID_B), ssid_query(UUID_B), type_query(UUID_A), ssid_query(UUID_A),
            delete_command(UUID_B), delete_command(UUID_A),
        )

    def test_partial_permission_failure_reports_deleted_ids_and_stops(self):
        for profile_uuid in (UUID_A, UUID_B, UUID_C):
            self.profile(profile_uuid)
            self.respond(delete_command(profile_uuid))
        self.respond(delete_command(UUID_B), wifi_profiles.NmcliError("Permission denied"))
        result = wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_A, UUID_B, UUID_C]})
        self.assertEqual(set(result), {"deleted", "error"})
        self.assertEqual(result["deleted"], [UUID_A])
        self.assertIsInstance(result["error"], str)
        self.assertIn("permission", result["error"].lower())
        self.assert_commands(
            type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_B), ssid_query(UUID_B),
            type_query(UUID_C), ssid_query(UUID_C), delete_command(UUID_A), delete_command(UUID_B),
        )

    def test_first_delete_failure_reports_empty_deleted_list_and_stops(self):
        self.profile(UUID_A)
        self.profile(UUID_B)
        self.respond(delete_command(UUID_A), wifi_profiles.NmcliError("Permission denied"))
        result = wifi_profiles.forget({"ssid": SSID, "uuids": [UUID_A, UUID_B]})
        self.assertEqual(result["deleted"], [])
        self.assertIn("permission", result["error"].lower())
        self.assert_commands(
            type_query(UUID_A), ssid_query(UUID_A), type_query(UUID_B), ssid_query(UUID_B), delete_command(UUID_A),
        )

    def test_invalid_ssid_is_rejected_by_both_actions_before_queries(self):
        for ssid in (None, "", 42, [], "x" * 257):
            for action, extra in (
                (wifi_profiles.forget, {"uuids": [UUID_A]}),
                (wifi_profiles.disconnect, {"device": DEVICE}),
            ):
                with self.subTest(action=action.__name__, ssid=ssid):
                    with self.assertRaises(wifi_profiles.WifiError):
                        action({"ssid": ssid, **extra})
                    self.nmcli.assert_not_called()


class ListProfilesTests(ProfileActionTestCase):
    def test_filters_nonwireless_profiles_and_preserves_exact_ssids(self):
        self.respond(LIST_QUERY, "\n".join([
            f"{UUID_ETHERNET}:802-3-ethernet",
            f"{UUID_A}:802-11-wireless",
            f"{UUID_C}:vpn",
            f"{UUID_B}:802-11-wireless",
            "malformed-row",
            "",
        ]))
        self.profile(UUID_A)
        second_ssid = "Network\nwith embedded newline\n"
        self.profile(UUID_B, second_ssid)
        self.assertEqual(wifi_profiles.list_profiles(), [
            {"uuid": UUID_A, "ssid": SSID},
            {"uuid": UUID_B, "ssid": second_ssid},
        ])
        self.assert_commands(LIST_QUERY, ssid_query(UUID_A), ssid_query(UUID_B))
        self.assert_no_mutation()

    def test_ethernet_only_and_empty_lists_do_not_query_ssids(self):
        for listing in ("", f"{UUID_ETHERNET}:802-3-ethernet"):
            with self.subTest(listing=listing):
                self.nmcli.reset_mock()
                self.respond(LIST_QUERY, listing)
                self.assertEqual(wifi_profiles.list_profiles(), [])
                self.assert_commands(LIST_QUERY)
                self.assert_no_mutation()

    def test_profile_disappearing_during_listing_is_skipped(self):
        self.respond(LIST_QUERY, f"{UUID_A}:802-11-wireless\n{UUID_B}:802-11-wireless")
        self.respond(ssid_query(UUID_A), wifi_profiles.NmcliError("Profile disappeared"))
        self.profile(UUID_B)
        self.assertEqual(wifi_profiles.list_profiles(), [{"uuid": UUID_B, "ssid": SSID}])
        self.assert_commands(LIST_QUERY, ssid_query(UUID_A), ssid_query(UUID_B))
        self.assert_no_mutation()

    def test_listing_failure_is_not_reported_as_empty_success(self):
        self.respond(LIST_QUERY, wifi_profiles.NmcliError("NetworkManager unavailable"))
        with self.assertRaises(wifi_profiles.NmcliError):
            wifi_profiles.list_profiles()
        self.assert_commands(LIST_QUERY)
        self.assert_no_mutation()


if __name__ == "__main__":
    unittest.main()

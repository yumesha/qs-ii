"""GIO ABI/codec tests using only synthetic data and mocked bus connections.

Run: python3 -B -m unittest discover -s tests -p 'test_gio_dbus.py' -v
No test connects to a bus, inspects a real profile, or changes network state.
"""

import ctypes as C
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/network/gio_dbus.py"
SPEC = importlib.util.spec_from_file_location("gio_dbus_under_test", MODULE_PATH)
dbus = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dbus
SPEC.loader.exec_module(dbus)
Variant = dbus.Variant


class NativeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Lookup/loading is intentionally done before blocking process creation:
        # ctypes.util.find_library may consult ldconfig, never with user values.
        cls.native = dbus._native()
        cls.codec = dbus._VariantCodec(cls.native)

    def setUp(self):
        super().setUp()
        for target in ("subprocess.Popen", "os.system", "os.popen", "builtins.open"):
            blocker = mock.patch(target, side_effect=AssertionError("External transport is forbidden"))
            blocker.start()
            self.addCleanup(blocker.stop)
        # An accidental real bus connection is also forbidden in every test.
        bus_blocker = mock.patch.object(
            self.native.gio, "g_bus_get_sync", side_effect=AssertionError("Real bus access is forbidden")
        )
        bus_blocker.start()
        self.addCleanup(bus_blocker.stop)

    def roundtrip(self, signature, value):
        pointer = self.codec.encode(signature, value)
        try:
            return self.codec.decode(pointer)
        finally:
            self.native.glib.g_variant_unref(pointer)

    def assert_safe(self, function, *args, **kwargs):
        with self.assertRaises(dbus.DBusError) as raised:
            function(*args, **kwargs)
        error = raised.exception
        self.assertEqual(str(error), "D-Bus operation failed.")
        self.assertEqual(error.args, ("D-Bus operation failed.",))
        self.assertEqual(repr(error), "DBusError('D-Bus operation failed.')")
        return error


class CodecTests(NativeTestCase):
    def test_scalar_roundtrips_and_integer_boundaries(self):
        for signature, (_, _, low, high) in dbus._INTEGER_TYPES.items():
            for value in (low, high, 0):
                with self.subTest(signature=signature, boundary=value):
                    result = self.roundtrip(signature, value)
                    self.assertEqual(result, value)
                    self.assertIs(type(result), int)
        for signature, value in (
            ("s", 'Synthetic \"quotes\" \\ backslash\nUnicode 雪'),
            ("s", ""), ("o", "/"), ("o", "/org/example/device_1"),
            ("g", ""), ("g", "sa{sv}(ut)"),
            ("b", True), ("b", False), ("d", -1.25),
            ("d", float("inf")), ("d", float("-inf")),
        ):
            with self.subTest(signature=signature):
                result = self.roundtrip(signature, value)
                self.assertEqual(result, value)
                self.assertIs(type(result), type(value))
        self.assertTrue(math.isnan(self.roundtrip("d", float("nan"))))
        self.assertIs(type(self.roundtrip("d", 1)), float)

    def test_integer_overflow_and_bool_coercion_are_rejected(self):
        for signature, (_, _, low, high) in dbus._INTEGER_TYPES.items():
            for value in (low - 1, high + 1, True, False, 1.0, "1", None):
                with self.subTest(signature=signature, input_type=type(value).__name__):
                    self.assert_safe(self.codec.encode, signature, value)

    def test_arrays_dictionaries_and_structures(self):
        for signature, value in (
            ("as", ["one", "two"]), ("ai", [-1, 0, 1]),
            ("aau", [[0, 2 ** 32 - 1], []]),
            ("a{is}", {-1: "negative", 1: "positive"}),
            ("a{bs}", {True: "yes", False: "no"}),
            ("a{os}", {"/test": "path"}),
            ("((sb)au)", (("nested", True), [1, 2])),
            ("av", [Variant("q", 65535), Variant("n", -32768)]),
        ):
            with self.subTest(signature=signature):
                self.assertEqual(self.roundtrip(signature, value), value)
        self.assertEqual(self.roundtrip("ay", bytes([0, 127, 255])), [0, 127, 255])
        self.assertEqual(self.roundtrip("ay", bytearray([1, 255])), [1, 255])
        self.assertEqual(self.roundtrip("as", ("one", "two")), ["one", "two"])

    def test_empty_containers_keep_their_type(self):
        for signature, value in (
            ("()", ()), ("ay", []), ("a{sv}", {}),
            ("a{sa{sv}}", {}), ("aa{sv}", []), ("a(ut)", []),
        ):
            with self.subTest(signature=signature):
                self.assertEqual(self.roundtrip(signature, value), value)
                self.assertEqual(self.roundtrip("v", Variant(signature, value)), Variant(signature, value))

    def test_variant_wrappers_preserve_every_width_and_nested_variant(self):
        for signature, value in (
            ("y", 1), ("n", -1), ("q", 1), ("i", -1), ("u", 1),
            ("x", -1), ("t", 1), ("b", True), ("d", 1.0),
            ("s", "text"), ("o", "/test"), ("g", "u"),
            ("a{sv}", {"entry": Variant("u", 7)}),
            ("v", Variant("v", Variant("q", 7))),
        ):
            with self.subTest(signature=signature):
                wrapped = Variant(signature, value)
                self.assertEqual(self.roundtrip("v", wrapped), wrapped)

    def test_representative_networkmanager_settings_roundtrip_and_update(self):
        # All IDs, SSIDs and credential-like values below are invented fixtures.
        settings = {
            "connection": {
                "id": Variant("s", "Synthetic in-memory test network"),
                "uuid": Variant("s", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                "type": Variant("s", "802-11-wireless"),
                "autoconnect": Variant("b", False),
                "autoconnect-priority": Variant("i", -5),
                "permissions": Variant("as", ["user:synthetic:"]),
                "timestamp": Variant("t", (1 << 64) - 1),
            },
            "802-11-wireless": {
                "ssid": Variant("ay", list(b"Synthetic test SSID")),
                "mode": Variant("s", "infrastructure"),
                "mtu": Variant("u", 1500),
                "seen-bssids": Variant("as", []),
            },
            "802-11-wireless-security": {
                "key-mgmt": Variant("s", "wpa-psk"),
                "psk": Variant("s", "SYNTHETIC_NOT_A_REAL_PASSWORD"),
                "psk-flags": Variant("u", 2),
            },
            "ipv4": {
                "method": Variant("s", "auto"),
                "dns": Variant("au", [0x0100007F]),
                "addresses": Variant("aau", [[0x0100007F, 8, 0]]),
                "route-data": Variant("aa{sv}", [
                    {"dest": Variant("s", "192.0.2.0"), "prefix": Variant("u", 24)},
                ]),
            },
            "ipv6": {
                "method": Variant("s", "auto"),
                "dns": Variant("aay", [[0] * 15 + [1]]),
                "address-data": Variant("aa{sv}", []),
            },
        }
        signature = "(a{sa{sv}}ooa{sv})"
        arguments = (settings, "/org/example/device_1", "/", {"persist": Variant("s", "memory")})
        decoded = self.roundtrip(signature, arguments)
        self.assertEqual(decoded, arguments)
        decoded[0]["802-11-wireless"]["mtu"].value = 1400
        self.assertEqual(self.roundtrip(signature, decoded), decoded)
        self.assertEqual(decoded[0]["802-11-wireless"]["mtu"].signature, "u")
        self.assertEqual(decoded[0]["connection"]["timestamp"].signature, "t")

    def test_invalid_signatures_never_reach_native_constructors(self):
        invalid = (
            None, b"s", "", "ss", "(s", "s)", "a", "a{}", "a{s}", "a{sss}",
            "a{vs}", "a{(s)s}", "{ss}", "({ss})", "a{ass}",
            "m", "ms", "h", "*", "?", "r", "s\0", "雪", "a" * 256 + "s",
            "(" * 66 + "s" + ")" * 66,
        )
        with mock.patch.object(self.codec, "_build") as build:
            for signature in invalid:
                with self.subTest(input_type=type(signature).__name__):
                    self.assert_safe(self.codec.encode, signature, None)
            build.assert_not_called()
        for signature in ("s", "a{sv}", "v"):
            self.assert_safe(self.codec.encode, signature, (), require_tuple=True)

    def test_invalid_values_are_safe(self):
        for signature, value in (
            ("s", None), ("s", b"bytes"), ("s", "synthetic\0marker"), ("s", "\ud800"),
            ("o", "relative/path"), ("o", "/has-dash"), ("g", "("), ("g", "*"), ("g", "s" * 256),
            ("b", 1), ("b", "true"), ("d", True), ("d", "1"), ("d", 10 ** 1000),
            ("as", "string"), ("au", bytes([1])), ("a{sv}", []),
            ("a{sv}", {"key": 3}), ("ay", [-1]), ("ay", [256]),
            ("(ss)", ("one",)), ("(s)", ["list"]), ("()", (1,)),
            ("v", 5), ("v", Variant("invalid", "synthetic marker")),
            ("a{uv}", {True: Variant("s", "fixture")}),
        ):
            with self.subTest(signature=signature, input_type=type(value).__name__):
                self.assert_safe(self.codec.encode, signature, value)

    def test_recursive_variants_are_bounded_without_recursionerror(self):
        cycle = Variant("v", None)
        cycle.value = cycle
        self.assert_safe(self.codec.encode, "v", cycle)
        nested = Variant("s", "fixture")
        for _ in range(70):
            nested = Variant("v", nested)
        self.assert_safe(self.codec.encode, "v", nested)

    def test_error_and_wrapper_reprs_do_not_display_values(self):
        marker = "SYNTHETIC_PRIVATE_VALUE"
        wrapped = Variant("s", marker)
        self.assertNotIn(marker, repr(wrapped))
        for name in (None, marker, "org.example.SyntheticFailure", marker + "\n", object()):
            error = dbus.DBusError(name)
            self.assertNotIn(marker, str(error))
            self.assertNotIn(marker, repr(error))
        self.assertEqual(dbus.DBusError("org.example.Failure").name, "org.example.Failure")
        self.assertIsNone(dbus.DBusError(marker).name)

    def test_local_error_categories_are_allowlisted_and_never_change_exception_text(self):
        self.assertIsNone(dbus.DBusError().category)
        for category in ("timeout", "cancelled", "permission", "transport"):
            error = dbus.DBusError(category=category)
            self.assertEqual(error.category, category)
            self.assertIsNone(error.name)
            self.assertEqual(str(error), "D-Bus operation failed.")
            self.assertEqual(repr(error), "DBusError('D-Bus operation failed.')")
            self.assertEqual(error.args, ("D-Bus operation failed.",))
        for category in (None, "SYNTHETIC_PRIVATE_VALUE", "timeout\n", "TIMEOUT", b"timeout", 24,
                         [], {}, object()):
            error = dbus.DBusError(category=category)
            self.assertIsNone(error.category)
            self.assertNotIn("PRIVATE", repr(error))
            self.assertNotIn("PRIVATE", repr(vars(error)))


class OwnershipTests(NativeTestCase):
    def test_encode_returns_nonfloating_full_reference(self):
        floating = self.native.glib.g_variant_is_floating
        floating.argtypes = [C.c_void_p]
        floating.restype = C.c_int
        for signature, value in (("s", "fixture"), ("a{sv}", {"key": Variant("u", 1)})):
            pointer = self.codec.encode(signature, value)
            try:
                self.assertFalse(floating(pointer))
                self.assertEqual(self.codec.decode(pointer), value)
                self.assertEqual(self.codec.decode(pointer), value)
            finally:
                self.native.glib.g_variant_unref(pointer)

    def test_partial_build_releases_already_created_children(self):
        glib = self.native.glib
        with mock.patch.object(glib, "g_variant_new_string", wraps=glib.g_variant_new_string) as create:
            with mock.patch.object(glib, "g_variant_unref", wraps=glib.g_variant_unref) as release:
                self.assert_safe(self.codec.encode, "(su)", ("fixture", -1))
                create.assert_called_once()
                release.assert_called_once()

    def test_container_takes_its_own_child_references(self):
        glib = self.native.glib
        with mock.patch.object(glib, "g_variant_unref", wraps=glib.g_variant_unref) as release:
            pointer = self.codec.encode("(su)", ("fixture", 42))
            try:
                self.assertEqual(release.call_count, 2)
                self.assertEqual(self.codec.decode(pointer), ("fixture", 42))
                self.assertEqual(release.call_count, 4)
            finally:
                glib.g_variant_unref(pointer)
            self.assertEqual(release.call_count, 5)

    def test_empty_array_frees_allocated_type(self):
        glib = self.native.glib
        with mock.patch.object(glib, "g_variant_type_free", wraps=glib.g_variant_type_free) as release:
            self.assertEqual(self.roundtrip("a{sv}", {}), {})
            release.assert_called_once()

    def test_decode_failure_releases_borrowed_children(self):
        glib = self.native.glib
        pointer = self.codec.encode("(su)", ("fixture", 1))
        try:
            with mock.patch.object(self.codec, "_signature", side_effect=["(su)", "s", "h"]):
                with mock.patch.object(glib, "g_variant_unref", wraps=glib.g_variant_unref) as release:
                    self.assert_safe(self.codec.decode, pointer)
                    self.assertEqual(release.call_count, 2)
        finally:
            glib.g_variant_unref(pointer)

    def test_real_gerror_retains_name_but_discards_message_and_frees_both(self):
        gio, glib = self.native.gio, self.native.glib
        create = gio.g_dbus_error_new_for_dbus_error
        create.argtypes = [C.c_char_p, C.c_char_p]
        create.restype = C.c_void_p
        pointer = create(b"org.example.SyntheticFailure", b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
        with mock.patch.object(glib, "g_error_free", wraps=glib.g_error_free) as free_error:
            with mock.patch.object(glib, "g_free", wraps=glib.g_free) as free_name:
                error = self.native.take_error(pointer)
                self.assertEqual(error.name, "org.example.SyntheticFailure")
                self.assertIsNone(error.category)
                self.assertEqual(str(error), "D-Bus operation failed.")
                self.assertNotIn("PRIVATE", repr(error))
                free_error.assert_called_once_with(pointer)
                free_name.assert_called_once()

    def test_local_gerror_without_remote_name_is_freed(self):
        glib = self.native.glib
        quark = glib.g_quark_from_string
        quark.argtypes = [C.c_char_p]
        quark.restype = C.c_uint32
        create = glib.g_error_new_literal
        create.argtypes = [C.c_uint32, C.c_int, C.c_char_p]
        create.restype = C.c_void_p
        pointer = create(quark(b"gio-dbus-synthetic-test-domain"), 1, b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
        with mock.patch.object(glib, "g_error_free", wraps=glib.g_error_free) as release:
            error = self.native.take_error(pointer)
            self.assertIsNone(error.name)
            self.assertIsNone(error.category)
            self.assertEqual(str(error), "D-Bus operation failed.")
            release.assert_called_once_with(pointer)

    def test_local_gerror_categories_use_only_known_domain_and_code(self):
        gio, glib = self.native.gio, self.native.glib
        create = glib.g_error_new_literal
        create.argtypes = [C.c_uint32, C.c_int, C.c_char_p]
        create.restype = C.c_void_p
        quark = glib.g_quark_from_string
        quark.argtypes = [C.c_char_p]
        quark.restype = C.c_uint32
        io_domain = gio.g_io_error_quark()
        other_domain = quark(b"gio-dbus-synthetic-unrelated-domain")
        # Expected constants are independent of the adapter's mapping.
        cases = [(io_domain, code, category) for code, category in (
            (14, "permission"), (18, "transport"), (19, "cancelled"), (24, "timeout"),
            (28, "transport"), (37, "transport"), (38, "transport"), (39, "transport"),
            (44, "transport"), (45, "transport"),
            (0, None), (13, None), (36, None), (9999, None), (-1, None),
        )]
        cases.extend((other_domain, code, None) for code in (14, 18, 19, 24, 45))
        for domain, code, expected in cases:
            with self.subTest(code=code, expected=expected, local=domain == io_domain):
                pointer = create(domain, code, b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
                with mock.patch.object(C, "string_at", side_effect=AssertionError("Text read forbidden")):
                    with mock.patch.object(glib, "g_error_free", wraps=glib.g_error_free) as free_error:
                        error = self.native.take_error(pointer)
                        free_error.assert_called_once_with(pointer)
                self.assertEqual(error.category, expected)
                self.assertIsNone(error.name)
                self.assertEqual(str(error), "D-Bus operation failed.")
                self.assertEqual(repr(error), "DBusError('D-Bus operation failed.')")
                self.assertNotIn("PRIVATE", repr(vars(error)))

    def test_remote_error_never_becomes_a_local_category(self):
        gio, glib = self.native.gio, self.native.glib
        create = glib.g_error_new_literal
        create.argtypes = [C.c_uint32, C.c_int, C.c_char_p]
        create.restype = C.c_void_p
        # Remote names are encoded by GIO in the message. Retain the existing
        # remote-name helper, but never classify such an error as a local timeout.
        pointer = create(gio.g_io_error_quark(), 24,
                         b"GDBus.Error:org.example.RemoteFailure: SYNTHETIC_PRIVATE_DIAGNOSTIC")
        error = self.native.take_error(pointer)
        self.assertEqual(error.name, "org.example.RemoteFailure")
        self.assertIsNone(error.category)
        self.assertNotIn("PRIVATE", repr(vars(error)))

    def test_null_gerror_has_no_name_or_category(self):
        error = self.native.take_error(None)
        self.assertIsNone(error.name)
        self.assertIsNone(error.category)


class BusTests(NativeTestCase):
    def setUp(self):
        super().setUp()
        self.gio = SimpleNamespace(
            g_bus_get_sync=mock.Mock(return_value=0x1234),
            g_object_unref=mock.Mock(),
            g_dbus_is_name=self.native.gio.g_dbus_is_name,
            g_dbus_is_interface_name=self.native.gio.g_dbus_is_interface_name,
            g_dbus_is_member_name=self.native.gio.g_dbus_is_member_name,
            g_dbus_connection_call_sync=mock.Mock(side_effect=self.reply),
        )
        fake = SimpleNamespace(gio=self.gio, glib=self.native.glib, take_error=self.native.take_error)
        patcher = mock.patch.object(dbus, "_native", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reply_signature = "(v)"
        self.reply_value = (Variant("s", "synthetic-version"),)

    def reply(self, *args):
        self.sent_arguments = self.codec.decode(args[5])
        return self.codec.encode(self.reply_signature, self.reply_value)

    def invoke(self, bus, **overrides):
        arguments = dict(
            path="/org/freedesktop/NetworkManager", interface="org.freedesktop.DBus.Properties",
            method="Get", signature="(ss)", arguments=("org.freedesktop.NetworkManager", "Version"),
        )
        arguments.update(overrides)
        return bus.call(**arguments)

    def test_call_passes_fixed_destination_tuple_and_default_timeout(self):
        with dbus.SystemBus() as bus:
            self.assertEqual(self.invoke(bus), self.reply_value)
            self.assertEqual(self.sent_arguments, ("org.freedesktop.NetworkManager", "Version"))
        self.gio.g_bus_get_sync.assert_called_once()
        self.assertEqual(self.gio.g_bus_get_sync.call_args.args[:2], (1, None))
        self.gio.g_dbus_connection_call_sync.assert_called_once()
        args = self.gio.g_dbus_connection_call_sync.call_args.args
        self.assertEqual(args[:5], (
            0x1234, b"org.freedesktop.NetworkManager", b"/org/freedesktop/NetworkManager",
            b"org.freedesktop.DBus.Properties", b"Get",
        ))
        self.assertEqual(args[6:10], (None, 0, 10000, None))
        self.gio.g_object_unref.assert_called_once_with(0x1234)

    def test_no_argument_call_and_optional_destination(self):
        self.reply_signature, self.reply_value = "(ao)", (["/org/example/device_1"],)
        with dbus.SystemBus(destination="org.example.Test") as bus:
            self.assertEqual(self.invoke(bus, signature="()", arguments=(), timeout_ms=500), self.reply_value)
            self.assertEqual(self.sent_arguments, ())
        args = self.gio.g_dbus_connection_call_sync.call_args.args
        self.assertEqual(args[1], b"org.example.Test")
        self.assertEqual(args[8], 500)

    def test_invalid_call_metadata_is_rejected_before_bus_call(self):
        with dbus.SystemBus() as bus:
            for override in (
                {"path": "not/a/path"}, {"path": "/synthetic\0marker"},
                {"interface": "invalid"}, {"interface": "org.example.\ud800"},
                {"method": "two.words"}, {"method": ""},
                {"timeout_ms": 0}, {"timeout_ms": -1}, {"timeout_ms": 2 ** 31},
                {"timeout_ms": True}, {"timeout_ms": 1.5},
                {"signature": "ss"}, {"signature": "s"}, {"arguments": ["a", "b"]},
                {"arguments": ("a",)},
            ):
                self.assert_safe(self.invoke, bus, **override)
            self.gio.g_dbus_connection_call_sync.assert_not_called()

    def test_invalid_destination_does_not_connect(self):
        for value in ("invalid", "org.example\0marker", None):
            self.assert_safe(dbus.SystemBus, value)
        self.gio.g_bus_get_sync.assert_not_called()

    def test_gio_debug_tracing_is_refused_before_connection_and_call(self):
        with mock.patch.dict(dbus.os.environ, {"G_DBUS_DEBUG": "message"}):
            self.assert_safe(dbus.SystemBus)
        self.gio.g_bus_get_sync.assert_not_called()
        with dbus.SystemBus() as bus:
            with mock.patch.dict(dbus.os.environ, {"G_DBUS_DEBUG": "all"}):
                self.assert_safe(self.invoke, bus)
        self.gio.g_dbus_connection_call_sync.assert_not_called()

    def test_close_is_idempotent_and_closed_bus_cannot_be_used(self):
        bus = dbus.SystemBus()
        bus.close()
        bus.close()
        bus.__del__()
        self.gio.g_object_unref.assert_called_once_with(0x1234)
        self.assert_safe(self.invoke, bus)
        self.assert_safe(bus.__enter__)
        self.gio.g_dbus_connection_call_sync.assert_not_called()

    def test_context_exit_releases_connection_on_error(self):
        with self.assertRaises(RuntimeError):
            with dbus.SystemBus():
                raise RuntimeError("Synthetic test failure")
        self.gio.g_object_unref.assert_called_once_with(0x1234)

    def test_null_connection_is_a_safe_failure(self):
        self.gio.g_bus_get_sync.return_value = None
        self.assert_safe(dbus.SystemBus)
        self.gio.g_object_unref.assert_not_called()

    def test_null_reply_is_safe_and_parameters_are_released(self):
        self.gio.g_dbus_connection_call_sync.side_effect = None
        self.gio.g_dbus_connection_call_sync.return_value = None
        glib = self.native.glib
        with dbus.SystemBus() as bus:
            with mock.patch.object(glib, "g_variant_unref", wraps=glib.g_variant_unref) as release:
                self.assert_safe(self.invoke, bus)
                # Two encoded strings plus the owned argument tuple.
                self.assertEqual(release.call_count, 3)

    def test_decode_failure_releases_reply_and_parameters(self):
        self.reply_signature, self.reply_value = "u", 1
        glib = self.native.glib
        with dbus.SystemBus() as bus:
            with mock.patch.object(glib, "g_variant_unref", wraps=glib.g_variant_unref) as release:
                self.assert_safe(self.invoke, bus)
                # Argument children + fake bus decode children + reply + parameters.
                self.assertEqual(release.call_count, 6)

    def test_remote_failure_has_safe_name_and_releases_gerror(self):
        gio, glib = self.native.gio, self.native.glib
        create = gio.g_dbus_error_new_for_dbus_error
        create.argtypes = [C.c_char_p, C.c_char_p]
        create.restype = C.c_void_p

        def fail(*args):
            pointer = create(b"org.example.NotAuthorized", b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
            C.cast(args[-1], C.POINTER(C.c_void_p))[0] = pointer
            return None

        self.gio.g_dbus_connection_call_sync.side_effect = fail
        with dbus.SystemBus() as bus:
            with mock.patch.object(glib, "g_error_free", wraps=glib.g_error_free) as release:
                error = self.assert_safe(self.invoke, bus)
                self.assertEqual(error.name, "org.example.NotAuthorized")
                release.assert_called_once()

    def test_local_call_timeout_preserves_category_without_message(self):
        glib = self.native.glib
        create = glib.g_error_new_literal
        create.argtypes = [C.c_uint32, C.c_int, C.c_char_p]
        create.restype = C.c_void_p

        def fail(*args):
            pointer = create(self.native.gio.g_io_error_quark(), 24, b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
            C.cast(args[-1], C.POINTER(C.c_void_p))[0] = pointer
            return None

        self.gio.g_dbus_connection_call_sync.side_effect = fail
        with dbus.SystemBus() as bus:
            error = self.assert_safe(self.invoke, bus)
            self.assertIsNone(error.name)
            self.assertEqual(error.category, "timeout")
            self.assertNotIn("PRIVATE", repr(vars(error)))

    def test_local_connection_permission_failure_preserves_category(self):
        glib = self.native.glib
        create = glib.g_error_new_literal
        create.argtypes = [C.c_uint32, C.c_int, C.c_char_p]
        create.restype = C.c_void_p

        def fail(_bus_type, _cancellable, error_out):
            pointer = create(self.native.gio.g_io_error_quark(), 14, b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
            C.cast(error_out, C.POINTER(C.c_void_p))[0] = pointer
            return None

        self.gio.g_bus_get_sync.side_effect = fail
        error = self.assert_safe(dbus.SystemBus)
        self.assertIsNone(error.name)
        self.assertEqual(error.category, "permission")
        self.assertNotIn("PRIVATE", repr(vars(error)))

    def test_connection_failure_consumes_gerror(self):
        gio, glib = self.native.gio, self.native.glib
        create = gio.g_dbus_error_new_for_dbus_error
        create.argtypes = [C.c_char_p, C.c_char_p]
        create.restype = C.c_void_p

        def fail(_bus_type, _cancellable, error_out):
            pointer = create(b"org.example.Unavailable", b"SYNTHETIC_PRIVATE_DIAGNOSTIC")
            C.cast(error_out, C.POINTER(C.c_void_p))[0] = pointer
            return None

        self.gio.g_bus_get_sync.side_effect = fail
        with mock.patch.object(glib, "g_error_free", wraps=glib.g_error_free) as release:
            error = self.assert_safe(dbus.SystemBus)
            self.assertEqual(error.name, "org.example.Unavailable")
            release.assert_called_once()
        self.gio.g_object_unref.assert_not_called()


class LibraryTests(unittest.TestCase):
    def test_debug_tracing_is_refused_before_native_library_lookup(self):
        with mock.patch.dict(dbus.os.environ, {"G_DBUS_DEBUG": "message"}):
            with mock.patch.object(dbus, "find_library") as lookup:
                with self.assertRaises(dbus.DBusError):
                    dbus._Native()
                lookup.assert_not_called()

    def test_missing_libraries_and_load_errors_are_safe(self):
        for available in (None, "synthetic-library"):
            with mock.patch.object(dbus, "find_library", return_value=available), \
                 mock.patch.object(dbus.shutil, "which", return_value=None), \
                 mock.patch.object(dbus.C, "CDLL", side_effect=OSError("SYNTHETIC_PRIVATE_DIAGNOSTIC")):
                with self.assertRaises(dbus.DBusError) as raised:
                    dbus._Native()
                self.assertEqual(str(raised.exception), "D-Bus operation failed.")
                self.assertEqual(raised.exception.stage, "startup-library-load")
                self.assertNotIn("PRIVATE", repr(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)

    def test_runtime_sonames_work_without_compiler_based_discovery(self):
        gio, glib = object(), object()
        with mock.patch.object(dbus, "find_library", return_value=None), \
             mock.patch.object(dbus.C, "CDLL", side_effect=[gio, glib]) as load, \
             mock.patch.object(dbus._Native, "_bind_all") as bind:
            native = dbus._Native()
        self.assertIs(native.gio, gio)
        self.assertIs(native.glib, glib)
        self.assertEqual(load.call_args_list, [mock.call("libgio-2.0.so.0"), mock.call("libglib-2.0.so.0")])
        bind.assert_called_once()

    def test_lookup_failure_still_tries_runtime_loader(self):
        with mock.patch.object(dbus, "find_library", side_effect=OSError("SYNTHETIC_PRIVATE_DIAGNOSTIC")), \
             mock.patch.object(dbus.C, "CDLL", side_effect=[object(), object()]) as load, \
             mock.patch.object(dbus._Native, "_bind_all"):
            dbus._Native()
        self.assertEqual(load.call_args_list, [mock.call("libgio-2.0.so.0"), mock.call("libglib-2.0.so.0")])

    def test_nix_gui_loader_uses_nmcli_package_runtime_without_hardcoded_paths(self):
        anchor = "/synthetic/store/networkmanager/lib/libnm.so.0"
        anchor_handle, gio, glib = object(), object(), object()
        with mock.patch.object(dbus, "find_library", return_value=None), \
             mock.patch.object(dbus.shutil, "which", return_value="/synthetic/profile/bin/nmcli") as which, \
             mock.patch.object(dbus.os.path, "realpath", return_value="/synthetic/store/networkmanager/bin/nmcli"), \
             mock.patch.object(dbus.os.path, "isfile", side_effect=lambda path: path == anchor), \
             mock.patch.object(dbus.C, "CDLL", side_effect=[OSError("not on runtime search path"), anchor_handle, gio, glib]) as load, \
             mock.patch.object(dbus._Native, "_bind_all"):
            native = dbus._Native()
        which.assert_called_once_with("nmcli")
        self.assertIs(native._runtime_anchor, anchor_handle)
        self.assertIs(native.gio, gio)
        self.assertIs(native.glib, glib)
        self.assertEqual(load.call_args_list, [mock.call("libgio-2.0.so.0"), mock.call(anchor),
                                             mock.call("libgio-2.0.so.0"), mock.call("libglib-2.0.so.0")])

    def test_missing_runtime_anchor_keeps_safe_startup_stage(self):
        with mock.patch.object(dbus, "find_library", return_value=None), \
             mock.patch.object(dbus.shutil, "which", return_value="/synthetic/bin/nmcli"), \
             mock.patch.object(dbus.os.path, "realpath", return_value="/synthetic/bin/nmcli"), \
             mock.patch.object(dbus.os.path, "isfile", return_value=False), \
             mock.patch.object(dbus.C, "CDLL", side_effect=OSError("SYNTHETIC_PRIVATE_DIAGNOSTIC")):
            with self.assertRaises(dbus.DBusError) as raised:
                dbus._Native()
        self.assertEqual(raised.exception.stage, "startup-library-load")
        self.assertNotIn("PRIVATE", repr(vars(raised.exception)))

    def test_ctypes_signatures_are_explicit_and_abi_sized(self):
        native = dbus._native()
        self.assertEqual(native.gio.g_dbus_connection_call_sync.restype, C.c_void_p)
        self.assertEqual(native.gio.g_dbus_connection_call_sync.argtypes, [
            C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
            C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.POINTER(C.c_void_p),
        ])
        self.assertEqual(native.glib.g_variant_n_children.restype, C.c_size_t)
        self.assertEqual(native.glib.g_variant_get_string.restype, C.c_void_p)
        self.assertEqual(native.gio.g_dbus_error_get_remote_error.restype, C.c_void_p)
        self.assertEqual(native.gio.g_io_error_quark.restype, C.c_uint32)
        self.assertEqual(native.gio.g_io_error_quark.argtypes, [])
        self.assertEqual(dbus._GErrorHeader._fields_, [("domain", C.c_uint32), ("code", C.c_int)])
        self.assertEqual(dbus._GErrorHeader.domain.offset, 0)
        self.assertEqual(dbus._GErrorHeader.code.offset, C.sizeof(C.c_uint32))
        self.assertFalse(hasattr(dbus._GErrorHeader, "message"))
        self.assertIsNone(native.glib.g_variant_unref.restype)
        self.assertIsNone(native.gio.g_object_unref.restype)
        for suffix, c_type, _, _ in dbus._INTEGER_TYPES.values():
            self.assertEqual(getattr(native.glib, "g_variant_new_" + suffix).argtypes, [c_type])
            self.assertEqual(getattr(native.glib, "g_variant_get_" + suffix).restype, c_type)


if __name__ == "__main__":
    unittest.main()

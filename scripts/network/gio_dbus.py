"""Small synchronous, in-process GIO adapter for NetworkManager's system bus.

Only Python's standard library and the installed GIO/GLib shared libraries are
needed. Values go directly to typed GVariant constructors, never through text
parsing, subprocess arguments, environment variables, or temporary files.

SystemBus.call takes a complete tuple signature (including its parentheses) and
a tuple of arguments. Arrays decode to lists, dictionaries to dicts, structures
to tuples, and every ``v`` to Variant(inner_signature, decoded_inner_value).
Retain those Variant wrappers when modifying and resending GetSettings results:
Python integers alone do not preserve D-Bus integer widths. Byte arrays accept
bytes/bytearray as well as lists/tuples on input, and decode to lists of integers.

Errors deliberately discard diagnostic text. Calls fail closed when G_DBUS_DEBUG
is enabled, since GIO can otherwise dump message bodies. Use this in a dedicated
helper process, not a process that previously initialized GIO with debug tracing.
This is not secure/zeroizing memory: Python and GLib may retain copies until their
allocations are released.
"""

import ctypes as C
from ctypes.util import find_library
from dataclasses import dataclass, field
from functools import lru_cache
import os
import re
import shutil
from threading import RLock
from typing import Any

__all__ = ["Variant", "DBusError", "SystemBus"]


@dataclass
class Variant:
    signature: str
    # Avoid accidentally displaying settings values in a wrapper's repr.
    value: Any = field(repr=False)


_ERROR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_LOCAL_ERROR_CATEGORIES = frozenset(("timeout", "cancelled", "permission", "transport"))
# Stable GIOErrorEnum values from gio/gioenums.h; unknown codes stay unclassified.
_G_IO_ERROR_CATEGORIES = {
    14: "permission",  # G_IO_ERROR_PERMISSION_DENIED
    18: "transport",   # G_IO_ERROR_CLOSED
    19: "cancelled",   # G_IO_ERROR_CANCELLED
    24: "timeout",     # G_IO_ERROR_TIMED_OUT
    28: "transport",   # G_IO_ERROR_HOST_NOT_FOUND
    37: "transport",   # G_IO_ERROR_HOST_UNREACHABLE
    38: "transport",   # G_IO_ERROR_NETWORK_UNREACHABLE
    39: "transport",   # G_IO_ERROR_CONNECTION_REFUSED
    44: "transport",   # G_IO_ERROR_BROKEN_PIPE / G_IO_ERROR_CONNECTION_CLOSED
    45: "transport",   # G_IO_ERROR_NOT_CONNECTED
}


class _GErrorHeader(C.Structure):
    # GError starts with GQuark (guint32), then gint. Deliberately omit the
    # following message pointer so this view cannot expose diagnostic text.
    _fields_ = [("domain", C.c_uint32), ("code", C.c_int)]


class DBusError(Exception):
    """Safe error with an optional remote name and allowlisted local category.

    category is None, "timeout", "cancelled", "permission", or "transport".
    Native remote errors retain their name and leave category as None.
    """

    def __init__(self, name: str | None = None, *, category: str | None = None):
        super().__init__("D-Bus operation failed.")
        self.name = (
            name if type(name) is str and len(name) <= 255
            and _ERROR_NAME.fullmatch(name) else None
        )
        self.category = (
            category if type(category) is str and category in _LOCAL_ERROR_CATEGORIES else None
        )

    def __str__(self):
        return "D-Bus operation failed."


def _startup_error(stage, error=None):
    error = error if error is not None else DBusError()
    error.stage = stage
    return error


def _check_debug():
    # Reject rather than change global environment or risk a GIO body dump.
    if os.environ.get("G_DBUS_DEBUG"):
        raise _startup_error("startup-debug-policy")


_SCALARS = frozenset("sogbynqiuxtd")
_INTEGER_TYPES = {
    "y": ("byte", C.c_uint8, 0, (1 << 8) - 1),
    "n": ("int16", C.c_int16, -(1 << 15), (1 << 15) - 1),
    "q": ("uint16", C.c_uint16, 0, (1 << 16) - 1),
    "i": ("int32", C.c_int32, -(1 << 31), (1 << 31) - 1),
    "u": ("uint32", C.c_uint32, 0, (1 << 32) - 1),
    "x": ("int64", C.c_int64, -(1 << 63), (1 << 63) - 1),
    "t": ("uint64", C.c_uint64, 0, (1 << 64) - 1),
}
_MAX_DEPTH = 64


@dataclass(frozen=True)
class _Type:
    signature: str
    kind: str
    children: tuple = ()


def _parse_signature(signature, require_tuple=False):
    """Validate our definite D-Bus/GVariant subset before calling any C API."""
    if type(signature) is not str or not 1 <= len(signature) <= 255:
        raise DBusError()

    def parse(index, depth, allow_entry=False):
        if index >= len(signature) or depth > _MAX_DEPTH:
            raise DBusError()
        start = index
        kind = signature[index]
        index += 1
        children = []
        if kind in _SCALARS or kind == "v":
            pass
        elif kind == "a":
            child, index = parse(index, depth + 1, True)
            children.append(child)
        elif kind == "(":
            while index < len(signature) and signature[index] != ")":
                child, index = parse(index, depth + 1)
                children.append(child)
            if index >= len(signature):
                raise DBusError()
            index += 1
        elif kind == "{" and allow_entry:
            key, index = parse(index, depth + 1)
            if key.kind not in _SCALARS:
                raise DBusError()
            value, index = parse(index, depth + 1)
            if index >= len(signature) or signature[index] != "}":
                raise DBusError()
            index += 1
            children = [key, value]
        else:
            raise DBusError()
        return _Type(signature[start:index], kind, tuple(children)), index

    result, end = parse(0, 0)
    if end != len(signature) or (require_tuple and result.kind != "("):
        raise DBusError()
    return result


class _Native:
    """All ABI declarations live here; no varargs GLib APIs are used."""

    def __init__(self):
        _check_debug()
        # find_library may require compiler/linker utilities absent from a GUI
        # launcher's PATH. The runtime loader can still resolve standard sonames.
        try:
            gio_path = find_library("gio-2.0") or "libgio-2.0.so.0"
            glib_path = find_library("glib-2.0") or "libglib-2.0.so.0"
        except (OSError, AttributeError, TypeError, ValueError):
            gio_path, glib_path = "libgio-2.0.so.0", "libglib-2.0.so.0"
        try:
            self.gio = C.CDLL(gio_path)
            self.glib = C.CDLL(glib_path)
        except (OSError, AttributeError, TypeError, ValueError):
            self._load_networkmanager_runtime()
        try:
            self._bind_all()
        except (OSError, AttributeError, TypeError, ValueError):
            raise _startup_error("startup-library-symbols") from None

    def _load_networkmanager_runtime(self):
        # On Nix, the GUI may have no library search path or development tools.
        # nmcli's own package contains libnm with the correct dependency RUNPATH.
        # Loading that installed library first makes its GIO/GLib dependencies
        # available by soname. Derive the location; never embed a store/home path,
        # change the environment, execute a shell, or inspect another process.
        executable = shutil.which("nmcli")
        if executable:
            prefix = os.path.dirname(os.path.dirname(os.path.realpath(executable)))
            for directory in ("lib", "lib64"):
                anchor = os.path.join(prefix, directory, "libnm.so.0")
                if not os.path.isfile(anchor):
                    continue
                try:
                    self._runtime_anchor = C.CDLL(anchor)
                    self.gio = C.CDLL("libgio-2.0.so.0")
                    self.glib = C.CDLL("libglib-2.0.so.0")
                    return
                except (OSError, AttributeError, TypeError, ValueError):
                    continue
        raise _startup_error("startup-library-load") from None

    @staticmethod
    def _bind(library, name, restype, *argtypes):
        function = getattr(library, name)
        function.argtypes = list(argtypes)
        function.restype = restype

    def _bind_all(self):
        ptr = C.c_void_p
        text = C.c_char_p
        size = C.c_size_t
        ptr_out = C.POINTER(ptr)
        bind = self._bind
        gio, glib = self.gio, self.glib
        bind(gio, "g_bus_get_sync", ptr, C.c_int, ptr, ptr_out)
        bind(gio, "g_dbus_connection_call_sync", ptr,
             ptr, text, text, text, text, ptr, ptr, C.c_int, C.c_int, ptr, ptr_out)
        # GIO links GObject; dlsym on its handle resolves this dependency symbol.
        bind(gio, "g_object_unref", None, ptr)
        bind(gio, "g_dbus_error_get_remote_error", ptr, ptr)
        bind(gio, "g_io_error_quark", C.c_uint32)
        for name in ("g_dbus_is_name", "g_dbus_is_interface_name", "g_dbus_is_member_name"):
            bind(gio, name, C.c_int, text)
        bind(glib, "g_error_free", None, ptr)
        bind(glib, "g_free", None, ptr)
        bind(glib, "g_variant_ref_sink", ptr, ptr)
        bind(glib, "g_variant_unref", None, ptr)
        bind(glib, "g_variant_type_new", ptr, text)
        bind(glib, "g_variant_type_free", None, ptr)
        bind(glib, "g_variant_get_type_string", text, ptr)
        bind(glib, "g_variant_n_children", size, ptr)
        bind(glib, "g_variant_get_child_value", ptr, ptr, size)
        bind(glib, "g_variant_get_variant", ptr, ptr)
        bind(glib, "g_variant_new_variant", ptr, ptr)
        bind(glib, "g_variant_new_array", ptr, ptr, ptr_out, size)
        bind(glib, "g_variant_new_tuple", ptr, ptr_out, size)
        bind(glib, "g_variant_new_dict_entry", ptr, ptr, ptr)
        bind(glib, "g_variant_new_boolean", ptr, C.c_int)
        bind(glib, "g_variant_get_boolean", C.c_int, ptr)
        bind(glib, "g_variant_new_double", ptr, C.c_double)
        bind(glib, "g_variant_get_double", C.c_double, ptr)
        for suffix, c_type, _, _ in _INTEGER_TYPES.values():
            bind(glib, "g_variant_new_" + suffix, ptr, c_type)
            bind(glib, "g_variant_get_" + suffix, c_type, ptr)
        for suffix in ("string", "object_path", "signature"):
            bind(glib, "g_variant_new_" + suffix, ptr, text)
        bind(glib, "g_variant_get_string", ptr, ptr, C.POINTER(size))
        bind(glib, "g_variant_is_object_path", C.c_int, text)
        bind(glib, "g_variant_is_signature", C.c_int, text)

    def take_error(self, error):
        """Consume GError without even reading its potentially sensitive message."""
        if not error:
            return DBusError()
        name_pointer = None
        name = None
        category = None
        try:
            name_pointer = self.gio.g_dbus_error_get_remote_error(error)
            if name_pointer:
                try:
                    name = C.string_at(name_pointer).decode("ascii")
                except UnicodeError:
                    pass
            else:
                header = C.cast(error, C.POINTER(_GErrorHeader)).contents
                if header.domain == self.gio.g_io_error_quark():
                    category = _G_IO_ERROR_CATEGORIES.get(header.code)
        finally:
            if name_pointer:
                self.glib.g_free(name_pointer)
            self.glib.g_error_free(error)
        return DBusError(name, category=category)


@lru_cache(maxsize=1)
def _native():
    return _Native()


def _utf8(value):
    if type(value) is not str or "\0" in value:
        raise DBusError()
    try:
        return value.encode("utf-8")
    except UnicodeError:
        raise DBusError() from None


class _VariantCodec:
    """Internal codec. encode returns one full reference, owned by its caller."""

    def __init__(self, native=None):
        self.native = native if native is not None else _native()
        self.glib = self.native.glib

    def encode(self, signature, value, require_tuple=False):
        return self._build(_parse_signature(signature, require_tuple), value, 0)

    def _own(self, pointer):
        if not pointer:
            raise DBusError()
        return self.glib.g_variant_ref_sink(pointer)

    def _build(self, node, value, depth):
        if depth > _MAX_DEPTH:
            raise DBusError()
        kind = node.kind
        glib = self.glib
        if kind in _INTEGER_TYPES:
            suffix, _, lower, upper = _INTEGER_TYPES[kind]
            if type(value) is not int or not lower <= value <= upper:
                raise DBusError()
            return self._own(getattr(glib, "g_variant_new_" + suffix)(value))
        if kind == "b":
            if type(value) is not bool:
                raise DBusError()
            return self._own(glib.g_variant_new_boolean(value))
        if kind == "d":
            if type(value) not in (float, int):
                raise DBusError()
            try:
                number = float(value)
            except (ValueError, OverflowError):
                raise DBusError() from None
            return self._own(glib.g_variant_new_double(number))
        if kind in ("s", "o", "g"):
            encoded = _utf8(value)
            if kind == "o" and not glib.g_variant_is_object_path(encoded):
                raise DBusError()
            if kind == "g" and (len(encoded) > 255 or not glib.g_variant_is_signature(encoded)):
                raise DBusError()
            suffix = {"s": "string", "o": "object_path", "g": "signature"}[kind]
            return self._own(getattr(glib, "g_variant_new_" + suffix)(encoded))

        # Every child is a full (non-floating) reference. A new parent refs each
        # child independently, so finally must release ours even on success.
        children = []
        child_type = None
        try:
            if kind == "v":
                if type(value) is not Variant:
                    raise DBusError()
                child = _parse_signature(value.signature)
                children.append(self._build(child, value.value, depth + 1))
                return self._own(glib.g_variant_new_variant(children[0]))
            if kind == "a":
                child = node.children[0]
                if child.kind == "{":
                    if type(value) is not dict:
                        raise DBusError()
                    values = value.items()
                else:
                    allowed = (list, tuple, bytes, bytearray) if child.kind == "y" else (list, tuple)
                    if type(value) not in allowed:
                        raise DBusError()
                    values = value
                for item in values:
                    children.append(self._build(child, item, depth + 1))
                child_type = glib.g_variant_type_new(child.signature.encode("ascii"))
                if not child_type:
                    raise DBusError()
                pointers = (C.c_void_p * len(children))(*children)
                return self._own(glib.g_variant_new_array(child_type, pointers, len(children)))
            if kind in ("(", "{"):
                if type(value) is not tuple or len(value) != len(node.children):
                    raise DBusError()
                for child, item in zip(node.children, value):
                    children.append(self._build(child, item, depth + 1))
                if kind == "{":
                    return self._own(glib.g_variant_new_dict_entry(*children))
                pointers = (C.c_void_p * len(children))(*children)
                return self._own(glib.g_variant_new_tuple(pointers, len(children)))
            raise DBusError()
        finally:
            if child_type:
                glib.g_variant_type_free(child_type)
            for child_pointer in children:
                glib.g_variant_unref(child_pointer)

    def _signature(self, pointer):
        if not pointer:
            raise DBusError()
        try:
            return self.glib.g_variant_get_type_string(pointer).decode("ascii")
        except (AttributeError, UnicodeError):
            raise DBusError() from None

    def decode(self, pointer, depth=0):
        """Decode a borrowed reference; never transfer it into Python values."""
        if depth > _MAX_DEPTH:
            raise DBusError()
        signature = self._signature(pointer)
        kind = signature[0]
        glib = self.glib
        if kind in _INTEGER_TYPES:
            return getattr(glib, "g_variant_get_" + _INTEGER_TYPES[kind][0])(pointer)
        if kind == "b":
            return bool(glib.g_variant_get_boolean(pointer))
        if kind == "d":
            return glib.g_variant_get_double(pointer)
        if kind in ("s", "o", "g"):
            length = C.c_size_t()
            text = glib.g_variant_get_string(pointer, C.byref(length))
            try:
                return C.string_at(text, length.value).decode("utf-8")
            except UnicodeError:
                raise DBusError() from None
        if kind == "v":
            child = glib.g_variant_get_variant(pointer)
            try:
                return Variant(self._signature(child), self.decode(child, depth + 1))
            finally:
                if child:
                    glib.g_variant_unref(child)
        if kind not in ("a", "(", "{"):
            raise DBusError()
        values = []
        for index in range(glib.g_variant_n_children(pointer)):
            child = glib.g_variant_get_child_value(pointer, index)
            try:
                values.append(self.decode(child, depth + 1))
            finally:
                if child:
                    glib.g_variant_unref(child)
        if kind == "a":
            return dict(values) if signature.startswith("a{") else values
        return tuple(values)


class SystemBus:
    """Synchronous NetworkManager calls; close releases our shared bus reference.

    The optional destination override is for tests/other explicitly chosen bus
    services. This adapter does not authorize operations: callers must implement
    their own action allowlist and must not log settings or credential values.
    """

    def __init__(self, destination="org.freedesktop.NetworkManager"):
        self._lock = RLock()
        self._connection = None
        _check_debug()
        self._native = _native()
        self._destination = _utf8(destination)
        if not self._native.gio.g_dbus_is_name(self._destination):
            raise DBusError()
        error = C.c_void_p()
        connection = self._native.gio.g_bus_get_sync(1, None, C.byref(error))
        if error.value:
            if connection:
                self._native.gio.g_object_unref(connection)
            raise _startup_error("startup-system-bus", self._native.take_error(error.value))
        if not connection:
            raise _startup_error("startup-system-bus")
        self._connection = connection

    def call(self, path, interface, method, signature, arguments, timeout_ms=10000) -> tuple:
        """Call one method with a complete tuple signature and tuple arguments."""
        with self._lock:
            _check_debug()
            if not self._connection:
                raise DBusError()
            if type(timeout_ms) is not int or not 1 <= timeout_ms <= (1 << 31) - 1:
                raise DBusError()
            path_bytes, interface_bytes, method_bytes = map(_utf8, (path, interface, method))
            gio, glib = self._native.gio, self._native.glib
            if not (
                glib.g_variant_is_object_path(path_bytes)
                and gio.g_dbus_is_interface_name(interface_bytes)
                and gio.g_dbus_is_member_name(method_bytes)
            ):
                raise DBusError()
            codec = _VariantCodec(self._native)
            parameters = codec.encode(signature, arguments, require_tuple=True)
            reply = None
            error = C.c_void_p()
            try:
                reply = gio.g_dbus_connection_call_sync(
                    self._connection, self._destination, path_bytes,
                    interface_bytes, method_bytes, parameters, None, 0,
                    timeout_ms, None, C.byref(error),
                )
                if error.value:
                    error_pointer = error.value
                    error.value = None
                    raise self._native.take_error(error_pointer)
                if not reply:
                    raise DBusError()
                result = codec.decode(reply)
                if type(result) is not tuple:
                    raise DBusError()
                return result
            finally:
                if error.value:
                    glib.g_error_free(error.value)
                if reply:
                    glib.g_variant_unref(reply)
                glib.g_variant_unref(parameters)

    def close(self):
        """Idempotently unref; never close the process-wide shared connection."""
        with self._lock:
            if self._connection:
                connection, self._connection = self._connection, None
                self._native.gio.g_object_unref(connection)

    def __enter__(self):
        if not self._connection:
            raise DBusError()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        # Also tolerate an exception partway through initialization or shutdown.
        try:
            self.close()
        except Exception:
            pass

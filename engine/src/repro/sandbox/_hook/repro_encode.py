"""Values to stable digests, for Repro's tracer (E01, E02; ADR-0005, ARCHITECTURE §4.3).

A value becomes a tagged byte string, CBOR-like, hashed with BLAKE2b-128. The same value gives
the same bytes in every process, whatever the hash seed and the Python version (3.12 to 3.15):
sets are written in the order of their elements' own encodings, floats as ``float.hex()`` (one
form each for NaN, the infinities and -0.0), integers in hexadecimal (no digit limit applies).

**No user code runs.** A value is read only through the interpreter's own C-level parts, taken
directly from ``type``, ``object`` and ``BaseException``, never looked up on the value or its
class (where a metaclass or a ``__getattribute__`` could answer instead):
- the exact builtin types are walked: ``None``, ``bool``, ``int``, ``float``, ``complex``,
  ``str``, ``bytes``, ``bytearray``, ``list``, ``tuple``, ``dict``, ``set``, ``frozenset``;
- exact standard-library value types already imported by the target have adapters running
  only standard-library code: ``datetime``, ``date``, ``time``, ``timedelta``, ``Decimal``,
  ``Fraction``, ``UUID``, pure and concrete paths, ``re.Pattern``; an enum member is its name;
- an exception is its type, its ``args``, and the types along its ``__cause__`` /
  ``__context__`` chain;
- any other object is its type's name and its state: the instance dictionary and the
  ``__slots__`` values, through the interpreter's own descriptors. A class that puts a
  descriptor of its own in their place is opaque instead;
- functions, classes, modules, generators, coroutines, code and frames: a token naming what
  they are, never called or consumed.

**Normalised.** Strings have the snapshot's root, the temporary directory and the home
directory replaced by ``<ROOT>``, ``<TMP>`` and ``<HOME>`` (and then ``\\`` made ``/``), and
hexadecimal addresses (``0x`` and six or more hex digits) by ``<ADDR>``: base and head run from
different directories, and default ``repr`` strings embed addresses.

**Two digests, one walk.** Every dictionary is written with its entries sorted by their
encodings, and its insertion order is kept apart, as the positions its entries came in. The
order-insensitive digest hashes the sorted bytes; the digest hashes them with the orders: two
values that differ only in the order of some dictionary have the same first and different
second digests, so a difference in order alone can be told apart.

**Guards.** Deeper than ``MAX_DEPTH``, past ``MAX_NODES`` values or ``MAX_SECONDS``, or back at a
container or object already on the path (a cycle), the walk writes a tag and the encoding is
*incomplete*: the engine never takes two incomplete encodings as equal. Nothing raises into the
target.

The standard library only: this runs in the target's interpreter.
"""

import os
import re
import sys
import time
import types
from collections.abc import Callable, Iterator
from hashlib import blake2b
from typing import Any

MAX_DEPTH = 6
MAX_NODES = 5000
MAX_SECONDS = 0.05
_CHECK_EVERY = 256
_SEQUENCES: dict[type, bytes] = {list: b"L", tuple: b"U"}
_SETS: dict[type, bytes] = {set: b"E", frozenset: b"Z"}
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")
_GETSET = types.GetSetDescriptorType
_MEMBER = types.MemberDescriptorType
_OPAQUE: dict[type, bytes] = {
    types.FunctionType: b"fn",
    types.BuiltinFunctionType: b"builtin",
    types.MethodType: b"method",
    types.ModuleType: b"module",
    types.GeneratorType: b"generator",
    types.CoroutineType: b"coroutine",
    types.AsyncGeneratorType: b"asyncgen",
    types.CodeType: b"code",
    types.FrameType: b"frame",
    types.TracebackType: b"traceback",
}
# The interpreter's own descriptors, taken once from the builtin types themselves.
_TYPE_MRO = type.__dict__["__mro__"]
_TYPE_DICT = type.__dict__["__dict__"]
_TYPE_QUALNAME = type.__dict__["__qualname__"]
_TYPE_MODULE = type.__dict__["__module__"]
_EXCEPTION_ARGS = BaseException.__dict__["args"]
_EXCEPTION_CAUSE = BaseException.__dict__["__cause__"]
_EXCEPTION_CONTEXT = BaseException.__dict__["__context__"]
_FUNCTION_QUALNAME = types.FunctionType.__dict__["__qualname__"]
_ABSENT = object()


def type_name(kind: type) -> str:
    """``module.qualname`` of a type, through ``type``'s own descriptors."""
    try:
        module = _TYPE_MODULE.__get__(kind)
        qualname = _TYPE_QUALNAME.__get__(kind)
    except Exception:  # noqa: BLE001 - a hostile type: still a name, never an error
        return "<unnamed type>"
    return f"{module}.{qualname}" if type(module) is str and type(qualname) is str else "?"


class Normaliser:
    """What is replaced in every string: directories (the longest first), then addresses."""

    def __init__(self, directories: dict[str, str] | None = None) -> None:
        pairs: set[tuple[str, str]] = set()
        for token, path in (directories or {}).items():
            if len(path) > 1:
                for form in (path, path.replace("\\", "/"), path.replace("/", "\\")):
                    pairs.add((form.rstrip("/\\"), token))
        self.pairs = sorted(pairs, key=lambda pair: (-len(pair[0]), pair))
        self.shortest = min((len(path) for path, _ in self.pairs), default=0)

    def text(self, value: str) -> str:
        replaced = False
        if self.pairs and len(value) >= self.shortest:
            for path, token in self.pairs:
                if path and path in value:
                    value = value.replace(path, token)
                    replaced = True
        if replaced:
            value = value.replace("\\", "/")
        if "0x" in value or "0X" in value:
            value = _ADDRESS.sub("<ADDR>", value)
        return value


def default_normaliser() -> Normaliser:
    """Directories from the sandbox's environment: the snapshot, the temporary directory, home."""
    environ = os.environ
    return Normaliser(
        {
            "<ROOT>": environ.get("REPRO_ROOT", ""),
            "<TMP>": environ.get("TMPDIR") or environ.get("TEMP") or "",
            "<HOME>": environ.get("HOME") or environ.get("USERPROFILE") or "",
        }
    )


_ADAPTERS: dict[str, Any] = {"modules": -1, "table": {}}


def _adapters() -> dict[type, Callable[[Any], str]]:
    """The adapter table, rebuilt only when the target has imported more modules."""
    if _ADAPTERS["modules"] != len(sys.modules):
        _ADAPTERS["table"] = _build_adapters()
        _ADAPTERS["modules"] = len(sys.modules)
    table: dict[type, Callable[[Any], str]] = _ADAPTERS["table"]
    return table


def _build_adapters() -> dict[type, Callable[[Any], str]]:
    """Exact standard-library types, from modules the target already imported (none is imported
    here), with the text that stands for a value of each."""
    found: dict[type, Callable[[Any], str]] = {}
    modules = sys.modules
    datetime = modules.get("datetime")
    if datetime is not None:
        for kind in (datetime.datetime, datetime.date, datetime.time):
            found[kind] = kind.isoformat
        found[datetime.timedelta] = lambda v: f"{v.days},{v.seconds},{v.microseconds}"
    decimal = modules.get("decimal")
    if decimal is not None:
        found[decimal.Decimal] = str
    fractions = modules.get("fractions")
    if fractions is not None:
        found[fractions.Fraction] = lambda v: f"{v.numerator}/{v.denominator}"
    uuid = modules.get("uuid")
    if uuid is not None:
        found[uuid.UUID] = lambda v: f"{v.int:032x}"
    pathlib = modules.get("pathlib")
    if pathlib is not None:
        names = ("PurePath", "PurePosixPath", "PureWindowsPath", "Path", "PosixPath", "WindowsPath")
        for name in names:
            kind = getattr(pathlib, name, None)
            if type(kind) is type:
                found[kind] = lambda v: _normaliser().text(str(v)).replace("\\", "/")
    found[re.Pattern] = lambda v: f"{v.flags}:{v.pattern!r}"
    return found


class _Walk:
    __slots__ = (
        "adapters", "complete", "deadline", "nodes", "normalise", "orders", "path", "shortest",
    )  # fmt: skip

    def __init__(self) -> None:
        self.nodes = 0
        self.complete = True
        self.orders = bytearray()  # each dictionary's insertion order, as sorted positions
        normaliser = _normaliser()
        self.normalise = normaliser.text
        # Strings shorter than every directory replaced cannot hold one.
        self.shortest = normaliser.shortest if normaliser.pairs else 1 << 62
        self.path: set[int] = set()
        self.deadline = time.perf_counter() + MAX_SECONDS
        self.adapters: dict[type, Callable[[Any], str]] | None = None  # when first needed

    def load_adapters(self) -> dict[type, Callable[[Any], str]]:
        self.adapters = _adapters()
        return self.adapters

    def stop(self, out: bytearray, tag: bytes = b"X") -> None:
        out += tag
        self.complete = False

    def value(self, value: Any, depth: int, out: bytearray) -> None:  # noqa: PLR0912 - a branch per type
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            self.stop(out)
            return
        if self.nodes % _CHECK_EVERY == 0 and time.perf_counter() > self.deadline:
            self.stop(out)
            return
        kind = type(value)
        if value is None:
            out += b"N"
        elif kind is bool:
            out += b"T" if value else b"F"
        elif kind is int:
            out += b"I" + hex(value).encode() + b";"
        elif kind is float:
            out += b"D" + value.hex().encode() + b";"
        elif kind is str:
            if len(value) >= self.shortest or "0x" in value or "0X" in value:
                value = self.normalise(value)  # it may hold a directory or an address
            data = value.encode("utf-8", "surrogatepass")
            out += b"S%d:" % len(data) + data
        elif kind is bytes or kind is bytearray:
            out += (b"B%d:" if kind is bytes else b"A%d:") % len(value) + value
        elif kind is complex:
            out += b"C" + value.real.hex().encode() + b"," + value.imag.hex().encode() + b";"
        elif kind in _SEQUENCES or kind is dict or kind in _SETS:
            self.container(value, kind, depth, out)
        elif kind in _OPAQUE:
            out += b"P" + _OPAQUE[kind] + b":" + self.callable_name(value, kind) + b";"
        elif issubclass(kind, type):
            out += b"K" + type_name(value).encode("utf-8", "surrogatepass") + b";"
        elif issubclass(kind, BaseException):
            self.exception(value, kind, depth, out)
        elif kind in (self.adapters or self.load_adapters()):
            self.adapted(value, kind, out)
        elif (base := _builtin_base(kind)) is not None:
            self.subclassed(value, kind, base, depth, out)
        elif _is_enum(kind):
            state = dict(_state(value, kind) or ())
            name = state.get("_name_")
            text = name if type(name) is str else "?"
            out += (
                b"V"
                + type_name(kind).encode("utf-8", "surrogatepass")
                + b"="
                + text.encode()
                + b";"
            )
        else:
            self.instance(value, kind, depth, out)

    def adapted(self, value: Any, kind: type, out: bytearray) -> None:
        try:
            text = (self.adapters or self.load_adapters())[kind](value)
        except Exception:  # noqa: BLE001
            self.stop(out)
            return
        data = str(text).encode("utf-8", "surrogatepass")
        out += b"V" + type_name(kind).encode() + b"=" + str(len(data)).encode() + b":" + data

    @staticmethod
    def callable_name(value: Any, kind: type) -> bytes:
        if kind is types.FunctionType:
            try:
                return str(_FUNCTION_QUALNAME.__get__(value)).encode("utf-8", "surrogatepass")
            except Exception:  # noqa: BLE001
                return b"?"
        return type_name(kind).encode()

    def container(
        self, value: Any, kind: type, depth: int, out: bytearray, *, subclass: bool = False
    ) -> None:
        """A list, tuple, dict, set or frozenset, never rebuilt (rebuilding a set or a dict would
        hash its elements again). An exact one is read through its own protocol, which for an
        exact builtin is the interpreter's; a subclass's (``subclass``, ``kind`` its builtin
        base) through ``kind``'s own iterators, which walk the underlying storage without
        calling the subclass's overrides. A container that holds itself is stopped by the depth
        guard."""
        if kind is list or kind is tuple:
            tag = b"L%d[" if kind is list else b"U%d["
            if subclass:
                out += tag % _LENGTH[kind](value)
                items: Iterator[Any] = _ITERATE[kind](value)
            else:
                out += tag % len(value)
                items = iter(value)
            for item in items:
                self.value(item, depth + 1, out)
            out += b"]"
        elif kind is dict:
            pairs = []
            for key, item in dict.items(value):
                pair = bytearray()
                self.value(key, depth + 1, pair)
                self.value(item, depth + 1, pair)
                pairs.append(bytes(pair))
            ordered = sorted(pairs)
            if ordered == pairs:
                self.orders += b"."
            else:  # its insertion order, as the sorted positions its entries came in
                ranked = sorted(range(len(pairs)), key=pairs.__getitem__)
                self.orders += b"(" + ",".join(map(str, ranked)).encode() + b")"
            out += b"M%d{" % len(pairs) + b"".join(ordered) + b"}"
        else:
            # Elements in the order of their encodings, and the orders of any dictionaries
            # inside them with them: a set's iteration order depends on the hash seed.
            start = len(self.orders)
            parts = []
            for item in _ITERATE[kind](value) if subclass else value:
                part = bytearray()
                before = len(self.orders)
                self.value(item, depth + 1, part)
                parts.append((bytes(part), bytes(self.orders[before:])))
                del self.orders[before:]
            parts.sort()
            del self.orders[start:]
            self.orders += b"".join(orders for _, orders in parts)
            out += _SETS[kind] + b"%d(" % len(parts) + b"".join(part for part, _ in parts) + b")"

    def exception(self, value: BaseException, kind: type, depth: int, out: bytearray) -> None:
        out += b"R" + type_name(kind).encode("utf-8", "surrogatepass") + b"("
        try:
            args = _EXCEPTION_ARGS.__get__(value)
        except Exception:  # noqa: BLE001
            args = None
        self.value(args if type(args) is tuple else None, depth + 1, out)
        chain = []
        link: Any = value
        for _ in range(MAX_DEPTH):
            try:
                cause = _EXCEPTION_CAUSE.__get__(link)
                link = cause if cause is not None else _EXCEPTION_CONTEXT.__get__(link)
            except Exception:  # noqa: BLE001
                link = None
            if link is None or not issubclass(type(link), BaseException):
                break
            chain.append(type_name(type(link)))
        out += b"|" + ",".join(chain).encode("utf-8", "surrogatepass") + b")"

    def subclassed(self, value: Any, kind: type, base: type, depth: int, out: bytearray) -> None:
        """A builtin's subclass (a named tuple, an ``int`` subclass): its builtin value, read
        through the base type's own methods, then its own state."""
        out += b"W" + type_name(kind).encode("utf-8", "surrogatepass") + b"("
        if base in _SEQUENCES or base is dict or base in _SETS:
            self.container(value, base, depth + 1, out, subclass=True)
        else:
            try:
                plain = _AS_BUILTIN[base](value)
            except Exception:  # noqa: BLE001
                self.stop(out)
                return
            self.value(plain, depth + 1, out)
        state = _state(value, kind) or []
        for field, item in state:
            self.value(field, depth + 1, out)
            self.value(item, depth + 1, out)
        out += b")"

    def instance(self, value: Any, kind: type, depth: int, out: bytearray) -> None:
        name = type_name(kind).encode("utf-8", "surrogatepass")
        state = _state(value, kind)
        if state is None:
            out += b"O" + name + b";"
            return
        if id(value) in self.path:
            self.stop(out, b"Y")
            return
        self.path.add(id(value))
        try:
            out += b"J" + name + b"{"
            for field, item in state:
                self.value(field, depth + 1, out)
                self.value(item, depth + 1, out)
            out += b"}"
        finally:
            self.path.discard(id(value))


# A builtin subclass's scalar value, through the base type's own C methods (never the
# subclass's overrides): each returns an instance of exactly the base type. Containers are
# walked through their base's iterators instead (``_Walk.container``).
_AS_BUILTIN: dict[type, Callable[[Any], Any]] = {
    int: lambda v: int.__add__(v, 0),
    float: float.__pos__,
    complex: complex.__pos__,
    str: str.__str__,
    bytes: lambda v: bytes.__getitem__(v, slice(None)),
    bytearray: lambda v: bytearray.__getitem__(v, slice(None)),
}
# The containers' own C iterators and lengths, which read their storage directly.
_ITERATE: dict[type, Callable[[Any], Iterator[Any]]] = {
    list: list.__iter__,
    tuple: tuple.__iter__,
    set: set.__iter__,
    frozenset: frozenset.__iter__,
}
_LENGTH: dict[type, Callable[[Any], int]] = {list: list.__len__, tuple: tuple.__len__}
_BUILTIN_BASES = frozenset({*_AS_BUILTIN, *_ITERATE, dict})


def _builtin_base(kind: type) -> type | None:
    """The builtin value type ``kind`` derives from, if any (bool cannot be subclassed)."""
    try:
        for klass in _TYPE_MRO.__get__(kind):
            if klass in _BUILTIN_BASES:
                return klass  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        return None
    return None


def _is_enum(kind: type) -> bool:
    enum = sys.modules.get("enum")
    return enum is not None and issubclass(kind, enum.Enum)


def _state(value: Any, kind: type) -> list[tuple[str, Any]] | None:
    """An instance's fields: its dictionary's items, then its slots' values, through the
    interpreter's own descriptors; None if the type gives them through anything else."""
    fields: list[tuple[str, Any]] = []
    try:
        has_dict = False
        for klass in _TYPE_MRO.__get__(kind):
            namespace = _TYPE_DICT.__get__(klass)
            entry = namespace.get("__dict__", _ABSENT)
            if entry is not _ABSENT and not has_dict:
                has_dict = True
                if type(entry) is not _GETSET:
                    return None  # a __dict__ of the class's own: user code
                instance_dict = entry.__get__(value, kind)
                if type(instance_dict) is not dict:
                    return None
                fields.extend(
                    (key, item) for key, item in instance_dict.items() if type(key) is str
                )
            slots = namespace.get("__slots__", ())
            for slot in (slots,) if type(slots) is str else slots:
                if type(slot) is not str or slot in ("__dict__", "__weakref__"):
                    continue
                descriptor = namespace.get(slot, _ABSENT)
                if type(descriptor) is not _MEMBER:
                    return None  # a slot replaced by a descriptor of the class's own
                try:
                    fields.append((slot, descriptor.__get__(value, kind)))
                except AttributeError:
                    continue  # an unset slot
    except Exception:  # noqa: BLE001 - anything odd about the type: opaque
        return None
    return fields


_DEFAULT: list[Normaliser] = []


def _normaliser() -> Normaliser:
    if not _DEFAULT:
        _DEFAULT.append(default_normaliser())
    return _DEFAULT[0]


def _run(value: Any) -> tuple[bytes, bytes, bool]:
    """The canonical bytes (dictionaries sorted), the dictionaries' orders, completeness."""
    walk = _Walk()
    out = bytearray()
    try:
        walk.value(value, 0, out)
    except Exception:  # noqa: BLE001 - e.g. a container changed size while walked: incomplete
        out += b"X"
        walk.complete = False
    return bytes(out), bytes(walk.orders), walk.complete


def encode(value: Any) -> tuple[bytes, bool]:
    """The canonical bytes of ``value`` (with its dictionaries' orders, when it holds any), and
    whether the walk was complete."""
    data, orders, complete = _run(value)
    return (data + b"#" + orders if orders else data), complete


def digest(value: Any) -> tuple[str, bool]:
    """BLAKE2b-128 of ``value``'s canonical bytes (hex), and whether the walk was complete."""
    data, complete = encode(value)
    return blake2b(data, digest_size=16).hexdigest(), complete


def digests(value: Any) -> tuple[str, str, bool]:
    """The digest, the order-insensitive digest (the same when ``value`` holds no dictionary),
    and whether the walk was complete; one walk."""
    data, orders, complete = _run(value)
    hashed = blake2b(data, digest_size=16)
    unordered = hashed.hexdigest()
    if not orders:
        return unordered, unordered, complete
    hashed.update(b"#" + orders)
    return hashed.hexdigest(), unordered, complete


# -- previews ------------------------------------------------------------------------------------

#: A preview's length at most (the event schema's ``Preview``).
PREVIEW_CHARACTERS = 512
#: Integers this long or longer are shown by size (their decimal form would fill a preview).
_PREVIEW_INT_BITS = 512
_ELLIPSIS = "…"


class _Full(Exception):  # noqa: N818 - control flow: the preview is long enough
    pass


class _Preview:
    """A short, readable rendering of a value under the encoder's rules: builtins through their
    own C ``repr``, sets in their canonical order, objects as ``Type(field=value)`` from their
    state, opaque things by name. Never a call into the target's code."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.parts: list[str] = []
        self.size = 0
        self.nodes = 0
        self.path: set[int] = set()
        self.adapters = _adapters()

    def put(self, text: str) -> None:
        self.parts.append(text)
        self.size += len(text)
        if self.size > self.limit:
            raise _Full

    def value(self, value: Any, depth: int) -> None:  # noqa: PLR0912 - a branch per type
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            self.put(_ELLIPSIS)
            return
        kind = type(value)
        if value is None or kind is bool or kind is float or kind is complex:
            self.put(repr(value))  # exact builtins: their own C repr
        elif kind is int:
            bits = value.bit_length()
            self.put(int.__repr__(value) if bits < _PREVIEW_INT_BITS else f"<int {bits} bits>")
        elif kind is str:
            self.put(str.__repr__(_normaliser().text(value)))
        elif kind is bytes or kind is bytearray:
            self.put(kind.__repr__(value))
        elif kind in _SEQUENCES or kind is dict or kind in _SETS:
            self.container(value, kind, depth)
        elif kind in _OPAQUE:
            self.put(f"<{_OPAQUE[kind].decode()} {_Walk.callable_name(value, kind).decode()}>")
        elif issubclass(kind, type):
            self.put(f"<class {type_name(value)}>")
        elif issubclass(kind, BaseException):
            self.put(f"{type_name(kind)}(")
            try:
                args = _EXCEPTION_ARGS.__get__(value)
            except Exception:  # noqa: BLE001
                args = ()
            self.items(args if type(args) is tuple else (), depth)
            self.put(")")
        elif kind in self.adapters:
            try:
                text = str(self.adapters[kind](value))
            except Exception:  # noqa: BLE001
                text = "?"
            self.put(f"{type_name(kind)}({text})")
        elif _is_enum(kind):
            name = dict(_state(value, kind) or ()).get("_name_")
            self.put(f"{type_name(kind)}.{name if type(name) is str else '?'}")
        else:
            self.instance(value, kind, depth)

    def items(self, values: Any, depth: int) -> None:
        for index, item in enumerate(values):
            if index:
                self.put(", ")
            self.value(item, depth + 1)

    def container(self, value: Any, kind: type, depth: int) -> None:
        if id(value) in self.path:
            self.put("<cycle>")
            return
        self.path.add(id(value))
        try:
            if kind is list or kind is tuple:
                self.put("[" if kind is list else "(")
                self.items(_ITERATE[kind](value), depth)
                self.put("]" if kind is list else ")")
            elif kind is dict:
                self.put("{")
                for index, (key, item) in enumerate(dict.items(value)):
                    if index:
                        self.put(", ")
                    self.value(key, depth + 1)
                    self.put(": ")
                    self.value(item, depth + 1)
                self.put("}")
            else:
                members = sorted(_ITERATE[kind](value), key=lambda item: encode(item)[0])
                self.put("frozenset({" if kind is frozenset else "{")
                self.items(members, depth)
                self.put("})" if kind is frozenset else "}")
        finally:
            self.path.discard(id(value))

    def instance(self, value: Any, kind: type, depth: int) -> None:
        base = _builtin_base(kind)
        state = _state(value, kind)
        if state is None and base is None:
            self.put(f"<{type_name(kind)}>")
            return
        if id(value) in self.path:
            self.put("<cycle>")
            return
        self.path.add(id(value))
        try:
            self.put(f"{type_name(kind)}(")
            first = True
            if base is not None:
                if base in _AS_BUILTIN:
                    self.value(_AS_BUILTIN[base](value), depth + 1)
                else:
                    self.container(value, base, depth + 1)
                first = False
            for field, item in state or ():
                self.put(("" if first else ", ") + f"{field}=")
                self.value(item, depth + 1)
                first = False
            self.put(")")
        finally:
            self.path.discard(id(value))


def preview(value: Any, limit: int = PREVIEW_CHARACTERS) -> str:
    """At most ``limit`` characters showing ``value`` (ending in an ellipsis when cut)."""
    walk = _Preview(limit - 1)
    try:
        walk.value(value, 0)
    except _Full:
        pass
    except Exception:  # noqa: BLE001
        walk.parts.append(_ELLIPSIS)
    text = "".join(walk.parts)
    return text if len(text) <= limit else text[: limit - 1] + _ELLIPSIS

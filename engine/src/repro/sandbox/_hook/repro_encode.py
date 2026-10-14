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

**Two digests.** A dictionary is written in insertion order; a second digest writes every
dictionary sorted by its keys' encodings, so a difference in order alone can be told apart.

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

    def text(self, value: str) -> str:
        replaced = False
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
    __slots__ = ("adapters", "complete", "deadline", "has_dict", "nodes", "path", "sort_dicts")

    def __init__(self, sort_dicts: bool) -> None:
        self.nodes = 0
        self.complete = True
        self.sort_dicts = sort_dicts
        self.has_dict = False
        self.path: set[int] = set()
        self.deadline = time.perf_counter() + MAX_SECONDS
        self.adapters = _adapters()

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
            data = _normaliser().text(value).encode("utf-8", "surrogatepass")
            out += b"S" + str(len(data)).encode() + b":" + data
        elif kind is bytes or kind is bytearray:
            out += (b"B" if kind is bytes else b"A") + str(len(value)).encode() + b":" + value
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
        elif kind in self.adapters:
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
            text = self.adapters[kind](value)
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

    def container(self, value: Any, kind: type, depth: int, out: bytearray) -> None:
        """A list, tuple, dict, set or frozenset, or (with ``kind`` its builtin base) a
        subclass of one: read through ``kind``'s own iterators, which walk the underlying
        storage without calling a subclass's overrides, and never rebuilt (rebuilding a set or
        a dict would hash its elements)."""
        if id(value) in self.path:
            self.stop(out, b"Y")  # a cycle: the container is already being written
            return
        self.path.add(id(value))
        try:
            if kind in _SEQUENCES:
                out += _SEQUENCES[kind] + str(_LENGTH[kind](value)).encode() + b"["
                for item in _ITERATE[kind](value):
                    self.value(item, depth + 1, out)
                out += b"]"
            elif kind is dict:
                self.has_dict = True
                pairs = []
                for key, item in dict.items(value):
                    pair = bytearray()
                    self.value(key, depth + 1, pair)
                    self.value(item, depth + 1, pair)
                    pairs.append(bytes(pair))
                if self.sort_dicts:
                    pairs.sort()
                out += b"M" + str(len(pairs)).encode() + b"{" + b"".join(pairs) + b"}"
            else:
                parts = []
                for item in _ITERATE[kind](value):
                    part = bytearray()
                    self.value(item, depth + 1, part)
                    parts.append(bytes(part))
                parts.sort()
                out += _SETS[kind] + str(len(parts)).encode() + b"(" + b"".join(parts) + b")"
        finally:
            self.path.discard(id(value))

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
            self.container(value, base, depth + 1, out)
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


def encode(value: Any, *, sort_dicts: bool = False) -> tuple[bytes, bool]:
    """The canonical bytes of ``value``, and whether the walk was complete."""
    return _run(_Walk(sort_dicts), value)


def _run(walk: _Walk, value: Any) -> tuple[bytes, bool]:
    out = bytearray()
    try:
        walk.value(value, 0, out)
    except Exception:  # noqa: BLE001 - e.g. a container changed size while walked: incomplete
        out += b"X"
        walk.complete = False
    return bytes(out), walk.complete


def digest(value: Any) -> tuple[str, bool]:
    """BLAKE2b-128 of ``value``'s canonical bytes (hex), and whether the walk was complete."""
    data, complete = encode(value)
    return blake2b(data, digest_size=16).hexdigest(), complete


def digests(value: Any) -> tuple[str, str, bool]:
    """The ordered digest, the digest with every dictionary sorted (the same when ``value``
    holds no dictionary), and whether the walk was complete."""
    walk = _Walk(False)
    data, complete = _run(walk, value)
    ordered = blake2b(data, digest_size=16).hexdigest()
    if not walk.has_dict:
        return ordered, ordered, complete
    sorted_data, _ = encode(value, sort_dicts=True)
    return ordered, blake2b(sorted_data, digest_size=16).hexdigest(), complete

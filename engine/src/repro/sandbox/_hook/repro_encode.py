"""Values to stable digests, for Repro's tracer (E01; ADR-0005, ARCHITECTURE §4.3).

A value becomes a tagged byte string, CBOR-like, hashed with BLAKE2b-128. The same value gives
the same bytes in every process, whatever the hash seed: sets and frozensets are written in the
order of their elements' own encodings, floats as ``float.hex()`` (so NaN, infinities and -0.0
each have one form), integers in hexadecimal (no digit limit applies).

**No user code runs.** Only the exact builtin types are walked: ``None``, ``bool``, ``int``,
``float``, ``complex``, ``str``, ``bytes``, ``bytearray``, ``list``, ``tuple``, ``dict``,
``set``, ``frozenset``. A subclass of any of them, like every other object, is an opaque token
naming its type, read from the type itself: its ``__eq__``, ``__repr__``, ``__iter__`` and
properties are never called. E02 adds structural walks of objects, exceptions and paths.

**Guards.** Deeper than ``MAX_DEPTH`` or past ``MAX_NODES`` values, the walk stops with a
truncation tag, and the encoding is *incomplete*: the engine never takes two incomplete
encodings as equal.

The standard library only: this runs in the target's interpreter (Python 3.12 to 3.15).
"""

from hashlib import blake2b
from typing import Any

MAX_DEPTH = 6
MAX_NODES = 5000
_SEQUENCES: dict[type, bytes] = {list: b"L", tuple: b"U"}
_SETS: dict[type, bytes] = {set: b"E", frozenset: b"Z"}


class _Walk:
    __slots__ = ("complete", "nodes")

    def __init__(self) -> None:
        self.nodes = 0
        self.complete = True

    def value(self, value: Any, depth: int, out: bytearray) -> None:  # noqa: PLR0912 - a branch per type
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            out += b"X"
            self.complete = False
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
            data = value.encode("utf-8", "surrogatepass")
            out += b"S" + str(len(data)).encode() + b":" + data
        elif kind is bytes or kind is bytearray:
            out += (b"B" if kind is bytes else b"A") + str(len(value)).encode() + b":" + value
        elif kind is complex:
            out += b"C" + value.real.hex().encode() + b"," + value.imag.hex().encode() + b";"
        elif kind in _SEQUENCES:
            out += _SEQUENCES[kind] + str(len(value)).encode() + b"["
            for item in value:
                self.value(item, depth + 1, out)
            out += b"]"
        elif kind is dict:
            out += b"M" + str(len(value)).encode() + b"{"
            for key, item in value.items():
                self.value(key, depth + 1, out)
                self.value(item, depth + 1, out)
            out += b"}"
        elif kind in _SETS:
            parts = []
            for item in value:
                part = bytearray()
                self.value(item, depth + 1, part)
                parts.append(bytes(part))
            parts.sort()
            out += _SETS[kind] + str(len(parts)).encode() + b"(" + b"".join(parts) + b")"
        else:
            out += b"O" + type_name(kind).encode("utf-8", "surrogatepass") + b";"


def type_name(kind: type) -> str:
    """``module.qualname`` of a type, read from the type's own attributes (no metaclass code)."""
    try:
        module = type.__getattribute__(kind, "__module__")
        qualname = type.__getattribute__(kind, "__qualname__")
    except Exception:  # noqa: BLE001 - a hostile type: still a name, never an error
        return "<unnamed type>"
    return f"{module}.{qualname}" if isinstance(module, str) and isinstance(qualname, str) else "?"


def encode(value: Any) -> tuple[bytes, bool]:
    """The canonical bytes of ``value``, and whether the walk was complete."""
    walk = _Walk()
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

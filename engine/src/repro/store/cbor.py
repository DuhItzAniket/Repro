"""Deterministic CBOR (RFC 8949) for Repro's artifacts: observations (E03) and what cites them.

The subset Repro writes: ``None``, booleans, integers from -2**64 to 2**64 - 1, floats, text,
bytes, lists (and tuples, written as lists) and maps. ``encode`` follows the core deterministic
encoding requirements (RFC 8949 §4.2.1): every argument as short as possible, floats in the
shortest form that keeps their value, definite lengths only, and each map's keys in the bytewise
order of their encodings. Equal values therefore always give the same bytes, which is what makes
an artifact's SHA-256 its identity.

``decode`` reads only that subset back and refuses anything else: tags, indefinite lengths,
simple values other than ``false``, ``true`` and ``null``, duplicate keys, trailing bytes, and
any item not in its deterministic form (it re-encodes what it read and compares). Artifacts are
written by Repro itself, but a file on disk is still checked before it is believed; nothing in
it can run code (THREAT_MODEL T14).
"""

import math
import struct
from typing import Any, Final

#: Containers nested deeper than this are refused (on both sides of the codec).
MAX_DEPTH: Final = 64
_UINT64: Final = 1 << 64


class CBORError(ValueError):
    """A value Repro's CBOR cannot hold, or bytes that are not in its deterministic form."""


def _head(major: int, argument: int) -> bytes:
    """An item's initial byte and its argument, as short as possible (RFC 8949 §4.2.1)."""
    kind = major << 5
    if argument < 24:  # noqa: PLR2004 - the RFC's boundaries
        return bytes((kind | argument,))
    if argument < 1 << 8:
        return bytes((kind | 24, argument))
    if argument < 1 << 16:
        return bytes((kind | 25,)) + argument.to_bytes(2, "big")
    if argument < 1 << 32:
        return bytes((kind | 26,)) + argument.to_bytes(4, "big")
    return bytes((kind | 27,)) + argument.to_bytes(8, "big")


def _float(value: float) -> bytes:
    """The shortest of binary16, binary32 and binary64 that keeps ``value`` (NaN as 0xf97e00)."""
    if math.isnan(value):
        return b"\xf9\x7e\x00"
    for code, form in ((0xF9, ">e"), (0xFA, ">f")):
        try:
            packed = struct.pack(form, value)
        except OverflowError:
            continue
        if struct.unpack(form, packed)[0] == value:
            return bytes((code,)) + packed
    return b"\xfb" + struct.pack(">d", value)


def encode(value: Any) -> bytes:
    """``value`` in deterministic CBOR; ``CBORError`` for anything outside the subset."""
    out = bytearray()
    _encode(value, out, 0)
    return bytes(out)


def _encode(value: Any, out: bytearray, depth: int) -> None:  # noqa: PLR0912 - a branch per type
    if depth > MAX_DEPTH:
        raise CBORError(f"nested deeper than {MAX_DEPTH}")
    kind = type(value)
    if value is None:
        out += b"\xf6"
    elif kind is bool:
        out += b"\xf5" if value else b"\xf4"
    elif kind is int:
        if not -_UINT64 <= value < _UINT64:
            raise CBORError(f"integer out of range: {value}")
        out += _head(0, value) if value >= 0 else _head(1, -1 - value)
    elif kind is float:
        out += _float(value)
    elif kind is str:
        data = value.encode("utf-8")  # a lone surrogate is not text: UnicodeEncodeError
        out += _head(3, len(data)) + data
    elif kind is bytes:
        out += _head(2, len(value)) + value
    elif kind is list or kind is tuple:
        out += _head(4, len(value))
        for item in value:
            _encode(item, out, depth + 1)
    elif kind is dict:
        pairs: list[tuple[bytes, Any]] = []
        for key, item in value.items():
            key_bytes = bytearray()
            _encode(key, key_bytes, depth + 1)
            pairs.append((bytes(key_bytes), item))
        pairs.sort(key=lambda pair: pair[0])
        out += _head(5, len(pairs))
        for key_data, item in pairs:
            out += key_data
            _encode(item, out, depth + 1)
    else:
        raise CBORError(f"not encodable: {kind.__name__}")


def decode(data: bytes) -> Any:
    """The value ``data`` holds; ``CBORError`` unless it is exactly one item of the subset, in
    its deterministic form."""
    reader = _Reader(data)
    value = reader.item(0)
    if reader.at != len(data):
        raise CBORError(f"{len(data) - reader.at} bytes after the item")
    if encode(value) != data:
        raise CBORError("not in deterministic form")
    return value


class _Reader:
    __slots__ = ("at", "data")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def take(self, count: int) -> bytes:
        end = self.at + count
        if end > len(self.data):
            raise CBORError("the data ends inside an item")
        chunk = self.data[self.at : end]
        self.at = end
        return chunk

    def argument(self, info: int) -> int:
        if info < 24:  # noqa: PLR2004
            return info
        if info > 27:  # noqa: PLR2004 - 28-30 reserved, 31 indefinite length
            raise CBORError(f"unsupported additional information {info}")
        return int.from_bytes(self.take(1 << (info - 24)), "big")

    def item(self, depth: int) -> Any:  # noqa: PLR0911 - a return per major type
        if depth > MAX_DEPTH:
            raise CBORError(f"nested deeper than {MAX_DEPTH}")
        initial = self.take(1)[0]
        major, info = initial >> 5, initial & 0x1F
        if major == 7:  # noqa: PLR2004
            return self.simple(info)
        argument = self.argument(info)
        if major == 0:
            return argument
        if major == 1:
            return -1 - argument
        if major in (2, 3):
            chunk = self.take(argument)
            if major == 2:  # noqa: PLR2004
                return chunk
            try:
                return chunk.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CBORError("text that is not UTF-8") from exc
        if major == 4:  # noqa: PLR2004
            self.room(argument)
            return [self.item(depth + 1) for _ in range(argument)]
        if major == 5:  # noqa: PLR2004
            self.room(2 * argument)
            found: dict[Any, Any] = {}
            for _ in range(argument):
                key = self.item(depth + 1)
                if isinstance(key, (list, dict)):
                    raise CBORError("a map key that is a container")
                if key in found:
                    raise CBORError(f"duplicate map key {key!r}")
                found[key] = self.item(depth + 1)
            return found
        raise CBORError(f"unsupported major type {major} (tags are not used)")

    def room(self, items: int) -> None:
        """Each item takes a byte at least: a count past the data's end is refused before any
        list is made for it."""
        if items > len(self.data) - self.at:
            raise CBORError("a count larger than the data left")

    def simple(self, info: int) -> Any:
        if info == 20:  # noqa: PLR2004
            return False
        if info == 21:  # noqa: PLR2004
            return True
        if info == 22:  # noqa: PLR2004
            return None
        forms = {25: ">e", 26: ">f", 27: ">d"}
        if info in forms:
            size = struct.calcsize(forms[info])
            value: float = struct.unpack(forms[info], self.take(size))[0]
            return value
        raise CBORError(f"unsupported simple value or break ({info})")

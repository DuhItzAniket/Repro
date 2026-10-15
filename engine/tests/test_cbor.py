"""Repro's deterministic CBOR (E03) against RFC 8949's own examples and its §4.2.1 rules.

The vectors are RFC 8949 Appendix A's, for the subset Repro uses (no tags, no indefinite
lengths, no simple values beyond false, true and null); verified against
https://www.rfc-editor.org/rfc/rfc8949.html on 2026-10-15.
"""

import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from repro.store.cbor import MAX_DEPTH, CBORError, decode, encode

APPENDIX_A: list[tuple[Any, str]] = [
    (0, "00"),
    (1, "01"),
    (10, "0a"),
    (23, "17"),
    (24, "1818"),
    (25, "1819"),
    (100, "1864"),
    (1000, "1903e8"),
    (1000000, "1a000f4240"),
    (1000000000000, "1b000000e8d4a51000"),
    (18446744073709551615, "1bffffffffffffffff"),
    (-18446744073709551616, "3bffffffffffffffff"),
    (-1, "20"),
    (-10, "29"),
    (-100, "3863"),
    (-1000, "3903e7"),
    (0.0, "f90000"),
    (-0.0, "f98000"),
    (1.0, "f93c00"),
    (1.1, "fb3ff199999999999a"),
    (1.5, "f93e00"),
    (65504.0, "f97bff"),
    (100000.0, "fa47c35000"),
    (3.4028234663852886e38, "fa7f7fffff"),
    (1.0e300, "fb7e37e43c8800759c"),
    (5.960464477539063e-8, "f90001"),
    (0.00006103515625, "f90400"),
    (-4.0, "f9c400"),
    (-4.1, "fbc010666666666666"),
    (math.inf, "f97c00"),
    (-math.inf, "f9fc00"),
    (False, "f4"),
    (True, "f5"),
    (None, "f6"),
    (b"", "40"),
    (b"\x01\x02\x03\x04", "4401020304"),
    ("", "60"),
    ("a", "6161"),
    ("IETF", "6449455446"),
    ('"\\', "62225c"),
    ("ü", "62c3bc"),
    ("水", "63e6b0b4"),
    ("\U00010151", "64f0908591"),
    ([], "80"),
    ([1, 2, 3], "83010203"),
    ([1, [2, 3], [4, 5]], "8301820203820405"),
    (list(range(1, 26)), "98190102030405060708090a0b0c0d0e0f101112131415161718181819"),
    ({}, "a0"),
    ({1: 2, 3: 4}, "a201020304"),
    ({"a": 1, "b": [2, 3]}, "a26161016162820203"),
    (["a", {"b": "c"}], "826161a161626163"),
    (
        {"a": "A", "b": "B", "c": "C", "d": "D", "e": "E"},
        "a56161614161626142616361436164614461656145",
    ),
]


@pytest.mark.parametrize(("value", "encoded"), APPENDIX_A, ids=[e for _, e in APPENDIX_A])
def test_rfc_8949_appendix_a(value: Any, encoded: str) -> None:
    assert encode(value).hex() == encoded
    back = decode(bytes.fromhex(encoded))
    assert back == value
    assert type(back) is type(value)
    if isinstance(value, float):
        assert math.copysign(1, back) == math.copysign(1, value)  # -0.0 stays negative


def test_nan_has_one_form() -> None:
    assert encode(math.nan).hex() == "f97e00"  # Appendix A's binary16 NaN
    assert math.isnan(decode(bytes.fromhex("f97e00")))
    for longer in ("fa7fc00000", "fb7ff8000000000000"):  # the same NaN, not in shortest form
        with pytest.raises(CBORError, match="deterministic"):
            decode(bytes.fromhex(longer))


def test_map_keys_sort_by_their_encodings() -> None:
    # RFC 8949 §4.2.1: bytewise order of the keys' encodings, so 10 (0x0a) < 100 (0x1864) <
    # -1 (0x20) < "z" (0x617a) < "aa" (0x626161) < [100] (0x811864) < [-1] (0x8120).
    value = {"aa": 0, "z": 0, 100: 0, -1: 0, 10: 0, False: 0, b"x": 0}
    assert (
        encode(value).hex()
        == "a7" + "0a00" + "186400" + "2000" + "417800" + "617a00" + ("62616100") + "f400"
    )
    assert encode(dict(reversed(value.items()))) == encode(value)  # insertion order is ignored


def test_tuples_are_lists() -> None:
    assert encode((1, (2, 3))) == encode([1, [2, 3]])


@pytest.mark.parametrize(
    ("hex_data", "reason"),
    [
        ("1817", "deterministic"),  # 23 with a needless extra byte
        ("190017", "deterministic"),
        ("a2616201616101", "deterministic"),  # {"b": 1, "a": 1}: keys out of order
        ("a2616101616102", "duplicate"),
        ("9fff", "additional information 31"),  # indefinite-length list
        ("5f42010243030405ff", "additional information 31"),
        ("c11a514b67b0", "major type 6"),  # a tag
        ("f7", "simple value"),  # undefined
        ("f0", "simple value"),
        ("1c", "additional information 28"),
        ("6161ff", "after the item"),
        ("62c3", "ends inside"),
        ("62c328", "not UTF-8"),
        ("9b00000000ffffffff", "count larger"),
        ("a1810000", "container"),
        ("", "ends inside"),
    ],
)
def test_what_decode_refuses(hex_data: str, reason: str) -> None:
    with pytest.raises(CBORError, match=reason):
        decode(bytes.fromhex(hex_data))


@pytest.mark.parametrize(
    "value",
    [object(), {1, 2}, 1 << 64, -(1 << 64) - 1, bytearray(b"x"), "\ud800"],
    ids=["object", "set", "too big", "too small", "bytearray", "lone surrogate"],
)
def test_what_encode_refuses(value: Any) -> None:
    with pytest.raises((CBORError, UnicodeEncodeError)):
        encode(value)


def test_depth_is_bounded_both_ways() -> None:
    deep: Any = []
    for _ in range(MAX_DEPTH + 1):
        deep = [deep]
    with pytest.raises(CBORError, match="deeper"):
        encode(deep)
    with pytest.raises(CBORError, match="deeper"):
        decode(b"\x81" * (MAX_DEPTH + 1) + b"\x80")


integers = st.integers(min_value=-(1 << 64), max_value=(1 << 64) - 1)
scalars = (
    st.none() | st.booleans() | integers | st.floats(allow_nan=False) | st.text() | st.binary()
)
values = st.recursive(
    scalars,
    lambda children: (
        st.lists(children, max_size=6)
        | st.dictionaries(st.text(max_size=8) | integers, children, max_size=6)
    ),
    max_leaves=40,
)


@given(values)
def test_round_trip_and_one_form(value: Any) -> None:
    data = encode(value)
    assert decode(data) == value
    assert encode(decode(data)) == data

"""The canonical encoder (E02): property tests and a hostile-object corpus.

Roadmap E02: "Hypothesis property tests (stable across processes and hash seeds, never calls
user dunders, guards terminate, truncated values are never equal) plus a fuzz corpus of
hostile objects." The encoder runs in the target's interpreter, so it is loaded from the hook
directory as a plain module, as the sandbox loads it.
"""

import importlib.util
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import hostile
from repro.runner.trace import same
from repro.sandbox.detect import HOOK_DIR


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repro_encode", HOOK_DIR / "repro_encode.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENCODE = load()
KEEP = ("SYSTEMROOT", "PATH")

scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.integers(min_value=10**30, max_value=10**60)
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=20)
    | st.binary(max_size=20)
    | st.complex_numbers(allow_nan=False, allow_infinity=False)
)
hashables = (
    st.none() | st.booleans() | st.integers() | st.text(max_size=10) | st.binary(max_size=10)
)
values = st.recursive(
    scalars,
    lambda children: (
        st.lists(children, max_size=5)
        | st.tuples(children, children)
        | st.dictionaries(hashables, children, max_size=5)
        | st.sets(hashables, max_size=8)
        | st.frozensets(hashables, max_size=8)
    ),
    max_leaves=30,
)


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(values, min_size=1, max_size=20))
def test_the_same_digests_in_other_processes_and_hash_seeds(batch: list[Any]) -> None:
    """Pickled here (our own generated builtins), digested in fresh interpreters with other
    hash seeds: string sets iterate in another order there, digests must not change."""
    here = [ENCODE.digest(value) for value in batch]
    module = str(HOOK_DIR / "repro_encode.py")
    script = (
        "import importlib.util, pickle, sys\n"
        f"spec = importlib.util.spec_from_file_location('e', {module!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "batch = pickle.loads(sys.stdin.buffer.read())\n"
        "sys.stdout.buffer.write(pickle.dumps([m.digest(v) for v in batch]))\n"
    )
    for seed in ("1", "4242"):
        env = {"PYTHONHASHSEED": seed, **{k: os.environ[k] for k in KEEP if k in os.environ}}
        done = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input=pickle.dumps(batch),
            env=env,
            capture_output=True,
            check=True,
        )
        assert pickle.loads(done.stdout) == here  # noqa: S301 - our own child's output


@settings(max_examples=200, deadline=None)
@given(values)
def test_equal_values_have_equal_digests(value: Any) -> None:
    assert ENCODE.digest(value) == ENCODE.digest(pickle.loads(pickle.dumps(value)))  # noqa: S301


@pytest.mark.parametrize("name", sorted(hostile.CORPUS))
def test_no_user_code_runs_on_hostile_objects(name: str) -> None:
    value = hostile.CORPUS[name]()
    hostile.CALLED.clear()
    data, _ = ENCODE.encode(value)
    assert hostile.CALLED == []
    assert data  # an encoding, whatever it holds
    ENCODE.digests([value, {"in": value}])
    assert hostile.CALLED == []


@settings(max_examples=100, deadline=None)
@given(st.lists(st.sampled_from(sorted(hostile.CORPUS)), max_size=6), values)
def test_no_user_code_runs_on_mixtures(names: list[str], value: Any) -> None:
    mixture = [hostile.CORPUS[name]() for name in names]
    mixed: Any = [value, mixture, {"x": tuple(mixture)}]
    hostile.CALLED.clear()
    ENCODE.digests(mixed)
    assert hostile.CALLED == []


def test_what_objects_encode_to() -> None:
    slots = ENCODE.encode(hostile.Slots())[0]
    assert b"hostile.Slots{" in slots  # its slots' values, not opaque
    assert ENCODE.encode(hostile.ReplacedSlot())[0] == b"Ohostile.ReplacedSlot;"
    assert ENCODE.encode(hostile.OwnDict())[0] == b"Ohostile.OwnDict;"
    assert ENCODE.encode(hostile.WithMeta)[0] == b"Khostile.WithMeta;"  # not "forged"
    first, second = hostile.Property(), hostile.Property()
    second.kept = 4
    assert ENCODE.digest(first) != ENCODE.digest(second)  # state, not just the type
    error = ENCODE.encode(hostile.chained())[0]
    assert error.startswith(b"Rbuiltins.ValueError(")
    assert error.endswith(b"|hostile.HostileError)")


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=0, max_value=60), st.integers(min_value=1, max_value=20_000))
def test_guards_terminate(depth: int, width: int) -> None:
    deep: Any = []
    for _ in range(depth):
        deep = [deep, list(range(min(width, 50)))]
    start = time.perf_counter()
    _, complete = ENCODE.encode([deep, list(range(width))])
    assert time.perf_counter() - start < 1.0
    expected = depth < ENCODE.MAX_DEPTH and width + 2 < ENCODE.MAX_NODES
    if not expected:
        assert complete is False


def test_cycles_are_incomplete() -> None:
    for value in (hostile.cyclic(), hostile.cyclic_object()):
        data, complete = ENCODE.encode(value)
        assert complete is False
        assert b"Y" in data


@settings(max_examples=200, deadline=None)
@given(values, values)
def test_truncated_values_are_never_equal(left: Any, right: Any) -> None:
    deep_left: Any = left
    for _ in range(ENCODE.MAX_DEPTH + 1):
        deep_left = [deep_left]
    truncated = ENCODE.digest(deep_left)
    assert truncated[1] is False
    assert same(truncated, truncated) is None
    assert same(truncated, ENCODE.digest(right)) is None
    assert same(ENCODE.digest(right), ENCODE.digest(right)) is True


def test_directories_and_addresses_are_normalised() -> None:
    root = str(Path("snapshot-a").resolve())
    other = str(Path("snapshot-b").resolve())
    one = ENCODE.Normaliser({"<ROOT>": root, "<TMP>": "", "<HOME>": ""})
    two = ENCODE.Normaliser({"<ROOT>": other, "<TMP>": "", "<HOME>": ""})
    assert one.text(f"{root}\\pkg\\data.json") == two.text(f"{other}/pkg/data.json")
    assert one.text(f"{root}\\pkg\\data.json") == "<ROOT>/pkg/data.json"
    assert one.text("<object at 0x0000017D6B008A50>") == "<object at <ADDR>>"
    assert one.text("0x1f is small") == "0x1f is small"  # under six hex digits: a number


def test_dictionary_order_has_its_own_digest() -> None:
    ordered_a, any_order_a, _ = ENCODE.digests({"a": 1, "b": 2})
    ordered_b, any_order_b, _ = ENCODE.digests({"b": 2, "a": 1})
    assert ordered_a != ordered_b
    assert any_order_a == any_order_b
    plain = ENCODE.digests([1, 2])
    assert plain[0] == plain[1]


def test_standard_library_values() -> None:
    import datetime  # noqa: PLC0415
    import decimal  # noqa: PLC0415
    import enum  # noqa: PLC0415
    import fractions  # noqa: PLC0415
    import re  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    class Colour(enum.Enum):
        RED = 1

    moment = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
    for value, text in (
        (moment, b"2026-01-02T03:04:05+00:00"),
        (datetime.timedelta(days=1, seconds=2), b"1,2,0"),
        (decimal.Decimal("1.10"), b"1.10"),
        (fractions.Fraction(1, 3), b"1/3"),
        (uuid.UUID(int=5), b"00000000000000000000000000000005"),
        (re.compile("a+", re.I), b"a+"),
        (Colour.RED, b"RED"),
    ):
        assert text in ENCODE.encode(value)[0]
    assert ENCODE.digest(decimal.Decimal("1.10")) != ENCODE.digest(decimal.Decimal("1.1"))


class Point(tuple[int, ...]):
    """A builtin subclass with state of its own (no __slots__)."""


def test_builtin_subclasses_keep_their_value() -> None:
    from collections import namedtuple  # noqa: PLC0415

    pair = namedtuple("pair", "a b")
    assert ENCODE.digest(pair(1, 2)) != ENCODE.digest(pair(1, 3))
    assert ENCODE.digest(pair(1, 2)) != ENCODE.digest((1, 2))  # its type is part of it
    assert ENCODE.digest(hostile.Subclassed(a=1)) != ENCODE.digest(hostile.Subclassed(a=2))
    marked = Point((1,))
    marked.note = "x"  # type: ignore[attr-defined]
    assert ENCODE.digest(marked) != ENCODE.digest(Point((1,)))

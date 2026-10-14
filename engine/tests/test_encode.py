"""The tracer's encoder (E01): stable digests, no user code run, guards.

The encoder runs inside the target's interpreter, so it is loaded here from the hook directory
the same way, as a plain module.
"""

import importlib.util
import os
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from repro.sandbox.detect import HOOK_DIR


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repro_encode", HOOK_DIR / "repro_encode.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENCODE = load()


def digest(value: Any) -> str:
    return str(ENCODE.digest(value)[0])


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (1, True),
        (0, False),
        (1, 1.0),
        ("a", b"a"),
        (b"a", bytearray(b"a")),
        ([1, 2], (1, 2)),
        ({1}, frozenset({1})),
        (0.0, -0.0),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),  # insertion order is part of a dict's value here
        ("", None),
        ([], ()),
    ],
)
def test_different_values_differ(left: Any, right: Any) -> None:
    assert digest(left) != digest(right)


def test_equal_values_are_equal() -> None:
    assert digest({"x", "y", "z"}) == digest({"z", "x", "y"})
    assert digest(float("nan")) == digest(float("nan"))
    assert digest(10**5000) == digest(10**5000)  # no int digit limit applies
    assert digest([1, [2, {"k": (3,)}]]) == digest([1, [2, {"k": (3,)}]])
    assert digest(1 + 2j) == digest(complex(1, 2))


#: What a Python process needs from the environment to start (Windows needs SYSTEMROOT).
KEEP = ("SYSTEMROOT", "PATH")


def test_the_same_digest_in_any_process_and_hash_seed() -> None:
    value = "{'apple', 'banana', 'cherry', 'date'}, frozenset({b'x', b'y'}), {'k': {1.5, 2.5}}"
    module = str(HOOK_DIR / "repro_encode.py")
    script = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('e', {module!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"print(m.digest(({value}))[0])\n"
    )
    found = set()
    for seed in ("0", "1", "12345"):
        done = subprocess.run(
            [sys.executable, "-I", "-c", script],
            env={"PYTHONHASHSEED": seed, **{k: os.environ[k] for k in KEEP if k in os.environ}},
            capture_output=True,
            text=True,
            check=True,
        )
        found.add(done.stdout.strip())
    assert len(found) == 1


class Hostile:
    def __eq__(self, other: object) -> bool:
        raise AssertionError("__eq__ was called")

    def __hash__(self) -> int:
        raise AssertionError("__hash__ was called")

    def __repr__(self) -> str:
        raise AssertionError("__repr__ was called")

    def __iter__(self) -> Any:
        raise AssertionError("__iter__ was called")

    def __len__(self) -> int:
        raise AssertionError("__len__ was called")

    @property
    def value(self) -> int:
        raise AssertionError("a property was read")


class Number(int):
    def __repr__(self) -> str:
        raise AssertionError("a subclass's __repr__ was called")


def test_no_user_code_runs() -> None:
    data, complete = ENCODE.encode([Hostile(), Number(3), {"k": Hostile()}])
    assert complete
    assert b"test_encode.Hostile" in data
    assert b"test_encode.Number" in data  # a subclass is opaque, not an int
    assert digest(Number(3)) != digest(3)


def test_guards_make_an_encoding_incomplete() -> None:
    deep: list[Any] = []
    for _ in range(ENCODE.MAX_DEPTH + 2):
        deep = [deep]
    assert ENCODE.encode(deep)[1] is False
    wide = list(range(ENCODE.MAX_NODES + 1))
    assert ENCODE.encode(wide)[1] is False
    assert ENCODE.encode(list(range(10)))[1] is True

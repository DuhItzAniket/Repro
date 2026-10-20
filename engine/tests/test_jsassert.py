"""Edited JavaScript and TypeScript tests' assertions, read from the TypeScript compiler's syntax
tree (K11; ADR-0017, phase 4). The counterpart of ``test_outcomes.py``'s test-diff cases: real
test sources parsed by the pinned compiler."""

from pathlib import Path

import pytest

from repro import jsassert
from repro.jsassert import Argument, Assertion
from repro.runner.testdiff import TestChangeKind
from ts_support import NEEDS_NODE, pinned

pytestmark = NEEDS_NODE


@pytest.fixture(scope="module")
def package(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return pinned(pytestconfig, tmp_path_factory)


def wrapped(lines: str) -> str:
    return 'test("t", async () => {\n' + lines + "});\n"


def changes(
    package: Path, tmp_path: Path, base: str, head: str, file: str = "t.test.ts"
) -> list[tuple[TestChangeKind, str]]:
    """What head's version of a one-test file does to base's, by the real compiler."""
    old, new = wrapped(base), wrapped(head)
    spans = [{"t": (1, old.count("\n"))}, {"t": (1, new.count("\n"))}]
    found = jsassert.assertions(
        package,
        [jsassert.Source(file, old, spans[0]), jsassert.Source(file, new, spans[1])],
        tmp_path,
    )
    return jsassert.compare(found[0]["t"], found[1]["t"])


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        # An exact matcher became a looser one.
        (
            "  expect(add(1, 2)).toBe(3);\n",
            "  expect(add(1, 2)).toBeTruthy();\n",
            "toBe(…) → toBeTruthy()",
        ),
        (
            "  expect(o).toEqual({ a: 1 });\n",
            "  expect(o).toBeDefined();\n",
            "toEqual(…) → toBeDefined()",
        ),
        (
            "  expect(o).toStrictEqual(p);\n",
            "  expect(o).not.toBeNull();\n",
            "toStrictEqual(p) → not.toBeNull()",
        ),
        (
            "  expect(o).toMatchObject({ a: 1 });\n",
            "  expect(o).toBeTruthy();\n",
            "toMatchObject(…) → toBeTruthy()",
        ),
        ("  expect(x).toBe(2);\n", "  expect(x).not.toBe(1);\n", "toBe(…) → not.toBe(…)"),
        (
            "  assert.strictEqual(a, 1);\n",
            "  assert.ok(a);\n",
            "assert.strictEqual(a, …) → assert.ok(a)",
        ),
        ("  expect(a).to.equal(1);\n", "  expect(a).to.be.ok;\n", "to.equal(…) → to.be.ok"),
    ],
)
def test_a_weakened_assertion(
    package: Path, tmp_path: Path, base: str, head: str, expected: str
) -> None:
    assert changes(package, tmp_path, base, head) == [
        ("assertion_weakened", f"a check became a looser one: {expected}")
    ]


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        (
            "  expect(() => f()).toThrow(TypeError);\n",
            "  expect(() => f()).toThrow();\n",
            "toThrow(TypeError) → toThrow()",
        ),
        (
            "  expect(() => f()).toThrow(/bad/);\n",
            "  expect(() => f()).toThrow(Error);\n",
            "toThrow(/…/) → toThrow(Error)",
        ),
        (
            '  await expect(p).rejects.toThrow("bad");\n',
            "  await expect(p).rejects.toThrow();\n",
            'rejects.toThrow("…") → rejects.toThrow()',
        ),
        (
            "  assert.throws(f, RangeError);\n",
            "  assert.throws(f);\n",
            "assert.throws(f, RangeError) → assert.throws(f)",
        ),
    ],
)
def test_a_widened_throw_check(
    package: Path, tmp_path: Path, base: str, head: str, expected: str
) -> None:
    # Widened, not also weakened: a throw check's strength does not depend on what it accepts.
    assert changes(package, tmp_path, base, head) == [
        ("raises_widened", f"a throw check accepts more than on base: {expected}")
    ]


def test_a_removed_assertion_by_the_syntax_tree(package: Path, tmp_path: Path) -> None:
    both = "  expect(a).toBe(1);\n  expect(b).toBe(2);\n"
    assert changes(package, tmp_path, both, "  expect(a).toBe(1);\n") == [
        ("assertion_removed", "2 expect or assert calls on base, 1 on head")
    ]
    # A matcher deleted leaves expect(b), which a scanner of expect( calls still counted.
    assert changes(package, tmp_path, both, "  expect(a).toBe(1);\n  expect(b);\n") == [
        ("assertion_removed", "2 expect or assert calls on base, 1 on head")
    ]
    # Assertions in comments and strings are none.
    commented = '  expect(a).toBe(1);\n  // expect(b).toBe(2);\n  log("expect(b).toBe(2)");\n'
    assert changes(package, tmp_path, both, commented) == [
        ("assertion_removed", "2 expect or assert calls on base, 1 on head")
    ]


def test_an_edit_that_keeps_or_strengthens_the_assertions(package: Path, tmp_path: Path) -> None:
    assert changes(package, tmp_path, "  expect(x).toBe(3);\n", "  expect(x).toBe(4);\n") == []
    assert changes(package, tmp_path, "  expect(x).toBeTruthy();\n", "  expect(x).toBe(4);\n") == []
    narrower = ("  expect(f).toThrow();\n", "  expect(f).toThrow(TypeError);\n")
    assert changes(package, tmp_path, *narrower) == []
    javascript = ("  expect(x).toEqual([1]);\n", "  expect(x).toStrictEqual([1]);\n")
    assert changes(package, tmp_path, *javascript, file="t.test.js") == []


def test_only_the_tests_own_lines_count(package: Path, tmp_path: Path) -> None:
    source = (
        'test("one", () => {\n  expect(a).toBe(1);\n});\n'
        'test("two", () => {\n  expect(b).toBe(2);\n  expect(c).toBeTruthy();\n});\n'
    )
    spans = {"one": (1, 3), "two": (4, 7)}
    (found,) = jsassert.assertions(package, [jsassert.Source("t.test.js", source, spans)], tmp_path)
    assert [a.text() for a in found["one"]] == ["toBe(…)"]
    assert [(a.line, a.text(), a.strength()) for a in found["two"]] == [
        (5, "toBe(…)", 2),
        (6, "toBeTruthy()", 0),
    ]


@pytest.mark.parametrize(
    ("chain", "args", "strength"),
    [
        (("toBeNull",), (), 2),
        (("not", "toBeNull"), (), 0),
        (("not", "toBeDefined"), (), 2),
        (("toHaveProperty",), (Argument("string"),), 1),
        (("toHaveProperty",), (Argument("string"), Argument("other")), 2),
        (("toBeGreaterThan",), (Argument("other"),), 1),
        (("not", "toThrow"), (), 0),
    ],
)
def test_strengths(chain: tuple[str, ...], args: tuple[Argument, ...], strength: int) -> None:
    assert Assertion(1, "expect", chain, True, args).strength() == strength
    assert Assertion(1, "assert", (), True, (Argument("name", "x"),)).strength() == 0

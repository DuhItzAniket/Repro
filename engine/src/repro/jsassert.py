"""Edited JavaScript and TypeScript tests' assertions, from the TypeScript compiler's syntax tree
(K11; ADR-0017, phase 4).

D06's checks of an edited test (``repro.runner.testdiff``) for JavaScript. A test's own lines on
each side are ``jsmap.own_lines``'s; the pinned compiler (``repro.analysis.typescript``) parses
the file, and each assertion whose first line is in the test's lines is the test's:
- an ``expect(...)`` chain (Jest, Vitest, Chai's ``expect``), with ``expect.soft`` and
  ``expect.poll``; a chain may end in a call (``.toBe(3)``) or not (``.to.be.true``), and a
  bare ``expect(x)`` is no assertion;
- an ``assert(...)`` or ``assert.<name>(...)`` call (Node's ``assert``, Chai's).

Each has a strength, as Python's do: 2 for an exact check (``toBe``, ``toEqual``,
``toStrictEqual``, ``toMatchObject``, ``toBeNull``, a snapshot, ``assert.strictEqual``), 0 for a
truth test (``toBeTruthy``, ``toBeDefined``, ``not.toBeNull``, ``not.toThrow()``,
``assert.ok``, a bare ``assert``), 1 for anything else (``toContain``, ``toBeGreaterThan``); a
negated exact check is 1, an inequality.

- ``assertion_removed``: fewer assertions than on base;
- ``assertion_weakened``: as many, but weaker in all: a check became a looser one;
- ``raises_widened``: a ``toThrow`` (``toThrowError``, Chai's ``throw``, ``assert.throws``,
  ``assert.rejects``) now accepts more than on base: it names no error class or only ``Error``
  where base named one, or it lost its message or pattern. A name passed to it is taken as an
  error class. Its own strength is constant: a ``toThrow`` that accepts more is this finding
  alone, not also a weakened assertion.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.analysis import typescript
from repro.jsmap import Span
from repro.runner.testdiff import TestChangeKind

#: Exact checks: a value, a call's arguments, a count, a snapshot.
EXACT: Final = frozenset(
    {
        # Jest and Vitest
        "toBe",
        "toEqual",
        "toStrictEqual",
        "toMatchObject",
        "toBeNull",
        "toBeUndefined",
        "toBeNaN",
        "toHaveLength",
        "toMatchSnapshot",
        "toMatchInlineSnapshot",
        "toMatchFileSnapshot",
        "toThrowErrorMatchingSnapshot",
        "toThrowErrorMatchingInlineSnapshot",
        "toHaveBeenCalledWith",
        "toHaveBeenLastCalledWith",
        "toHaveBeenNthCalledWith",
        "toHaveBeenCalledExactlyOnceWith",
        "toHaveBeenCalledTimes",
        "toHaveReturnedWith",
        "toHaveLastReturnedWith",
        "toHaveNthReturnedWith",
        "toHaveReturnedTimes",
        "toBeCalledWith",
        "toBeCalledTimes",
        "lastCalledWith",
        "nthCalledWith",
        "toReturnWith",
        # Chai and Node's assert
        "equal",
        "equals",
        "eq",
        "eql",
        "eqls",
        "strictEqual",
        "deepEqual",
        "deepStrictEqual",
        "true",
        "false",
        "null",
        "undefined",
        "NaN",
        "isTrue",
        "isFalse",
        "isNull",
        "isUndefined",
        "isNaN",
        "lengthOf",
        "sameMembers",
        "sameDeepMembers",
    }
)
#: Truth tests: something, anything.
TRUTH: Final = frozenset(
    {
        "toBeTruthy",
        "toBeFalsy",
        "toBeDefined",
        "toHaveBeenCalled",
        "toBeCalled",
        "toHaveReturned",
        "toReturn",
        "ok",
        "isOk",
        "isNotOk",
        "exist",
        "exists",
        "isDefined",
        "isNotNull",
        "isNotUndefined",
    }
)
#: Negated, these are truth tests too: ``not.toBeNull`` is "it is something".
_NOT_NOTHING: Final = frozenset({"toBeNull", "toBeUndefined", "null", "undefined"})
#: Negated checks that are exact: ``not.toBeDefined`` is ``toBeUndefined``.
_NEGATED: Final[Mapping[str, int]] = {"toBeDefined": 2}
#: Checks that the code throws, which may name an error class or a message.
THROWS: Final = frozenset({"toThrow", "toThrowError", "throw", "throws", "Throw"})
_ASSERT_THROWS: Final = frozenset({"throws", "rejects"})
#: The error class that accepts any error.
_BROAD: Final = "Error"
_MATCHES: Final = frozenset({"string", "regex", "other"})


@dataclass(frozen=True, slots=True)
class Argument:
    kind: str  # string, regex, name, other
    name: str | None = None

    def text(self) -> str:
        return {"string": '"…"', "regex": "/…/", "name": self.name or "…"}.get(self.kind, "…")


@dataclass(frozen=True, slots=True)
class Assertion:
    """An assertion as the worker reads it: where, an ``expect`` chain or an ``assert`` call,
    the names after the root, and the last call's arguments."""

    line: int
    root: str  # expect, assert
    chain: tuple[str, ...]
    called: bool
    args: tuple[Argument, ...]

    @property
    def matcher(self) -> str:
        return self.chain[-1] if self.chain else self.root

    @property
    def negated(self) -> bool:
        return "not" in self.chain[:-1]

    @property
    def throws(self) -> bool:
        """Whether it checks that something throws (``not.toThrow`` does not)."""
        if self.root == "assert":
            return self.matcher in _ASSERT_THROWS
        return self.matcher in THROWS and not self.negated

    def strength(self) -> int:
        """2 exact, 1 a comparison, 0 a truth test; a throw check is 1 whatever it accepts."""
        name = self.matcher
        if self.throws:
            return 1
        if self.negated:  # not.toBeNull: "something"; not.toThrow(): "it runs"; not.toBe: "≠"
            truth = name in _NOT_NOTHING or name in TRUTH or name in THROWS
            return _NEGATED.get(name, 0 if truth else 1)
        if name in ("toHaveProperty", "property"):
            return 2 if len(self.args) >= 2 else 1  # noqa: PLR2004 - a name and a value
        if self.root == "assert" and not self.chain:
            return 0  # assert(x)
        return 2 if name in EXACT else 0 if name in TRUTH else 1

    def raises(self) -> tuple[bool, bool]:
        """A throw check's (broad, has a message or pattern), as Python's ``pytest.raises``."""
        args = self.args[1:] if self.root == "assert" else self.args
        classes = [a.name for a in args if a.kind == "name"]
        broad = all(name == _BROAD for name in classes)
        return broad, any(a.kind in _MATCHES for a in args)

    def text(self) -> str:
        """``toBe(…)``, ``not.toBeNull()``, ``to.be.true``, ``assert.ok(…)``."""
        names = ".".join(self.chain) if self.root == "expect" else ".".join(("assert", *self.chain))
        if not self.called:
            return names
        return f"{names}({', '.join(a.text() for a in self.args)})"


def _assertion(data: Mapping[str, Any]) -> Assertion:
    args = tuple(
        Argument(str(a["kind"]), None if a.get("name") is None else str(a["name"]))
        for a in data["args"]
    )
    chain = tuple(str(name) for name in data["chain"])
    return Assertion(int(data["line"]), str(data["root"]), chain, bool(data["called"]), args)


def read(response: Sequence[Mapping[str, Any]]) -> list[dict[str, tuple[Assertion, ...]]]:
    """Each file's tests' assertions from the worker's answer, in source order."""
    return [
        {
            str(test): tuple(sorted((_assertion(a) for a in found), key=lambda a: a.line))
            for test, found in file.items()
        }
        for file in response
    ]


@dataclass(frozen=True, slots=True)
class Source:
    """A test file on one side: its path, its text, and the edited tests' lines in it."""

    file: str
    text: str
    spans: Mapping[str, Span]


def assertions(
    package: Path, sources: Sequence[Source], work: Path
) -> list[dict[str, tuple[Assertion, ...]]]:
    """Each source's tests' assertions, read with the pinned compiler in ``package``. Raises
    ``typescript.TypeScriptError`` if it cannot run."""
    request = [
        {"file": s.file, "text": s.text, "spans": {t: list(span) for t, span in s.spans.items()}}
        for s in sources
    ]
    return read(typescript.run(package, {"tests": request}, work)["tests"])


def compare(
    base: Sequence[Assertion], head: Sequence[Assertion]
) -> list[tuple[TestChangeKind, str]]:
    """How head's version of a test is weaker than base's, each with a short detail."""
    found: list[tuple[TestChangeKind, str]] = []
    if len(head) < len(base):
        found.append(
            (
                "assertion_removed",
                f"{len(base)} expect or assert calls on base, {len(head)} on head",
            )
        )
    elif sum(a.strength() for a in head) < sum(a.strength() for a in base):
        pairs = [(b, h) for b, h in zip(base, head, strict=False) if h.strength() < b.strength()]
        detail = "a check became a looser one" + (
            f": {pairs[0][0].text()} → {pairs[0][1].text()}" if pairs else ""
        )
        found.append(("assertion_weakened", detail))
    old = [a for a in base if a.throws]
    new = [a for a in head if a.throws]
    for before, after in zip(old, new, strict=False):
        (b_broad, b_match), (h_broad, h_match) = before.raises(), after.raises()
        if (h_broad and not b_broad) or (b_match and not h_match):
            found.append(
                (
                    "raises_widened",
                    f"a throw check accepts more than on base: {before.text()} → {after.text()}",
                )
            )
            break
    return found

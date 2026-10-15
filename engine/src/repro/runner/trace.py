"""Tracing a side's tests (E01): which functions to trace, and what a traced run could not see.

A target is a symbol of C06 (``module:qualname#ordinal``) on one side; the tracer is given its
file, qualified name and line span on that side (``TraceTarget``), so a code object is traced
when it is that function, whatever else its file defines. A run's calls come back keyed by the
target they belong to.

A change's plan (E03) traces the functions it changed that exist on both sides (modified,
renamed or moved), each on its own side, and files both sides' calls under the change's symbol
ID, so base's and head's calls of one function meet under one name.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from repro.analysis.blast import module_of
from repro.analysis.changes import SymbolChange
from repro.runner.pytest import MAX_TARGETS, PytestRun, TraceCall, TraceTarget
from repro.runner.selection import CONFTEST, Resolver, base_id, head_id

#: Targets listed one by one in a missing item's detail, at most.
LISTED: Final = 5
#: The changes whose function exists on both sides, so its calls can be compared.
TRACED_CHANGES: Final = frozenset({"modified", "renamed", "moved"})


def targets_for(symbols: Iterable[str], resolver: Resolver) -> list[TraceTarget]:
    """The trace targets for ``symbols`` on ``resolver``'s side; those it cannot find (the
    side does not have them, or they are a module's own code) are left out."""
    return [target for target, _ in _found(symbols, resolver)]


@dataclass(frozen=True, slots=True)
class TracePlan:
    """What to trace on each side, each target with the symbol its calls are filed under."""

    base: Mapping[TraceTarget, str]
    head: Mapping[TraceTarget, str]
    #: Changed functions not traced: past ``MAX_TARGETS`` on a side.
    left_out: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.base) and bool(self.head)

    def without_test_code(self, test_modules: set[str]) -> "TracePlan":
        """The plan without test code (as ``selection.uncovered`` tells it): functions of the
        modules tests are collected from, and of ``conftest.py`` files. Which modules those are
        is known only once the tests are collected, so they are traced, then left out here."""

        def kept(side: Mapping[TraceTarget, str]) -> dict[TraceTarget, str]:
            return {
                target: symbol
                for target, symbol in side.items()
                if PurePosixPath(target[0]).name != CONFTEST
                and module_of(symbol) not in test_modules
            }

        return TracePlan(kept(self.base), kept(self.head), self.left_out)


def plan(changes: Sequence[SymbolChange], resolvers: tuple[Resolver, Resolver]) -> TracePlan:
    """The functions of ``changes`` that exist on both sides, as targets on each."""
    traced = [c for c in changes if c.change in TRACED_CHANGES and c.kind in ("function", "method")]
    sides = []
    left_out: set[str] = set()
    for side_id, resolver in ((base_id, resolvers[0]), (head_id, resolvers[1])):
        symbols = {found: c.symbol_id for c in traced if (found := side_id(c)) is not None}
        named = {target: symbols[found] for target, found in _found(symbols, resolver)}
        kept = dict(sorted(named.items(), key=lambda item: (item[1], item[0]))[:MAX_TARGETS])
        left_out |= set(named.values()) - set(kept.values())
        sides.append(kept)
    both = set(sides[0].values()) & set(sides[1].values())
    return TracePlan(
        {t: s for t, s in sides[0].items() if s in both},
        {t: s for t, s in sides[1].items() if s in both},
        tuple(sorted(left_out)),
    )


def _found(symbols: Iterable[str], resolver: Resolver) -> list[tuple[TraceTarget, str]]:
    """Each target of ``symbols`` on ``resolver``'s side, with the symbol it is."""
    paths: dict[str, str] = {}
    for path, module in resolver.names.items():
        paths.setdefault(module, path)
    wanted = sorted(set(symbols))
    resolver.load(paths[s.partition(":")[0]] for s in wanted if s.partition(":")[0] in paths)
    found: list[tuple[TraceTarget, str]] = []
    for symbol in wanted:
        file = paths.get(symbol.partition(":")[0])
        table = resolver.table(file) if file is not None else None
        if file is None or table is None:
            continue
        found.extend(
            ((file, candidate.qualname, candidate.start, candidate.end), symbol)
            for candidate in table.symbols
            if candidate.id == symbol and candidate.kind in ("function", "method")
        )
    return found


def same(left: tuple[str, bool], right: tuple[str, bool]) -> bool | None:
    """Whether two encodings (digest, complete) are of the same value; None when either is
    incomplete: a truncated or failed encoding is never taken as equal to anything (E02)."""
    if not left[1] or not right[1]:
        return None
    return left[0] == right[0]


def calls_by_target(run: PytestRun) -> dict[tuple[str, TraceTarget], list[TraceCall]]:
    """Each (test, target)'s calls, in the order they started."""
    grouped: dict[tuple[str, TraceTarget], list[TraceCall]] = {}
    for call in run.calls:
        grouped.setdefault((call.test, call.target), []).append(call)
    for calls in grouped.values():
        calls.sort(key=lambda call: call.index)
    return grouped


def trace_missing(
    run: PytestRun, side: str, names: Mapping[TraceTarget, str] | None = None
) -> list[dict[str, Any]]:
    """``missing.recorded`` payloads: no trace at all, or targets whose budget ran out (named by
    their symbols when ``names`` maps them)."""
    items: list[dict[str, Any]] = []
    if run.map_unavailable:
        items.append(
            _missing(
                "trace_unavailable",
                f"{side}: no behaviour trace: {run.map_unavailable}",
                [],
                "Free a sys.monitoring tool ID (Repro takes 4, 3, 2 or 5) in the test run",
            )
        )
    if run.truncated:
        targets = sorted({target for _, target in run.truncated})
        named = [(names or {}).get(target, f"{target[0]}:{target[1]}") for target in targets]
        shown = ", ".join(named[:LISTED]) + (
            f" and {len(named) - LISTED} more" if len(named) > LISTED else ""
        )
        tests = len({test for test, _ in run.truncated})
        items.append(
            _missing(
                "trace_truncated",
                f"{side}: calls past the budget were not recorded, in {tests} tests: {shown}",
                [{"symbol": name} if ":" in name and "#" in name else {} for name in named],
                None,
            )
        )
    return items


def _missing(
    reason: str, detail: str, targets: Sequence[dict[str, str]], resolution: str | None
) -> dict[str, Any]:
    return {
        "missing": {
            "reason": reason,
            "targets": [t for t in targets if t],
            "detail": detail[:1000],
            "resolution": resolution,
        }
    }

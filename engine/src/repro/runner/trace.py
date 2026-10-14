"""Tracing a side's tests (E01): which functions to trace, and what a traced run could not see.

A target is a symbol of C06 (``module:qualname#ordinal``) on one side; the tracer is given its
file, qualified name and line span on that side (``TraceTarget``), so a code object is traced
when it is that function, whatever else its file defines. A run's calls come back keyed by the
target they belong to.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from repro.runner.pytest import PytestRun, TraceCall, TraceTarget
from repro.runner.selection import Resolver

#: Targets listed one by one in a missing item's detail, at most.
LISTED: Final = 5


def targets_for(symbols: Iterable[str], resolver: Resolver) -> list[TraceTarget]:
    """The trace targets for ``symbols`` on ``resolver``'s side; those it cannot find (the
    side does not have them, or they are a module's own code) are left out."""
    paths: dict[str, str] = {}
    for path, module in resolver.names.items():
        paths.setdefault(module, path)
    wanted = sorted(set(symbols))
    resolver.load(paths[s.partition(":")[0]] for s in wanted if s.partition(":")[0] in paths)
    found: list[TraceTarget] = []
    for symbol in wanted:
        file = paths.get(symbol.partition(":")[0])
        table = resolver.table(file) if file is not None else None
        if file is None or table is None:
            continue
        found.extend(
            (file, candidate.qualname, candidate.start, candidate.end)
            for candidate in table.symbols
            if candidate.id == symbol and candidate.kind in ("function", "method")
        )
    return found


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

"""Two-sided execution (D06, ARCHITECTURE §4): the selected tests on base and head, run so that
what differs is the change and not the run.

1. **A**: base, mapped, every test (or, with the base map cached, only the selected ones).
2. Head's tests are listed, and the tests to run are selected (D05).
3. **A2**: base again, the selected tests in the reverse order, with another ``PYTHONHASHSEED``
   and another seed for ``random``.
4. **H**: head, the selected tests, mapped (coverage of head-only code, and DeFlaker's check).

With a trace plan (E03), A and A2 trace base's changed functions and H head's: the
observations ``repro.runner.observations`` compares.
5. Each flip (A and A2 agreeing, H differing) runs again *k* times on both sides.
6. The base version of each edited test runs against head's code.

A run that does not finish leaves its tests unclassified and becomes a missing item (``timeout``
or ``environment_failed``), with every collection error (``collection_error``); outcomes are only
compared where both runs reported them.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from repro.analysis.changes import SymbolChange
from repro.analysis.imports import ImportGraph
from repro.runner.outcomes import RERUNS, OutcomeDiff, classify, is_flip, passes
from repro.runner.pytest import TestRun
from repro.runner.selection import (
    MapCache,
    Resolver,
    Selected,
    TestMap,
    base_id,
    head_id,
    select,
    test_map,
    uncovered,
)
from repro.runner.sides import Side
from repro.runner.testdiff import TestChange, test_changes
from repro.runner.trace import TracePlan

#: A2's hash seed and ``random`` seed: anything but the sandbox's and the plugin's 0.
OTHER_HASH_SEED: Final = 1
OTHER_SEED: Final = 1
#: The traced runs, by label.
TRACED_RUNS: Final = ("A", "A2", "H")
OVERLAY: Final = "base_tests"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One pytest run on one side: what it was for, the tests asked for, how it went."""

    side: str
    label: str  # "A", "A2", "H", "rerun 1".., "head tests", "base tests on head"
    tests: tuple[str, ...]  # the tests asked for (empty: every test)
    run: TestRun


def _empty() -> TestMap:
    return TestMap({}, {})


@dataclass
class TwoSided:
    selected: tuple[Selected, ...] = ()
    gaps: tuple[SymbolChange, ...] = ()
    base_map: TestMap = field(default_factory=_empty)
    head_tests: TestMap = field(default_factory=_empty)
    head_map: TestMap = field(default_factory=_empty)
    outcomes: tuple[OutcomeDiff, ...] = ()
    test_changes: tuple[TestChange, ...] = ()
    runs: list[RunRecord] = field(default_factory=list)
    map_cached: bool = False
    #: What A, A2 and H traced (None: nothing).
    trace: TracePlan | None = None

    def traced(self) -> dict[str, RunRecord]:
        """A, A2 and H, those that ran, by label."""
        return {r.label: r for r in self.runs if r.label in TRACED_RUNS}

    def problems(self) -> list[dict[str, Any]]:
        """``missing.recorded`` payloads for runs that did not finish, collection errors, and a
        map that could not be made."""
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for record in self.runs:
            results, execution = record.run.results, record.run.execution
            for error in results.collect_errors:
                if (record.side, error.nodeid) not in seen:
                    seen.add((record.side, error.nodeid))
                    detail = f"{record.side}: {error.nodeid} did not collect: {error.message}"
                    items.append(_missing("collection_error", detail, _file(error.nodeid)))
            if not results.complete:
                timed_out = execution.outcome == "timeout"
                ended = "took longer than its limit" if timed_out else "ended early"
                detail = (
                    f"{record.side}: the {record.label} run {ended} (exit status "
                    f"{execution.returncode}); {len(results.tests)} tests reported"
                )
                items.append(_missing("timeout" if timed_out else "environment_failed", detail))
            if results.map_unavailable:
                detail = f"{record.side}: no test map ({results.map_unavailable})"
                items.append(_missing("trace_unavailable", detail))
        return items


def _file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0] or "."


def _missing(reason: str, detail: str, file: str | None = None) -> dict[str, Any]:
    return {
        "missing": {
            "reason": reason,
            "targets": [{"file": file}] if file else [],
            "detail": detail[:1000],
            "resolution": None,
        }
    }


def _outcome(done: TestRun | None, test: str) -> str | None:
    found = done.results.tests.get(test) if done is not None else None
    return found.outcome if found is not None else None


def _message(done: TestRun | None, test: str) -> str | None:
    found = done.results.tests.get(test) if done is not None else None
    return found.message if found is not None else None


Observe = Callable[[RunRecord], None]


class _Reproduction:
    def __init__(
        self,
        sides: tuple[Side, Side],
        resolvers: tuple[Resolver, Resolver],
        observe: Observe | None,
        stop: Callable[[], bool] | None,
        trace: TracePlan | None = None,
    ) -> None:
        self.base, self.head = sides
        self.resolvers = resolvers
        self.observe = observe
        self.stop = stop
        self.result = TwoSided(trace=trace or None)
        self.on_base = list(trace.base) if trace else []
        self.on_head = list(trace.head) if trace else []
        self.a: TestRun | None = None
        self.a2: TestRun | None = None
        self.h: TestRun | None = None

    def run(self, side: Side, label: str, tests: Sequence[str] = (), **options: Any) -> TestRun:
        done = side.run(tests, stop=self.stop, **options)
        record = RunRecord(side.name, label, tuple(tests), done)
        self.result.runs.append(record)
        if self.observe is not None and label != "A":
            self.observe(record)
        return done

    def map_base(self, cache: MapCache | None, key: str | None) -> TestRun | None:
        """The base map: from the cache, or from A run over every test."""
        cached = cache.get(key) if cache is not None and key is not None else None
        if cached is not None:
            self.result.base_map, self.result.map_cached = cached, True
            return None
        full = self.run(self.base, "A", map_tests=True, trace=self.on_base)
        self.result.base_map = test_map(full.results, self.resolvers[0])
        if cache is not None and key is not None and full.results.complete:
            cache.put(key, self.result.base_map)
        return full

    def run_selected(self, full: TestRun | None, on_base: list[str], on_head: list[str]) -> None:
        if full is not None:
            self.a = full
            if self.observe is not None:
                self.observe(RunRecord("base", "A", tuple(on_base), full))
        elif on_base:
            self.a = self.run(self.base, "A", on_base, trace=self.on_base)
        if on_base:
            reverse = list(reversed(on_base))
            self.a2 = self.run(
                self.base,
                "A2",
                reverse,
                hash_seed=OTHER_HASH_SEED,
                seed=OTHER_SEED,
                trace=self.on_base,
            )
        if on_head:
            self.h = self.run(self.head, "H", on_head, map_tests=True, trace=self.on_head)
            self.result.head_map = test_map(self.h.results, self.resolvers[1])

    def rerun(self, flips: list[str]) -> dict[str, tuple[list[str | None], list[str | None]]]:
        """Each flip's outcomes when run again, on base and on head."""
        again: dict[str, tuple[list[str | None], list[str | None]]] = {t: ([], []) for t in flips}
        for attempt in range(1, RERUNS + 1) if flips else ():
            on_base = self.run(self.base, f"rerun {attempt}", flips)
            on_head = self.run(self.head, f"rerun {attempt}", flips)
            for test in flips:
                again[test][0].append(_outcome(on_base, test))
                again[test][1].append(_outcome(on_head, test))
        return again

    def classify(
        self, chosen: list[str], on_base: set[str], on_head: set[str], modified: set[str],
        changes: Sequence[SymbolChange],
    ) -> tuple[OutcomeDiff, ...]:  # fmt: skip
        flips = [
            t
            for t in chosen
            if is_flip(
                _outcome(self.a, t),
                _outcome(self.a2, t),
                _outcome(self.h, t),
                modified=t in modified,
            )
        ]
        again = self.rerun(flips)
        changed = {i for c in changes for i in (base_id(c), head_id(c)) if i}
        base_ran, head_ran = self.result.base_map.ran, self.result.head_map.ran
        diffs = []
        for test in chosen:
            a, h = _outcome(self.a, test), _outcome(self.h, test)
            if (test in on_base and a is None) or (test in on_head and h is None):
                continue  # a run that did not report it: a missing item, not an outcome
            ran = (base_ran.get(test, frozenset()) | head_ran.get(test, frozenset())) & changed
            reruns = again.get(test, ([], []))
            diffs.append(
                classify(
                    test,
                    base=a if test in on_base else None,
                    base_again=_outcome(self.a2, test),
                    head=h if test in on_head else None,
                    modified=test in modified,
                    base_reruns=reruns[0],
                    head_reruns=reruns[1],
                    ran_changed_code=bool(ran),
                    base_message=_message(self.a, test),
                    head_message=_message(self.h, test),
                )
            )
        return tuple(diffs)

    def base_tests_on_head(self, edited: list[str]) -> list[TestChange]:
        """The base version of each edited test, against head's code: a failure where it passed
        on base is a regression the edit hid (ARCHITECTURE §4.2)."""
        if not edited or self.a is None:
            return []
        files = sorted({_file(test) for test in edited})
        directory = self.head.overlay(OVERLAY, self.resolvers[0].read(files))
        done = self.run(self.head, "base tests on head", edited, directory=directory)
        found = []
        for test in edited:
            before, after = _outcome(self.a, test), _outcome(done, test)
            if before is not None and after is not None and passes(before) and not passes(after):
                detail = f"base's version passes on base, {after} on head"
                found.append(TestChange(_file(test), test, "base_test_fails_on_head", detail))
        return found


def reproduce(
    sides: tuple[Side, Side],
    changes: Sequence[SymbolChange],
    graphs: tuple[ImportGraph, ImportGraph],
    resolvers: tuple[Resolver, Resolver],
    *,
    cache: MapCache | None = None,
    cache_key: str | None = None,
    observe: Observe | None = None,
    on_selected: Callable[[tuple[Selected, ...]], None] | None = None,
    stop: Callable[[], bool] | None = None,
    trace: TracePlan | None = None,
) -> TwoSided:
    """Runs the steps of the module's docstring on ``sides`` (base, head) and classifies what
    they found. ``observe`` sees each run as it ends (A once the tests are selected), and
    ``on_selected`` the selection; ``trace`` is what A, A2 and H trace."""
    steps = _Reproduction(sides, resolvers, observe, stop, trace)
    result = steps.result
    full = steps.map_base(cache, cache_key)
    listed = steps.run(steps.head, "head tests", collect_only=True)
    result.head_tests = test_map(listed.results, resolvers[1])
    result.selected = select(changes, result.base_map, result.head_tests, graphs)
    if on_selected is not None:
        on_selected(result.selected)
    chosen = [s.test for s in result.selected]
    wanted = set(chosen)  # run in collection order, so only A2 changes the order
    on_base = [t for t in result.base_map.tests if t in wanted]
    on_head = [t for t in result.head_tests.tests if t in wanted]
    steps.run_selected(full, on_base, on_head)
    modified = {s.test for s in result.selected if "modified_test" in s.reasons}
    result.outcomes = steps.classify(chosen, set(on_base), set(on_head), modified, changes)
    found = test_changes(changes, result.base_map, result.head_tests, resolvers)
    found += steps.base_tests_on_head(sorted(modified & set(on_base)))
    result.test_changes = tuple(found)
    result.gaps = uncovered(changes, result.selected, result.base_map, result.head_map)
    return result

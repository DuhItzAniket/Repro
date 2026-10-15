"""Behaviour differences (E04): calls that behave differently on head for the same input,
classified, reproduced and turned into evidence (ARCHITECTURE §4.5).

**Classes** (the schema's ``BehaviourChange``), from the fields E03 compares once the noise is
masked:

- ``exception_added`` / ``exception_removed``: it returned on one side and raised on the other;
- ``exception_changed``: it raised on both, another exception (type, arguments or cause);
- ``result_changed``: it returned on both, another value or type, or other yields;
- ``order_only``: the same value, with some dictionary in another order;
- ``input_mutated``: the same arguments went in, and were left in another state;
- ``calls_changed``: in the same test it was called with arguments seen on one side only.

A call can be in two classes (another result *and* its input mutated). Differences are
grouped by (test, function, class): one evidence item and one ``diff.behaviour`` each, with the
number of calls and the first as its reproducer.

**Reproducers.** The tests with differences run once more on each side, traced, asking for
previews of each group's first call (``run_tests(previews=...)``): the reproducer is that test,
the call, and what each side gave. A difference that does not come back the same way on both
sides was not stable after all: its evidence is ``unstable``, which ADR-0015 §3 leaves
unassessed. Every behaviour difference is a ``warn`` check (ADR-0015 §2): the change may have
meant it, which only the PR's claims can say.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from repro import __version__
from repro.ids import new_evidence_id
from repro.runner.observations import (
    CALL,
    FIELDS,
    Behaviour,
    Compared,
    Key,
    Observation,
    RunObservations,
    StabilityLabel,
    observe,
)
from repro.runner.pytest import TraceTarget
from repro.runner.sides import Side
from repro.runner.trace import TracePlan

#: The classes, in the order a group's evidence is listed.
CHANGES: Final = (
    "exception_added",
    "exception_removed",
    "exception_changed",
    "result_changed",
    "order_only",
    "input_mutated",
    "calls_changed",
)
#: Groups itemised as evidence in one run, at most (all are in ``obs/behaviour.cbor``).
MAX_GROUPS: Final = 200
SUMMARY: Final = 1000
_RESULT: Final = frozenset({"type", "value", "yields"})


def classes(item: Compared) -> list[str]:
    """The classes of one compared call's differences (none if nothing stable differs)."""
    fields = set(item.differs)
    if not fields:
        return []
    if CALL in fields:
        return ["calls_changed"]
    base, head = item.base, item.head
    if base is None or head is None:  # pragma: no cover - a one-sided call differs in CALL
        return []
    found: list[str] = []
    if "outcome" in fields:
        if base.outcome == "return" and head.outcome == "raise":
            found.append("exception_added")
        elif base.outcome == "raise" and head.outcome == "return":
            found.append("exception_removed")
        else:  # a generator that now ends early, or late
            found.append("result_changed")
    elif base.outcome == "raise":
        if fields & (_RESULT | {"order"}):
            found.append("exception_changed")
    elif fields & _RESULT:
        found.append("result_changed")
    elif "order" in fields:
        found.append("order_only")
    if "mutation" in fields:
        found.append("input_mutated")
    return found


@dataclass
class Difference:
    """The calls of one function in one test that differ the same way."""

    test: str
    symbol: str
    change: str
    calls: list[Compared] = field(default_factory=list)
    test_modified: bool = False
    #: The first call as the reproducer run saw it, on each side (None: not seen there).
    base_again: Observation | None = None
    head_again: Observation | None = None
    #: Whether that run gave the same as A and H: None if it did not report the test.
    reproduced: bool | None = None

    @property
    def first(self) -> Compared:
        return self.calls[0]

    @property
    def stability(self) -> StabilityLabel:
        if self.reproduced is False:
            return "unstable"
        return "n/a" if self.first.stability == "n/a" else "stable"

    # -- what it says -----------------------------------------------------------------------

    def previews(self) -> tuple[str | None, str | None]:
        """What each side gave, as the reproducer run showed it (``diff.behaviour``)."""
        return _shown(self.base_again, self.change), _shown(self.head_again, self.change)

    def call_text(self) -> str:
        seen = self.head_again or self.base_again
        if seen is not None and seen.args_preview:
            return seen.args_preview
        name = self.symbol.partition(":")[2].rpartition("#")[0]
        return f"{name}(… arguments {self.first.key[3][:12]})"

    def summary(self) -> str:
        base, head = self.previews()
        call = self.call_text()
        count = len(self.calls)
        where = f"in {self.test}" + (f", {count} calls" if count > 1 else "")
        if self.change == "calls_changed":
            side = "head" if self.first.base is None else "base"
            on_head = sum(1 for c in self.calls if c.base is None)
            on_base = count - on_head
            text = f"{call} is called on {side} only (in {self.test}" + (
                f"; calls on one side: {on_head} head, {on_base} base)" if count > 1 else ")"
            )
        elif self.change == "input_mutated":
            after = f"head {head or '?'}; base {base or '?'}"
            text = f"{call} leaves its arguments in another state: {after} ({where})"
        else:
            verb = {
                "exception_added": "now raises",
                "exception_removed": "no longer raises",
                "exception_changed": "raises another exception",
                "result_changed": "gives another result",
                "order_only": "gives the same entries in another order",
            }[self.change]
            text = f"{call} {verb}: head {head or '?'}, base {base or '?'} ({where})"
        return text if len(text) <= SUMMARY else text[: SUMMARY - 1] + "…"

    def evidence(self, run_id: str, artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """The ``behaviour_diff`` evidence record (the writer adds ``seq``)."""
        test, phase, symbol, args, occurrence = self.first.key
        base, head = self.previews()
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "behaviour_diff",
            "targets": [{"symbol": symbol, "test": test}],
            "summary": self.summary(),
            "data": {
                "change": self.change,
                "calls": len(self.calls),
                "test_modified": self.test_modified,
                "first": {
                    "phase": phase,
                    "args": args,
                    "occurrence": occurrence,
                    "base": _side(self.first.base),
                    "head": _side(self.first.head),
                    "differs": list(self.first.differs),
                },
                "reproducer": {
                    "test": test,
                    "command": f"python -m pytest {test}",
                    "call": self.call_text(),
                    "base": base,
                    "head": head,
                    "reproduced": self.reproduced,
                },
            },
            "artifacts": [dict(ref) for ref in artifacts],
            "stability": self.stability,
            "origin": "introduced",
            "produced_by": {"component": "repro.runner.behaviour", "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        """The ``diff.behaviour`` payload."""
        base, head = self.previews()
        return {
            "evidence_id": evidence_id,
            "symbol_id": self.symbol,
            "test": self.test,
            "change": self.change,
            "stability": self.stability,
            "base_preview": base,
            "head_preview": head,
        }

    def missing(self) -> dict[str, Any]:
        """The ``unstable_observation`` item of a difference that did not come back."""
        detail = (
            f"{self.symbol} in {self.test}: {self.change.replace('_', ' ')} on the first run, "
            "not the same when run again; not evidence"
        )
        return {
            "missing": {
                "reason": "unstable_observation",
                "targets": [{"symbol": self.symbol}, {"test": self.test}],
                "detail": detail[:1000],
                "resolution": "Make the function independent of time, randomness and hashing",
            }
        }


def _side(seen: Observation | None) -> dict[str, Any] | None:
    if seen is None:
        return None
    return {
        "outcome": seen.outcome,
        "type": seen.type,
        "result": seen.result or None,
        "any_order": seen.any_order,
        "args_after": seen.after,
    }


def _shown(seen: Observation | None, change: str) -> str | None:
    """What a side gave, for a class: its arguments afterwards, the call, or its result."""
    if seen is None:
        return None
    if change == "input_mutated":  # the arguments afterwards, where the call changed them
        return seen.after_preview if seen.after is not None else "unchanged"
    if change == "calls_changed":
        return seen.args_preview
    if seen.outcome == "raise":
        return f"raises {seen.result_preview}" if seen.result_preview else f"raises {seen.type}"
    return seen.result_preview


def differences(behaviour: Behaviour, modified: frozenset[str] = frozenset()) -> list[Difference]:
    """The comparison's differences, grouped by (test, function, class); ``modified`` names
    the tests the change edited (their calls may differ because the test does)."""
    groups: dict[tuple[str, str, str], Difference] = {}
    for item in behaviour.compared:
        test, _, symbol, _, _ = item.key
        for change in classes(item):
            group = groups.get((test, symbol, change))
            if group is None:
                group = Difference(test, symbol, change, test_modified=test in modified)
                groups[(test, symbol, change)] = group
            group.calls.append(item)
    order = {change: i for i, change in enumerate(CHANGES)}
    return sorted(groups.values(), key=lambda d: (d.symbol, d.test, order[d.change]))


# -- reproducers ---------------------------------------------------------------------------------


@dataclass
class Reproduction:
    """The reproducer runs: what each side gave when the tests ran again."""

    base: RunObservations | None
    head: RunObservations | None


def reproduce(
    found: Sequence[Difference],
    sides: tuple[Side, Side],
    plan: TracePlan,
    *,
    stop: Callable[[], bool] | None = None,
    timeout_s: float | None = None,
) -> Reproduction:
    """Runs the tests of ``found`` once more on each side, with previews of each group's first
    call, and records on each group what came back (``Difference.reproduced``)."""
    if not found:
        return Reproduction(None, None)
    tests = sorted({d.test for d in found})
    runs: list[RunObservations | None] = []
    for side, names in ((sides[0], plan.base), (sides[1], plan.head)):
        wanted = _wanted(found, names)
        done = side.run(tests, trace=list(names), previews=wanted, stop=stop, timeout_s=timeout_s)
        runs.append(observe(f"{side.name}_again", side.name, done.results, names))
    base, head = runs
    for difference in found:
        _check(difference, base, head)
    return Reproduction(base, head)


def _wanted(
    found: Sequence[Difference], names: Mapping[TraceTarget, str]
) -> list[tuple[str, TraceTarget, str]]:
    targets: dict[str, list[TraceTarget]] = defaultdict(list)
    for target, symbol in names.items():
        targets[symbol].append(target)
    wanted = {
        (d.test, target, d.first.key[3]) for d in found for target in targets.get(d.symbol, ())
    }
    return sorted(wanted)


def _check(
    difference: Difference, base: RunObservations | None, head: RunObservations | None
) -> None:
    key: Key = difference.first.key
    if base is None or head is None or key[0] not in base.tests or key[0] not in head.tests:
        difference.reproduced = None
        return
    difference.base_again = base.calls.get(key)
    difference.head_again = head.calls.get(key)
    difference.reproduced = _same(difference.first.base, difference.base_again) and _same(
        difference.first.head, difference.head_again
    )


def _same(first: Observation | None, again: Observation | None) -> bool:
    """Whether a call came back as it was (absent both times counts: a one-sided call)."""
    if first is None or again is None:
        return first is None and again is None
    return all(first.compare(again, name) is not False for name in FIELDS)

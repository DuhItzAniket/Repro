"""Behaviour observations (E03): what each traced run saw, joined across runs, with the noise
told apart from the change (ARCHITECTURE §4.3).

**Observations and their keys.** A traced run's calls (E01, digests by E02) become observations
keyed by ``(test, phase, symbol, args, occurrence)``: the test and its phase, the changed symbol
(the same ID on both sides of the change), the arguments' digest, and which call with those
arguments it was (0 for the first). The same test calling the same function with the same
arguments on base and on head is then the same key, whatever else it called in between. A call
whose arguments could not be encoded completely has no key (a truncated encoding is never equal
to anything, E02): its (test, phase, symbol) is not comparable.

**Stability.** A (base) and A2 (base again: tests in reverse order, another ``PYTHONHASHSEED``
and another ``REPRO_SEED``) run the same code, so whatever differs between them is not the
change:

- a field of a call (``outcome``, ``type``, ``value``: the result with every dictionary sorted,
  ``order``: the result as it was, ``yields``, ``mutation``: the arguments' state when the call
  ended) that differs is *unstable* for that call;
- a (test, phase, symbol) whose calls differ (arguments that are not the same in both runs,
  another number of calls) has an unstable *call set*.

Unstable parts are masked from the A vs H comparison and listed as ``unstable_observation``; a
field that cannot be compared (an incomplete encoding) is listed as ``encoding_failed``; a call
of a test A2 did not report has no stability (``n/a``). What remains are the candidate
behaviour differences E04 classifies.

**Artifacts.** Each traced run's observations, and the comparison, are written as deterministic
CBOR (``repro.store.cbor``), so the same observations are always the same bytes.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from repro.runner.pytest import PytestRun, TraceCall, TraceTarget
from repro.runner.selection import test_modules
from repro.runner.trace import TracePlan
from repro.runner.twosided import TRACED_RUNS, TwoSided
from repro.store import cbor

#: The fields of a call compared across runs, in this order.
FIELDS: Final = ("outcome", "type", "value", "order", "yields", "mutation")
#: A call's whole presence, when it is made on one side only.
CALL: Final = "call"
SUSPENDED: Final = "suspended"
UNFINISHED: Final = "unfinished"
OBSERVATIONS_FORMAT: Final = "repro.observations/1"
BEHAVIOUR_FORMAT: Final = "repro.behaviour/1"
#: Targets named one by one in a missing item, at most.
LISTED: Final = 5

Key = tuple[str, str, str, str, int]  # test, phase, symbol, arguments' digest, occurrence
Group = tuple[str, str, str]  # test, phase, symbol
StabilityLabel = Literal["stable", "unstable", "n/a"]


@dataclass(frozen=True, slots=True)
class Observation:
    """One call of a changed function, as one run saw it."""

    key: Key
    index: int  # its order among the function's calls in the test
    outcome: str
    type: str
    result: str  # the digest keeping dictionaries' order ("" when there is none)
    result_complete: bool
    any_order: str | None  # the digest with dictionaries sorted, where it differs
    yields: tuple[str, ...]
    yields_complete: bool
    #: The arguments' digest when the call ended, where they changed in place (E04).
    after: str | None = None
    after_complete: bool = True
    #: Previews (only in a run that asked for them): the call, its result, its arguments after.
    args_preview: str | None = None
    result_preview: str | None = None
    after_preview: str | None = None

    @property
    def group(self) -> Group:
        return self.key[0], self.key[1], self.key[2]

    def compare(self, other: "Observation", name: str) -> bool | None:
        """Whether ``name`` is the same in both calls; None if it cannot be told: an encoding
        is incomplete, or a call was cut off by its budget (``unfinished``)."""
        if UNFINISHED in (self.outcome, other.outcome):
            return None
        if name in ("value", "order"):
            return self._same_result(other, ordered=name == "order")
        mine, theirs = self._field(name), other._field(name)
        if not mine[1] or not theirs[1]:
            return None
        return bool(mine[0] == theirs[0])

    def _field(self, name: str) -> tuple[object, bool]:
        """A field's value and whether it is complete."""
        if name == "yields":
            return self.yields, self.yields_complete
        if name == "mutation":  # the arguments' state when the call ended (None: unchanged)
            return self.after, self.after_complete
        return getattr(self, name), True  # outcome, type

    def _same_result(self, other: "Observation", *, ordered: bool) -> bool | None:
        if SUSPENDED in (self.outcome, other.outcome):
            return True  # no result to compare: the outcome tells the calls apart
        if not self.result_complete or not other.result_complete:
            return None
        if ordered:
            return self.result == other.result
        return (self.any_order or self.result) == (other.any_order or other.result)


@dataclass
class RunObservations:
    """Every observation of one traced run."""

    label: str  # "A", "A2", "H"
    side: str  # "base" or "head"
    calls: dict[Key, Observation] = field(default_factory=dict)
    #: The tests the run reported: a test with no calls in it made none.
    tests: frozenset[str] = frozenset()
    #: Calls whose arguments could not be encoded completely, per (test, phase, symbol).
    unkeyed: Counter[Group] = field(default_factory=Counter)
    #: (test, symbol) pairs whose budget ran out: later calls were not recorded.
    truncated: frozenset[tuple[str, str]] = frozenset()
    #: Why part of the trace is missing altogether (its file reached its limit).
    cut: str | None = None

    def groups(self) -> dict[Group, set[Key]]:
        found: dict[Group, set[Key]] = defaultdict(set)
        for key in self.calls:
            found[(key[0], key[1], key[2])].add(key)
        return found


def observe(
    label: str, side: str, run: PytestRun, names: Mapping[TraceTarget, str]
) -> RunObservations:
    """``run``'s calls as observations; ``names`` gives each traced target's symbol."""
    result = RunObservations(label, side, tests=frozenset(run.tests), cut=run.trace_cut)
    ordered = sorted(
        (call for call in run.calls if call.target in names),
        key=lambda call: (call.test, call.target, call.index),
    )
    seen: Counter[tuple[str, str, str, str]] = Counter()
    for call in ordered:
        symbol = names[call.target]
        if not call.args_complete:
            result.unkeyed[(call.test, call.phase, symbol)] += 1
            continue
        base = (call.test, call.phase, symbol, call.args)
        key: Key = (*base, seen[base])
        seen[base] += 1
        result.calls[key] = _observation(key, call)
    result.truncated = frozenset(
        (test, names[target]) for test, target in run.truncated if target in names
    )
    return result


def _observation(key: Key, call: TraceCall) -> Observation:
    return Observation(
        key=key,
        index=call.index,
        outcome=call.outcome,
        type=call.type,
        result=call.result,
        result_complete=call.result_complete,
        any_order=call.result_any_order,
        yields=call.yields,
        yields_complete=call.yields_complete,
        after=call.args_after,
        after_complete=call.args_after_complete,
        args_preview=call.args_preview,
        result_preview=call.result_preview,
        after_preview=call.args_after_preview,
    )


@dataclass(frozen=True, slots=True)
class Stability:
    """What differs between two runs of the same code (A and A2)."""

    #: The tests both runs reported: only their calls have a stability.
    tests: frozenset[str]
    #: Per call seen in both runs: the fields that differ between them.
    unstable: Mapping[Key, frozenset[str]]
    #: Per call seen in both runs: the fields that could not be compared.
    unknown: Mapping[Key, frozenset[str]]
    #: (test, phase, symbol) whose calls are not the same in both runs.
    groups: frozenset[Group]


def stability(first: RunObservations, again: RunObservations) -> Stability:
    tests = first.tests & again.tests
    unstable: dict[Key, frozenset[str]] = {}
    unknown: dict[Key, frozenset[str]] = {}
    groups: set[Group] = set()
    mine, theirs = first.groups(), again.groups()
    for group in mine.keys() | theirs.keys() | first.unkeyed.keys() | again.unkeyed.keys():
        if group[0] not in tests:
            continue
        keys, other = mine.get(group, set()), theirs.get(group, set())
        if keys != other or first.unkeyed[group] != again.unkeyed[group]:
            groups.add(group)
        for key in keys & other:
            a, b = first.calls[key], again.calls[key]
            verdicts = {name: a.compare(b, name) for name in FIELDS}
            differing = frozenset(n for n, same in verdicts.items() if same is False)
            missing = frozenset(n for n, same in verdicts.items() if same is None)
            if differing:
                unstable[key] = differing
            if missing:
                unknown[key] = missing
    return Stability(frozenset(tests), unstable, unknown, frozenset(groups))


@dataclass(frozen=True, slots=True)
class Compared:
    """One key of a test run on both sides: base's and head's call, and what differs."""

    key: Key
    base: Observation | None
    head: Observation | None
    #: Fields that differ and are neither unstable nor unknown (``call``: made on one side).
    differs: tuple[str, ...]
    #: Fields masked because they differ between A and A2.
    unstable: tuple[str, ...]
    #: Fields that could not be compared (an incomplete encoding, a spent budget).
    unknown: tuple[str, ...]
    stability: StabilityLabel


@dataclass
class Behaviour:
    """The traced runs and their comparison: the input of E04's behaviour diffs."""

    runs: dict[str, RunObservations]
    stability: Stability
    compared: tuple[Compared, ...]
    #: Calls whose arguments could not be encoded, on base and on head, per (test, phase,
    #: symbol).
    unkeyed: Mapping[Group, tuple[int, int]] = field(default_factory=dict)
    #: Changed functions not traced at all (more than one run can trace).
    left_out: tuple[str, ...] = ()
    #: What was traced, test code left out (the reproducer runs trace the same, E04).
    plan: TracePlan | None = None

    def differences(self) -> list[Compared]:
        """The candidate behaviour differences: what differs once the noise is masked."""
        return [c for c in self.compared if c.differs]

    def counts(self) -> dict[str, int]:
        return {
            "calls": len(self.compared),
            "same": sum(1 for c in self.compared if not (c.differs or c.unstable or c.unknown)),
            "unstable": sum(1 for c in self.compared if c.stability == "unstable"),
            "unknown": sum(1 for c in self.compared if c.unknown),
            "differences": len(self.differences()),
        }


def compare(base: RunObservations, again: RunObservations, head: RunObservations) -> Behaviour:
    """A against H, for the tests both reported, with A vs A2's noise masked."""
    measured = stability(base, again)
    tests = base.tests & head.tests
    mine, theirs = base.groups(), head.groups()
    compared: list[Compared] = []
    unkeyed: dict[Group, tuple[int, int]] = {}
    for group in sorted(mine.keys() | theirs.keys() | base.unkeyed.keys() | head.unkeyed.keys()):
        test, _, symbol = group
        if test not in tests:
            continue
        if base.unkeyed[group] or head.unkeyed[group]:
            unkeyed[group] = (base.unkeyed[group], head.unkeyed[group])
        cut = (test, symbol) in base.truncated or (test, symbol) in head.truncated
        noisy_group = group in measured.groups
        compared.extend(
            _compared(key, (base, again, head), measured, cut=cut, noisy=noisy_group)
            for key in sorted(mine.get(group, set()) | theirs.get(group, set()))
        )
    return Behaviour(
        {run.label: run for run in (base, again, head)},
        measured,
        tuple(compared),
        unkeyed,
    )


def _compared(
    key: Key,
    runs: tuple[RunObservations, RunObservations, RunObservations],
    measured: Stability,
    *,
    cut: bool,
    noisy: bool,
) -> Compared:
    base, again, head = runs
    before, after = base.calls.get(key), head.calls.get(key)
    label: StabilityLabel = "n/a" if key[0] not in measured.tests else "stable"
    unstable = set(measured.unstable.get(key, frozenset()))
    unknown = set(measured.unknown.get(key, frozenset()))
    # A call A2 did not make, in a call set that differs between A and A2: none of its fields
    # can be shown stable, so whatever differs in it is masked with the noise.
    unproven = noisy and label == "stable" and key not in again.calls
    differs: list[str] = []
    if before is None or after is None:
        if noisy:
            unstable.add(CALL)
        elif cut:
            unknown.add(CALL)
        else:
            differs.append(CALL)
    else:
        for name in FIELDS:
            same = before.compare(after, name)
            if same is None:
                unknown.add(name)
            elif same or name in unstable or name in unknown:
                continue
            elif unproven:
                unstable.add(name)
            else:
                differs.append(name)
    if noisy or unstable:
        label = "unstable" if label == "stable" else label
    return Compared(
        key,
        before,
        after,
        tuple(differs),
        tuple(n for n in (*FIELDS, CALL) if n in unstable),
        tuple(n for n in (*FIELDS, CALL) if n in unknown),
        label,
    )


def behaviour_of(result: TwoSided) -> Behaviour | None:
    """A, A2 and H of a two-sided run, observed and compared (None: nothing was traced, or one
    of them did not run). Test code is left out, as ``selection.uncovered`` leaves it."""
    traced = result.traced()
    if result.trace is None or set(traced) != set(TRACED_RUNS):
        return None
    plan = result.trace.without_test_code(test_modules(result.base_map, result.head_tests))
    names = {"A": plan.base, "A2": plan.base, "H": plan.head}
    base, again, head = (
        observe(label, traced[label].side, traced[label].run.results, names[label])
        for label in TRACED_RUNS
    )
    behaviour = compare(base, again, head)
    behaviour.left_out = plan.left_out
    behaviour.plan = plan
    return behaviour


# -- missing items -------------------------------------------------------------------------------


def missing(behaviour: Behaviour) -> list[dict[str, Any]]:
    """``missing.recorded`` payloads: noise masked from the comparison and what could not be
    compared (per symbol), then traces cut short and functions not traced."""
    return _masked(behaviour) + _untraced(behaviour)


def _masked(behaviour: Behaviour) -> list[dict[str, Any]]:
    noisy: dict[str, list[Compared]] = defaultdict(list)
    unknown: dict[str, list[Compared]] = defaultdict(list)
    for item in behaviour.compared:
        if item.unstable:
            noisy[item.key[2]].append(item)
        if item.unknown:
            unknown[item.key[2]].append(item)
    items: list[dict[str, Any]] = []
    for symbol, found in sorted(noisy.items()):
        fields = sorted({name for item in found for name in item.unstable})
        tests = sorted({item.key[0] for item in found})
        detail = (
            f"{len(found)} calls of {symbol} in {_counted(tests, 'test')} differ between two "
            f"runs of base ({', '.join(fields)}); not compared with head"
        )
        resolution = "Make the function independent of time, randomness and hashing"
        items.append(_missing("unstable_observation", detail, symbol, tests, resolution))
    for symbol, found in sorted(unknown.items()):
        fields = sorted({name for item in found for name in item.unknown})
        tests = sorted({item.key[0] for item in found})
        detail = (
            f"{len(found)} calls of {symbol} in {_counted(tests, 'test')} could not be "
            f"compared ({', '.join(fields)}): an incomplete encoding or a spent budget"
        )
        items.append(_missing("encoding_failed", detail, symbol, tests, None))
    unkeyed: dict[str, set[str]] = defaultdict(set)
    for (test, _, symbol), counts in behaviour.unkeyed.items():
        if any(counts):
            unkeyed[symbol].add(test)
    for symbol, tested in sorted(unkeyed.items()):
        tests = sorted(tested)
        detail = (
            f"calls of {symbol} in {_counted(tests, 'test')} have arguments that could not be "
            "encoded completely: they were not compared"
        )
        items.append(_missing("encoding_failed", detail, symbol, tests, None))
    return items


def _untraced(behaviour: Behaviour) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for run in behaviour.runs.values():
        if run.cut is not None:
            detail = f"{run.side} ({run.label}): {run.cut}; later calls were not recorded"
            items.append(_missing("trace_truncated", detail, None, [], None))
    for label in ("A", "H"):  # A2 runs what A runs
        run = behaviour.runs[label]
        for symbol in sorted({symbol for _, symbol in run.truncated}):
            tests = sorted(test for test, s in run.truncated if s == symbol)
            detail = (
                f"{run.side}: calls of {symbol} past the budget were not recorded, in "
                f"{_counted(tests, 'test')}"
            )
            items.append(_missing("trace_truncated", detail, symbol, tests, None))
    if behaviour.left_out:
        shown = ", ".join(behaviour.left_out[:LISTED])
        more = len(behaviour.left_out) - LISTED
        detail = f"more changed functions than one run can trace: {shown}" + (
            f" and {more} more" if more > 0 else ""
        )
        # Every one is a target: the status counts them as unverified (F04).
        targets = [{"symbol": symbol} for symbol in behaviour.left_out]
        items.append(
            {
                "missing": {
                    "reason": "trace_unavailable",
                    "targets": targets,
                    "detail": detail[:1000],
                    "resolution": None,
                }
            }
        )
    return items


def _counted(items: Sequence[str], noun: str) -> str:
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def _missing(
    reason: str, detail: str, symbol: str | None, tests: Iterable[str], resolution: str | None
) -> dict[str, Any]:
    targets: list[dict[str, str]] = [{"symbol": symbol}] if symbol else []
    targets += [{"test": test} for test in list(tests)[:LISTED]]
    return {
        "missing": {
            "reason": reason,
            "targets": targets,
            "detail": detail[:1000],
            "resolution": resolution,
        }
    }


# -- artifacts -----------------------------------------------------------------------------------

_CALL_FIELDS: Final = (
    "test", "phase", "symbol", "args", "occurrence", "index", "outcome", "type", "result",
    "result_complete", "any_order", "yields", "yields_complete", "after", "after_complete",
    "args_preview", "result_preview", "after_preview",
)  # fmt: skip


def _digest(text: str | None) -> bytes | None:
    return bytes.fromhex(text) if text else None


def _text(data: Any) -> str:
    if data is None:
        return ""
    if not isinstance(data, bytes):
        raise cbor.CBORError("a digest that is not bytes")
    return data.hex()


def dump_observations(run: RunObservations) -> bytes:
    """``run`` as a deterministic CBOR document (``OBSERVATIONS_FORMAT``)."""
    tests = sorted(run.tests | {key[0] for key in run.calls} | {g[0] for g in run.unkeyed})
    symbols = sorted(
        {key[2] for key in run.calls} | {g[2] for g in run.unkeyed} | {s for _, s in run.truncated}
    )
    test_at = {test: i for i, test in enumerate(tests)}
    symbol_at = {symbol: i for i, symbol in enumerate(symbols)}
    calls = [
        [
            test_at[o.key[0]],
            o.key[1],
            symbol_at[o.key[2]],
            _digest(o.key[3]),
            o.key[4],
            o.index,
            o.outcome,
            o.type,
            _digest(o.result),
            o.result_complete,
            _digest(o.any_order),
            [_digest(y) for y in o.yields],
            o.yields_complete,
            _digest(o.after),
            o.after_complete,
            o.args_preview,
            o.result_preview,
            o.after_preview,
        ]
        for _, o in sorted(run.calls.items())
    ]
    return cbor.encode(
        {
            "format": OBSERVATIONS_FORMAT,
            "run": run.label,
            "side": run.side,
            "tests": tests,
            "reported": sorted(test_at[t] for t in run.tests),
            "symbols": symbols,
            "fields": list(_CALL_FIELDS),
            "calls": calls,
            "unkeyed": [
                [test_at[t], phase, symbol_at[s], n]
                for (t, phase, s), n in sorted(run.unkeyed.items())
            ],
            "truncated": sorted([test_at[t], symbol_at[s]] for t, s in run.truncated),
            "cut": run.cut,
        }
    )


def load_observations(data: bytes) -> RunObservations:
    """A document of ``dump_observations`` back; ``CBORError`` if it is not one."""
    document = cbor.decode(data)
    try:
        if document["format"] != OBSERVATIONS_FORMAT or document["fields"] != list(_CALL_FIELDS):
            raise cbor.CBORError(f"not {OBSERVATIONS_FORMAT}")
        tests, symbols = document["tests"], document["symbols"]
        run = RunObservations(
            str(document["run"]),
            str(document["side"]),
            tests=frozenset(tests[i] for i in document["reported"]),
            cut=document["cut"],
        )
        for row in document["calls"]:
            (test, phase, symbol, args, occurrence, index, outcome, kind, result, complete,
             any_order, yields, yields_complete, after, after_complete, args_preview,
             result_preview, after_preview) = row  # fmt: skip
            key: Key = (tests[test], phase, symbols[symbol], _text(args), occurrence)
            run.calls[key] = Observation(
                key, index, outcome, kind, _text(result), complete,
                _text(any_order) or None, tuple(_text(y) for y in yields), yields_complete,
                _text(after) or None, after_complete, args_preview, result_preview,
                after_preview,
            )  # fmt: skip
        for test, phase, symbol, count in document["unkeyed"]:
            run.unkeyed[(tests[test], phase, symbols[symbol])] = count
        run.truncated = frozenset((tests[t], symbols[s]) for t, s in document["truncated"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise cbor.CBORError(f"not {OBSERVATIONS_FORMAT}: {exc}") from exc
    return run


def dump_behaviour(behaviour: Behaviour, artifacts: Mapping[str, Mapping[str, Any]]) -> bytes:
    """The comparison (``BEHAVIOUR_FORMAT``): each key, where it was seen, its stability and what
    differs, with the observation artifacts it was made from (``artifacts``: run → reference)."""
    keys = [item.key for item in behaviour.compared]
    tests = sorted({key[0] for key in keys})
    symbols = sorted({key[2] for key in keys})
    test_at = {test: i for i, test in enumerate(tests)}
    symbol_at = {symbol: i for i, symbol in enumerate(symbols)}
    rows = [
        [
            test_at[c.key[0]],
            c.key[1],
            symbol_at[c.key[2]],
            _digest(c.key[3]),
            c.key[4],
            c.base is not None,
            c.head is not None,
            c.stability,
            list(c.differs),
            list(c.unstable),
            list(c.unknown),
        ]
        for c in behaviour.compared
    ]
    return cbor.encode(
        {
            "format": BEHAVIOUR_FORMAT,
            "observations": {label: dict(ref) for label, ref in sorted(artifacts.items())},
            "tests": tests,
            "symbols": symbols,
            "fields": [
                "test",
                "phase",
                "symbol",
                "args",
                "occurrence",
                "on_base",
                "on_head",
                "stability",
                "differs",
                "unstable",
                "unknown",
            ],
            "compared": rows,
            "counts": behaviour.counts(),
        }
    )

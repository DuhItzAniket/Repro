"""JavaScript and TypeScript: function-level traces of a change, compared base against head
(K07; ADR-0017, phase 3).

**What is traced.** The functions a change edits (``jsmap.changed``), by name in their file.
A runtime (``_hook/repro_trace_js.cjs``, ``repro_encode``'s rules ported) wraps them and
records each call in the current test: the arguments' digest, how it ended and the result's
digest, in the records Python's tracer writes (``runner.pytest``), so the same comparison reads
them.
- **Vitest:** a Vite plugin (``_hook/repro_trace_vite.mjs``) wraps them in place, last of the
  transforms. Calls from inside the module are traced too.
- **Jest:** its setup file mocks each planned module by its own exports, wrapped. Jest runs
  modules in a registry of its own, so a call from inside the module is not traced, and the
  summary says so.

ADR-0017 had planned a Node ``load`` hook. Neither runner loads the project's modules through
Node's loader: Vitest evaluates what Vite transformed, and Jest evaluates modules in its own
``vm`` contexts. Each runner's own transform point is used instead.

**The comparison** is E03's: base runs twice (A, then A2 in shuffled order: Vitest's
``--sequence.shuffle``, Jest's ``--randomize``, the same seed each time) and head once (H). What
differs between A and A2 is noise and masked. A call whose arguments could not be encoded is
matched by its position. What remains are E04's behaviour differences. The first calls of each
function in each test carry previews (``SAMPLES``): they stand in for a reproducer run.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final, Literal

from repro.jsmap import JsChange
from repro.runner.behaviour import Difference, differences
from repro.runner.observations import Behaviour, RunObservations, compare, observe
from repro.runner.pytest import TestResult, TraceTarget, read_results

TRACE_FILE: Final = "repro-calls.jsonl"
#: Each (test, function)'s first calls previewed.
SAMPLES: Final = 20
#: A2's order: shuffled, the same way each time.
SEED: Final = "1"
Runner = Literal["vitest", "jest"]


def plan(changes: Sequence[JsChange]) -> dict[str, list[str]]:
    """The functions to trace, by file: the changed ones."""
    return {c.file: sorted(c.functions) for c in changes if c.functions}


def targets(traced: Mapping[str, Sequence[str]]) -> dict[TraceTarget, str]:
    """Each traced function's target, as the runtime names it, and its symbol."""
    return {
        (file, name, 1, 1): f"{file}:{name}" for file, names in traced.items() for name in names
    }


def shuffled(runner: Runner) -> list[str]:
    """The runner's arguments for A2: the tests in another order, the same each time."""
    if runner == "vitest":
        return ["--sequence.shuffle", f"--sequence.seed={SEED}"]
    return ["--randomize", f"--seed={SEED}"]


def observed(
    label: str,
    side: str,
    outcomes: Mapping[str, str],
    calls: bytes,
    names: Mapping[TraceTarget, str],
) -> RunObservations:
    """One traced run's calls as observations, its tests as the runner reported them."""
    run = read_results(b"", calls)  # no pytest results: only the trace (None would skip it)
    tests = {test: TestResult(test, outcome, 0.0, None, None) for test, outcome in outcomes.items()}  # type: ignore[arg-type]
    return observe(label, side, replace(run, tests=tests), names)


def behaviour(
    runs: Sequence[tuple[Mapping[str, str], bytes]],
    names: Mapping[TraceTarget, str],
) -> tuple[Behaviour, list[Difference]]:
    """A, A2 and H, each (outcomes, trace), compared: the behaviour and its differences, each
    showing the values its own traced calls previewed."""
    (a, a_calls), (a2, a2_calls), (h, h_calls) = runs
    found = compare(
        observed("A", "base", a, a_calls, names),
        observed("A2", "base", a2, a2_calls, names),
        observed("H", "head", h, h_calls, names),
    )
    listed = differences(found)
    for difference in listed:
        difference.base_again = difference.first.base
        difference.head_again = difference.first.head
    return found, listed


def summary(found: Behaviour, listed: Sequence[Difference]) -> dict[str, object]:
    """What ``repro js-run`` reports of the behaviour: the counts, and each difference."""
    return {
        "counts": found.counts(),
        "differences": [
            {
                "function": difference.symbol,
                "test": difference.test,
                "change": difference.change,
                "stability": difference.stability,
                "summary": difference.summary(),
            }
            for difference in listed
        ],
    }

# E04 — Behaviour diff engine & reproducers

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | E03 |
| **Branch / PR** | `phase/E04-behaviour-diff` · [#49](https://github.com/DuhItzAniket/Repro/pull/49) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Turn what E03's comparison finds into evidence a reviewer can act on: each difference
classified (another result, an exception added, removed or changed, an input mutated, an order
changed, other calls), confirmed by running its test again, and shown with a reproducer: the
test, the call and what each side gave. A change that alters behaviour no test checks is then
caught without a failing test.

## Scope
- **Input mutation in the tracer.** A call's arguments are kept from PY_START and encoded again
  when it ends; `args_after` is recorded where they changed in place. Calls whose arguments are
  all immutable scalars skip the second encoding. E03's comparison gains the `mutation` field.
- **Previews on request.** `run_tests(previews=...)` names calls (test, target, arguments'
  digest); for those the tracer records the call (`name=value, ...`), its result or exception,
  and its arguments afterwards, as previews (E02's `preview`, 512 characters at most).
- **Classes** (`repro.runner.behaviour.classes`): `exception_added`, `exception_removed`,
  `exception_changed`, `result_changed`, `order_only`, `input_mutated`, and a new
  `calls_changed` (called with arguments seen on one side only).
- **Groups**: one per (test, function, class), with its calls; the first is its reproducer.
  At most 200 groups are itemised per run (all are in `obs/behaviour.cbor`).
- **Reproducers**: the tests with differences run again on each side with previews of each
  group's first call; a group whose call does not come back the same on both sides is
  `unstable` (and an `unstable_observation` item).
- **Evidence and events**: `behaviour_diff` evidence (class, call count, the first call's
  digests and what differs, the reproducer, whether the test was edited, the comparison
  artifact) and a `diff.behaviour` per group, `warn` (ADR-0015 §2).
- **Fixtures** `silent-change` (an output no test checks) and `false-claim` ("no behaviour
  change", and an input mutated); the other fixtures' expectations list their differences.
- **Gate D's browser test** counts the behaviour checks its two branches now produce.

## Out of scope
- Judging whether a difference was intended (Stage G's reviewers, from the PR's claims);
  generated inputs (E06); the cockpit's behaviour field from real samples (E07).

## Design notes
- **One class per kind of difference, several per call.** A call that returns another value and
  also mutates its input is in two groups: they need different explanations.
- **`calls_changed` is new in the schema.** A function called with other arguments on one side
  (a caller changed, or the test was edited) is a behaviour difference the six classes did not
  cover; it is an additive enum value (`BehaviourChange`), not a change of core fields.
- **Reproduced, not assumed.** A difference comes with a second run of its test on both sides:
  the reproducer is what that run showed, and a difference that does not come back is not
  evidence (unstable, unassessed). Only the named calls leave the sandbox as text; everything
  else stays digests.
- **Arguments looked at twice only when they can change.** Numbers, strings, bytes and `None`
  cannot change in place, so calls with only those skip the second encoding.
- **Edited tests are marked.** A difference in a test the change edited may come from the edit
  (`test_modified` in the evidence's data), which the reviewers weigh.

## Acceptance criteria
- [x] AC1 (roadmap): the `silent-change` and `false-claim` fixtures produce the expected stable
  diffs with working reproducers.
- [x] AC2: every difference is `behaviour_diff` evidence with a `diff.behaviour` check (`warn`),
  schema-valid, through `repro run`.
- [x] AC3: the tracer's overhead stays within E01's check with the mutation check on.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_fixtures_give_stable_reproduced_diffs[silent-change, false-claim]`: the classes and tests listed in each fixture's TOML, stable, reproduced, with the expected previews; `test_input_mutation_and_previews` (tracer, real sandbox) |
| AC2 | `test_run_stage.py` over every fixture (evidence names, cited checks, `warn`); `test_behaviour.py` (each class, groups, schema validation, unstable when not reproduced); Gate D's browser test |
| AC3 | `scripts/bench_tracer.py` on 3.12–3.15 |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.runner.behaviour`: `classes`, `differences`, `Difference` (summary, evidence,
  `diff.behaviour` payload, missing item), `reproduce`.
- Tracer: `args_after` (arguments encoded again when a call ends), previews of the calls named
  in `REPRO_PREVIEW_CALLS`; `run_tests(previews=...)`; `TraceCall` and `Observation` fields.
- E03's comparison: the `mutation` field; the stored observations carry it and the previews.
- Schema: `BehaviourChange` gains `calls_changed` (TS and Pydantic regenerated).
- The `behaviour` job: reproducer runs, `behaviour_diff` evidence citing `obs/behaviour.cbor`,
  `diff.behaviour` checks, the reproducer runs' observations stored (`obs/base_again.cbor`,
  `obs/head_again.cbor`).
- Fixtures `silent-change`, `false-claim`; the `behaviour_diff` items of `honest-fix`,
  `selection`, `breaks-one` and `test-tamper`; Gate D's spec counts the new checks.
- Tests: `test_behaviour.py`, `test_input_mutation_and_previews`, both fixtures in
  `test_twosided.py` and `test_run_stage.py`. pytest 1224 → 1248 (1236 pass and 12 skip on Windows with Docker Desktop stopped).

## Evidence
Every fixture's behaviour differences, through `reproduce` and the reproducer runs (Windows,
Python 3.13); each was reproduced on both sides:

| Fixture | Difference (test) | Reproducer: base → head |
|---|---|---|
| `silent-change` | `result_changed` `to_celsius` (`test_describe_mentions_celsius`) | `to_celsius(fahrenheit=100)`: `37.8` → `38` |
| | `result_changed` `to_celsius` (`test_freezing`) | `to_celsius(fahrenheit=32)`: `0.0` → `0` |
| `false-claim` | `input_mutated` `restock` (`test_restock_adds`) | `restock(levels={'a': 1}, sku='a', amount=2)`: unchanged → `levels={'a': 3}, …` |
| `honest-fix` | `result_changed` `parse_date` (both tests: naive → UTC-aware datetimes) | `datetime.datetime(2026-03-29T02:30:00)` → `…T01:30:00+00:00)` |
| `breaks-one` | `result_changed` `discount` (`test_discount`) | `discount(amount=50, percent=10)`: `45.0` → `5.0` |
| `test-tamper` | `result_changed` `divide`; `exception_changed` `divide` (`ZeroDivisionError('division by zero')` → `('integer division or modulo by zero')`); `calls_changed` `divide`, `percent` (the edited tests no longer call them) | |
| `selection` | `calls_changed` `Cart.names` (the edited test fills the cart differently) | |
| `noisy`, `flaky`, `perf-regress`, `untested` | none | |

- AC1: `silent-change` changes no test outcome (all P2P) and gives two stable, reproduced
  `result_changed` differences; `false-claim`'s "no behaviour change" meets a stable,
  reproduced `input_mutated`, while its other rewrite (`unique_skus`) gives none.
- AC2: through `repro run`, every difference arrived as `behaviour_diff` evidence cited by a
  `warn` `diff.behaviour`, in a schema-valid log, for all six fixtures run end to end. Gate D
  in Edge (local, process sandbox): `breaks-one` 2 checks, both flagged (the P2F and the
  unexplained `discount` difference); `test-tamper` 8 flagged, 2 unassessed, 1 passed.
- AC3, the tracer with the mutation check (commit `3336feb`, 8 rounds, BCa 95 %):

| Python | `fib(28)` | 40,000 records | 1,000,000 small calls |
|---|---|---|---|
| 3.12.13 | 1.21× (1.13–1.27) | 1.20× (1.12–1.24) | 1.15× (1.09–1.19) |
| 3.13.13 | 1.09× (1.03–1.13) | 1.24× (1.17–1.35) | 1.05× (0.99–1.11) |
| 3.14.4 | 1.10× (1.05–1.16) | 1.19× (1.14–1.24) | 1.09× (1.03–1.13) |
| 3.15.0 | 1.10× (1.04–1.18) | 1.22× (1.17–1.28) | 1.11× (1.04–1.17) |

  No interval lies above 1.20×. The mutation check costs the dict-heavy records test about
  five points (1.14–1.18× at E02, 1.19–1.24× now): its argument, a dictionary, is encoded
  twice per call. `fib` and the small calls, whose arguments are numbers, skip it.
- CI run: linked in the PR (#49).

## Deviations from spec
- The schema's `BehaviourChange` gains `calls_changed` (additive): one-sided calls had no class.
- ARCHITECTURE §4.5's reproducer is "test node ID plus encoded args preview"; E04's also holds
  what each side gave, from a second run, and says whether it came back the same.
- Differences are itemised per (test, function, class), at most 200 a run, rather than per call;
  every call is in `obs/behaviour.cbor`.

## Known gaps
- A difference whose reproducer run did not report its test keeps `reproduced: null` (its
  stability from A and A2 stands).
- Arguments mutated through an object the encoder sees as opaque (its own `__dict__`
  descriptor, E02) are not seen to change.
- The cockpit's behaviour field still lights from `trace.sample` events, which the engine does
  not emit yet (E07); the `diff.behaviour` checks already reach the index and Change routes.

## Dependencies added
None.

## Research notes
- ARCHITECTURE §4.5 (behaviour differ, reproducers); ADR-0015 §2–3 (status of a
  `diff.behaviour`, unassessed when unstable).

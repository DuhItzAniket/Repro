# E04 — Behaviour diff engine & reproducers

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | in progress |
| **Depends on** | E03 |
| **Branch / PR** | `phase/E04-behaviour-diff` · PR pending |
| **Started / finished** | 2026-10-15 / — |

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
- [ ] AC1 (roadmap): the `silent-change` and `false-claim` fixtures produce the expected stable
  diffs with working reproducers.
- [ ] AC2: every difference is `behaviour_diff` evidence with a `diff.behaviour` check (`warn`),
  schema-valid, through `repro run`.
- [ ] AC3: the tracer's overhead stays within E01's check with the mutation check on.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_fixtures_give_stable_reproduced_diffs[silent-change, false-claim]`: the classes and tests listed in each fixture's TOML, stable, reproduced, with the expected previews; `test_input_mutation_and_previews` (tracer, real sandbox) |
| AC2 | `test_run_stage.py` over every fixture (evidence names, cited checks, `warn`); `test_behaviour.py` (each class, groups, schema validation, unstable when not reproduced); Gate D's browser test |
| AC3 | `scripts/bench_tracer.py` on 3.12–3.15 |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- ARCHITECTURE §4.5 (behaviour differ, reproducers); ADR-0015 §2–3 (status of a
  `diff.behaviour`, unassessed when unstable).

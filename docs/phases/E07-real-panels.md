# E07 — Real-data panels & Gate E scenario

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | in progress |
| **Depends on** | E04, E05 |
| **Branch / PR** | `phase/E07-real-panels` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Drive the cockpit's behaviour field and Signals from what a real run observes, and prove
Stage E's gate in the browser: a change that alters an output no test checks is seen as a stable
behaviour diff with its reproducer, and the noise of the A/A′ control is not.

## Scope
- **Samples in the tracer**: with `REPRO_TRACE_SAMPLES=n` (`run_tests(samples=n)`), each
  (test, target)'s first `n` calls are previewed (the call, its result or exception); A, A′ and
  H trace with `n = 4`.
- **`trace.sample` events** (`repro.runner.trace.samples`): one per previewed call of A
  (`base`), A′ (`base_repeat`) and H (`head`), emitted as each run ends, test code left out, at
  most 2,000 a run.
- **Test hook**: the summary gains the behaviour field's cells, the Signals series and the
  `diff.behaviour` checks (their previews).
- **Gate E's browser test** (`apps/web/gate/gate-e.spec.ts`) and its CI job (`gate E`, Docker).
- `run_tests` builds a traced run's files and variables in one place (`_tracing`).

## Out of scope
- The card itself (Stage F); reviewer verdicts (Stage G); the focus view's text for behaviour
  evidence (unchanged).

## Design notes
- **Samples are previews, bounded.** Four calls per test and function, on three runs: enough
  for the field's cells (it caps brightness at four samples) and Signals' drift series, without
  sending every value of a run out of the sandbox as text.
- **The panels' rules, the engine's verdicts.** The field already compares samples side by
  side and lets `diff.behaviour` win (DESIGN.md panel 4); with real samples it lights during the
  run and settles on the engine's checks.
- **Test code stays out of the field.** A run's own collected test files and `conftest.py`
  are left out of its samples, as the comparison leaves them out (E03).

## Acceptance criteria
- [ ] AC1 (roadmap): the Gate E scenario passes end to end in the cockpit.
- [ ] AC2: the behaviour field and Signals are fed by the run's `trace.sample` events, schema-
  valid, through `repro run`.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `gate-e.spec.ts`: `silent-change` (no test fails on any side; two stable `result_changed` diffs, base `37.8` / head `38` and `0.0` / `0`; the field's `to_celsius` cells differ; drift has points; the two checks flagged) and `noisy` (no `diff.behaviour`; the time, random and set-order cells unstable, `total` the same, no cell differing) |
| AC2 | `test_samples_preview_each_tests_first_calls` (real sandbox); `test_samples_for_the_cockpit`; `test_run_stage.py`'s logs validated against the schema |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- DESIGN.md panels 4 (behaviour field) and 6 (Signals); ARCHITECTURE §5.2 (`trace.sample`).

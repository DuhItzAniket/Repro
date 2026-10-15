# E07 — Real-data panels & Gate E scenario

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | E04, E05 |
| **Branch / PR** | `phase/E07-real-panels` · [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

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
- [x] AC1 (roadmap): the Gate E scenario passes end to end in the cockpit.
- [x] AC2: the behaviour field and Signals are fed by the run's `trace.sample` events, schema-
  valid, through `repro run`.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `gate-e.spec.ts`: `silent-change` (no test fails on any side; two stable `result_changed` diffs, base `37.8` / head `38` and `0.0` / `0`; the field's `to_celsius` cells differ; drift has points; the two checks flagged) and `noisy` (no `diff.behaviour`; the time, random and set-order cells unstable, `total` the same, no cell differing) |
| AC2 | `test_samples_preview_each_tests_first_calls` (real sandbox); `test_samples_for_the_cockpit`; `test_run_stage.py`'s logs validated against the schema |

---
*Filled in at the end of the phase:*

## What shipped
- Tracer: `samples` (`REPRO_TRACE_SAMPLES`); `run_tests(samples=...)` and `_tracing`;
  `twosided.SAMPLES` (4) for A, A′ and H.
- `repro.runner.trace.samples`, `MAX_SAMPLES`; `trace.sample` events from the tests job.
- Test hook: `panels.behaviour`, `panels.signals`, `behaviourDiffs`.
- `apps/web/gate/gate-e.spec.ts`; the `gate E` CI job (Docker).
- Tests: `test_samples_preview_each_tests_first_calls`, `test_samples_for_the_cockpit`, two
  test-hook cases. pytest 1295 → 1297 (1285 pass and 12 skip on Windows with Docker Desktop
  stopped); Vitest `@repro/web` 296 → 298.

## Evidence
Gate E's browser test, Windows, Edge, process sandbox (local):

| Scenario | Result |
|---|---|
| `silent-change` (57 s) | no test failed on BASE, A′ or HEAD; two `diff.behaviour` checks, both `result_changed` and `stable`, with their reproducers' values: `test_describe_mentions_celsius` base `37.8`, head `38`; `test_freezing` base `0.0`, head `0`; the behaviour field's two `to_celsius` cells differ; Signals' DRIFT has points and ends at `1.00`; the index flags the two checks ("4 checks / 2 passed / 2 flagged") |
| `noisy` (57 s) | no test failed; no `diff.behaviour`; the `stamp`, `roll` and `fruit` cells unstable, `total` the same, no cell differing; DRIFT ends at `0.00`; "5 checks / 5 passed / 0 flagged" |

- Both screenshots were checked by eye: on `silent-change` the HEAD cells glow in the flag
  colour and Change routes reads "to_celsius 2 tests 2 flagged".
- Gate D still passes with the samples (`breaks-one` 38 s, `test-tamper` 51 s, the same run).
- The first Gate E run found the spec looking for a "BEHAVIOUR DRIFT" series; the panel labels
  it "DRIFT" (DESIGN.md's name for the signal is BEHAVIOUR DRIFT), fixed in the spec.
- CI run: linked in the PR (#52).

## Deviations from spec
- The roadmap names Execution among the real-data panels: it has drawn real test events since
  D06, so E07 changes nothing in it; the behaviour field and Signals' drift were the panels
  still waiting for real samples.

## Known gaps
- Samples show the first four calls of each function per test: a difference only in later
  calls lights its cell when the engine's `diff.behaviour` arrives, not before.
- A function whose noise is only in its arguments (`since`, called with the time) can show as
  the same in the field when its results agree: the samples are matched by call position; its
  masked call set is listed as a missing item, not as a cell state.

## Dependencies added
None.

## Research notes
- DESIGN.md panels 4 (behaviour field) and 6 (Signals); ARCHITECTURE §5.2 (`trace.sample`).

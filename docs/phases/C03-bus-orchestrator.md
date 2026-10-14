# C03 — Event bus & orchestrator

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | done |
| **Depends on** | C02 |
| **Branch / PR** | `phase/C03-bus-orchestrator` · [#31](https://github.com/DuhItzAniket/Repro/pull/31) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
A run is a DAG of jobs that the orchestrator schedules, times out and cancels, and everything it
does reaches the store as validated events through one bus. Whatever happens, a run ends with
`run.finished`, and whatever could not be done is on record as a failed event and a missing item.

## Scope
- **Bus** (`repro.bus`, ARCHITECTURE §5): builds each event's envelope (ULID, timestamp, `v`,
  the kind's `pv`, `producer`), scrubs known secret formats from the payload and target, validates
  the complete event against its kind's generated model (payload and stage), and submits it to
  the store's writer, the only code that assigns `seq`. After each commit it fans the events out
  to subscribers (C04's WebSocket clients), which must not block.
- **Secret scrubbing** (defence in depth, ARCHITECTURE §5.3): GitHub tokens (`ghp_`,
  `github_pat_`, `gho_`, `ghu_`, `ghs_`, `ghr_`), AWS access key IDs (`AKIA`, `ASIA`), PEM private
  key blocks and `Bearer` credentials become `[redacted]`.
- **Orchestrator** (`repro.orchestrator`): a run's jobs form a DAG (`needs`); each job belongs
  to one of the seven stages.
  - Jobs run on daemon threads, at most `concurrency` at once, as soon as their dependencies
    succeed. A job whose dependency did not succeed is skipped.
  - Every job has a timeout. A job still running at its deadline is abandoned (its context is
    cancelled and closed, so it can emit nothing more) and recorded as timed out.
  - `cancel()` stops the run: running jobs see their context cancelled, pending ones never
    start, and the run ends `cancelled`.
  - A job that fails emits a `log.line` with status `fail` and a `missing.recorded` item for what
    it would have verified; a skipped job records its missing item too; a timeout's reason is
    `timeout`.
  - `stage.started` and `stage.finished` frame each stage's jobs (`fail` if one failed or timed
    out, `warn` if one was skipped).
  - **`run.finished` is guaranteed**: it is emitted in a `finally`, with the outcome
    (`completed`, `failed`, `cancelled`), the duration and the counts, and the run registry and
    a WAL checkpoint follow.
  - A job context offers `emit` and a cancellable, timed `run` for subprocesses that kills the
    process tree on timeout or cancellation.

## Out of scope
- Real pipeline jobs (snapshots C05, analysis C06–C07, execution in Stage D); the API (C04).
- The card and its status (`card_status` stays `null` until F05).

## Design notes
- Validation uses the generated Pydantic models (`repro_events.models.EVENT_ADAPTER`), not the
  JSON Schema files, so an installed engine needs no schema directory at runtime; the drift gate
  keeps the models equal to the schema.
- Threads cannot be killed, so timeouts and cancellation are cooperative inside Python and
  forceful for subprocesses. Daemon threads keep an abandoned job from blocking the process exit.

## Acceptance criteria
- [x] AC1 (roadmap): golden-log test of a stub pipeline.
- [x] AC2 (roadmap): a cancelled run ends cleanly with a final event.
- [x] AC3: a failing, timing-out or skipped job yields `status: fail` events and missing items,
      and the run still ends with `run.finished`.
- [x] AC4: every emitted event is valid for its kind, carries no recognised secret, and
      subscribers see events only after they are committed, in `seq` order.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_orchestrator.py::test_stub_pipeline_matches_its_golden_log` (normalised, schema-validated) |
| AC2 | `test_orchestrator.py`: cancel during a running job and before jobs start |
| AC3 | `test_orchestrator.py`: failure, timeout, skipped dependants, an exception inside the orchestrator |
| AC4 | `test_bus.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/bus.py`, `scrub.py`, and `orchestrator/` (`jobs.py`, `runner.py`).
- Tests: `test_bus.py` (28), `test_orchestrator.py` (18); golden log
  `engine/tests/golden/stub-pipeline.jsonl`. pytest 667 → 713 (712 pass and 1 skips on Windows).

## Evidence
- The stub pipeline's golden log (20 events): a failing job, a job that overruns its 0.2 s
  timeout while ignoring cancellation, a skipped dependant and two clean jobs. It passes the
  schema and log invariants (`validate_log`), is identical over five consecutive runs, and the
  abandoned job's late `log.line` never reaches the store.
- Cancellation: a run cancelled while its job waits ends `cancelled` in well under a second; one
  running a tool that started a grandchild kills the whole tree and ends within the test's 15 s
  bound (a surviving grandchild would hold the pipes open and stall it).
- CI run: linked in the PR.

## Deviations from spec
- None.

## Known gaps
- A job that ignores cancellation keeps its thread until it returns (threads cannot be killed);
  it is abandoned and closed, so it can no longer emit. Real jobs run tools through `ctx.run`,
  which is killed on time.
- On Windows the tool tree is killed with `taskkill /T`; Job Objects arrive with the sandbox (D).
- The bus validates with the generated models; the JSON Schema itself is checked by the drift gate
  and by `validate_log` in tests.

## Dependencies added
None.

## Research notes

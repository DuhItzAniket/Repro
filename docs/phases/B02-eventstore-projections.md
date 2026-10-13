# B02 — EventStore, projections, snapshots & clock

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B01 |
| **Branch / PR** | `phase/B02-eventstore-projections` · [#11](https://github.com/DuhItzAniket/Repro/pull/11) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
The cockpit's data layer: any moment of a run can be turned into exact UI state, cheaply and
deterministically, from the event log alone.

## Scope
- `EventStore`: typed-array columns plus the parsed events, gap and duplicate handling,
  envelope-version check, tolerant of unknown kinds.
- `Folder`: snapshots every N events, `stateAt(cursor)` and `sync()`, with sequential reuse and
  error isolation.
- `WindowIndex` (time windows) and `KindIndex` (per-kind prefixes).
- `PresentationClock`: replay at four speeds, live mode, pause, seek, end-of-data handling.
- Projections: `run`, `summary`, `checks` (ADR-0015), `claims`, `agents`, combined into one
  cockpit projection. Selectors `headerCounters`, `indexFooter`, `indexFooterText` and
  `stageProgress`. A `CockpitModel` façade. `parseJsonl`.

## Out of scope
- Panel-specific view models (execution lanes, behaviour grid, routes, signals): B08/B09, on
  top of these projections and indexes.
- Transient visuals (streaks, bundles): B05–B07 use `WindowIndex`.
- Transport (WebSocket replay-then-live): C08.

## Design notes
- **Folded vs indexed state.** Small state that changes in place is folded and snapshotted:
  counters, stages, the check model, claims, agents. Append-only collections (the feed,
  waveform samples, graph tables) need no snapshots: `KindIndex.count/last(kind, cursor)` gives
  any prefix with a binary search. This keeps snapshots small (72 for the 18.5k-event stress
  log).
- **Mutable reducers with clone-on-snapshot.** `apply` may mutate and return the state.
  Snapshots use `structuredClone` (Maps and Sets included) unless a projection supplies
  `clone`. `stateAt` returns a folder-owned object that is valid until the next call. That is
  what lets sequential playback fold only new events.
- **Presentation time** is the running maximum of `ts - ts₀`. A backwards timestamp, which the
  validator only warns about, can therefore never break `cursorAt(t)` or window queries.
- **Gaps stop ingestion.** A projection fold over a log with a hole would be silently wrong, so
  the store returns `{ status: "gap", expected }` and the transport (C08) resyncs. Duplicates
  are ignored, which handles the WebSocket replay/live overlap.
- **Tolerance.** An unknown kind, or a known kind with `pv` newer than this build supports, is
  stored and indexed as `unknown` but never passed to projections. An envelope version other
  than 1 is rejected. A projection that throws on an event is isolated: the error is recorded
  once per `seq` and folding continues.
- **Check model.** `checks` implements ADR-0015 exactly. Header counters and the index footer
  read the **same `counts` object**. ADR-0015 gained one precision: review closes at the review
  stage's end, or at the card stage or run end when a run has no review stage (contradiction
  outweighs support).
- **Clock semantics.** Replay never runs past the data. It waits at the end and re-anchors, so
  newly arrived data does not make it jump. Live runs at ×1 from the newest event. Pausing live
  drops to a ×1 replay behind the edge, and `goLive` catches up. Wall time is injected.
- `Projection.apply` takes a third argument `{ index, time }` and has an optional `clone`. The
  interface sketch in IMPLEMENTATION_PLAN §5 is updated accordingly.

## Acceptance criteria
- [x] AC1: Property tests: `fold(all) == fold(snapshot_k) + rest` for any k (fast-check, 60
      cases), and random-seek equality with a linear fold for any snapshot interval (1–700)
      and any order of calls (40 cases × up to 12 seeks).
- [x] AC2: Header counters and the index footer come from one projection. The test asserts
      `indexFooter(state) === state.checks.counts` and agreement at **every** cursor of the demo
      run, plus `passed + flagged + unassessed + pending = checks`, and that CHECKS and FLAGGED
      never decrease.
- [x] AC3: Unknown kinds are tolerated: unknown kinds and newer `pv` are stored, indexed as
      unknown, skipped by projections, and leave the counters and verdicts unchanged.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `folder.test.ts`: "fold(all) == …", "random seeks equal a linear fold …" |
| AC2 | `cockpit.test.ts`: "header counters and index footer read one projection …" |
| AC3 | `store.test.ts` "keeps unknown kinds …"; `cockpit.test.ts` "ignores unknown kinds …" |

---

## What shipped
- `apps/web/src/model/`: `codes.ts`, `store.ts`, `window.ts`, `projection.ts`, `folder.ts`,
  `clock.ts`, `jsonl.ts`, `cockpit.ts`, `projections/{run,summary,checks,claims,agents}.ts`.
- `apps/web/README.md`.

## Evidence
- Tests: web 35 (store 7, folder 6, cockpit 7, clock 8, window 4, jsonl 2, app 1). The final
  demo state equals the B01 generator's recounted plan: 4 claims, 12 agents, 147 files, and
  28 / 20 / 4 / 4 / 0 checks / passed / flagged / unassessed / pending. Verdicts, agreement,
  rejections and sandboxes are checked too.
- Measured (Windows dev box, Node 25.9.0, inside Vitest, 5 repetitions, stress fixture of
  18,542 events):

  | Step | Time |
  |---|---|
  | JSONL parse | 22–28 ms |
  | Ingest and fold (72 snapshots) | 26–47 ms |
  | Random `stateAt` | 0.22–0.28 ms on average |
  | Sequential step of 30 events | about 5 µs |

  Indicative only; B04 measures in the browser on a mid laptop.
- CI run: see the PR checks.

## Deviations from spec
- None in scope. The `Projection` interface gained `meta` and `clone` (recorded in
  IMPLEMENTATION_PLAN §5).

## Known gaps
- `structuredClone` snapshots copy the `files` set (2,000 entries in stress) every 256 events.
  That is cheap at these sizes. If B04 profiling disagrees, a prefix index can replace it.
- Live mode's handling of clock skew between engine and browser is left to C08, which has a
  real engine to measure against.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| `@repro/events` (workspace) | — | Apache-2.0 | Event types and the kind registry at runtime |
| `@repro/synth` (workspace, dev) | — | Apache-2.0 | Fixtures generated in tests |
| fast-check (dev) | 4.10.2 | MIT | Property tests (already pinned in the workspace) |
| @types/node (dev) | 24.19.2 | MIT | Tests read fixture files (already pinned) |

## Research notes
None beyond B01's: the projection implements ADR-0015 as logged.

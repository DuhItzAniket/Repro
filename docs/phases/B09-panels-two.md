# B09 — Panels II: change routes, signals, dispatch, change×check index

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B08 |
| **Branch / PR** | `phase/B09-panels-two` · [#20](https://github.com/DuhItzAniket/Repro/pull/20) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
The second row of panels: change routes, signals, agents / dispatch, and the change×check
index. With them, all eight panels draw from the event store. The index, its footer and the
header counters count one list of checks.

## Scope
- `model/changes.ts`: `ChangeIndex` (changed symbols, test selections, routes between them),
  synced by `CockpitModel`.
- `model/check-index.ts`: the change×check index selector (rows, relations, row status), plus
  the route and relation helpers the routes panel shares.
- `panels/routes.ts`, `signals.ts`, `dispatch.ts`, `check-index.ts`, wired into the shell (all
  eight panels are now canvases).
- `PanelHost`: clears the whole backing store in device pixels and clamps canvas sides to
  4,096 CSS px.
- `projections/checks.ts` exports `CHECK_KINDS`.

## Design notes
- **Routes.** A selected test routes to a changed symbol when it was selected for it, when one
  of its selected symbols calls it within 3 `calls` hops, or, for a module-level change, when the
  test's module imports the changed module. Selections by `module_import` name no symbols. Two
  demo examples:
  - `test_fold_resolution` reaches the unclaimed `_fold_offset` through
    `get_zone → resolve_fold → _fold_offset`;
  - `test_format_date_locale` reaches `fmt:<module>` through its module's import.

  Each selection is routed with the graph edges and changes that precede it in the log. That is
  what the engine knew when it selected the test, and it makes routes pure in the cursor. A test
  ingests the log in 97-event chunks, querying routes after each chunk, and gets the same routes
  as one ingestion.
- **Index rows and relations** (DESIGN.md panel 8, noted in ADR-0015 §4).
  - Rows are the claims, then changed symbols no claim covers (grouped by file), then "other".
    A claim covers the symbols it targets, and a file-only target covers the whole file.
  - A check that names a symbol relates only to rows covering that symbol. A first version also
    matched behaviour diffs by their test, which put `parse_date`'s diff on the `_split_iso` row.
  - Other checks relate through a file target or a routed test. A claim also relates to every
    check whose evidence its verdict cites, so C4 (deps, supported) shows the failed
    no-new-dependencies invariant that cites the same evidence.
  - Status: a claim is flagged if contradicted or any related check is flagged, verified if
    supported with nothing pending, otherwise review. An unclaimed change is never verified.
- **Index columns** are the checks projection's list, in arrival order. When checks outnumber
  the columns that fit (3 px pitch), each column covers a contiguous run of checks and shows the
  most urgent related result (flagged > pending > unassessed > passed).
- **Route steps.** FILE (changed) → SYMBOL (tests selected) → TEST (fills as route tests finish
  on HEAD) → CHECK (fills as related checks resolve). The current step is a pill with a white
  underline while in progress, as in the reference.
- **Signals.**
  - PASS RATE: the last 8 HEAD finishes.
  - DRIFT: the last 16 stable base/head sample pairs; pairs with A ≠ A′ are left out.
  - PERF Δ: head/base − 1 per repetition.
  - Ticks mark the checks that resolve each signal, at the data point they are about. A first
    version put them at the check events (~35 s), far right of the 23–27 s series, which squeezed
    the series into the left 40% of the axis.
- **Dispatch.** Working, waiting, done or flagged (the agent failed or contradicted a claim).
  Tool names drop the `mcp__<server>__` prefix.
- **Dense rows.** Routes and index rows shrink with the panel, down to a 9 px and 7 px pitch,
  with whole-pixel text. At 1440×900 all 7 routes and all 9 index rows fit in an 83 px canvas.

## Acceptance criteria
- [x] AC1 (as B08): each panel is a pure `draw(ctx, view, size, t)` that redraws only when its
      version changes. In the browser (demo, `clearRect` per canvas over 2 s):

      | Window | Frames | Routes | Signals | Dispatch | Index |
      |---|---|---|---|---|---|
      | ×1 from 23.4 s (tests and traces) | 120 | 39 | 86 | 5 | 1 |
      | Paused | 119 | 0 | 0 | 0 | 0 |
      | ×1 from 10 s (graph, 7 `symbol.changed`) | 120 | 8 | 1 | 1 | 8 |
      | ×1 from 33 s (diff and review) | 121 | 3 | 1 | 13 | 3 |

      Cost per redraw on a real canvas (stress run, 981 playback cursors × 2, after warm-up):

      | Panel | p50 (ms) | p95 (ms) | max (ms) |
      |---|---|---|---|
      | Index | 0.1 | 0.5 | 1.1 |
      | Routes | 0.1 | 0.3 | 1.3 |
      | Signals | 0 | 0.2 | 0.5 |
      | Dispatch | 0 | 0.1 | 1.7 |

      The B08 panels measured the same way: execution p95 0.8 ms, the others ≤ 0.1 ms. The sum of
      all eight p95s is about 2.2 ms. `performance.now` resolution is 0.1 ms.
- [x] AC2 (as B08): view-model unit tests pass. Covered:
      - routes: steps and progress mid-run and at the end, and per-route results;
      - signals: series lengths and bounds, tick counts and placement;
      - dispatch: 12 slots, a08 flagged, the others done;
      - index: rows and statuses for the demo, citation relations, symbol-only relations, and
        the status before verdicts;
      - `columnRanges` covers every check exactly once (fast-check);
      - 611 stress checks bucket into 68 columns.
- [x] AC3 (as B08): per-panel golden draw-call recordings (`routes-26000`, `routes-final`,
      `signals-final`, `dispatch-26000`, `index-final`).
- [x] AC4: the index footer and header counters can never disagree. At every 7th cursor of the
      demo, the matrix's result counts equal `indexFooter` and `headerCounters`. The B02 test
      still checks that footer and header share one object at every cursor.
- [x] AC5: Signals shows "illustrative until run completes" while the run is partial, and no
      caption once `run.finished` arrives (app test).

## Evidence
- Tests: web 172 (+23: changes 5, check index 6, panels II 12), plus caption and canvas
  assertions in the app test.
- In the browser (1440×900):
  - the index reads C1 fix verified; C2 perf, C3 refactor and C4 deps flagged; `_split_iso`,
    `fmt.py` and `_fold_offset` review; `_by_month` flagged; other verified;
  - the routes show `format_duration` with "2 flagged" and `_fold_offset` with "2 passed";
  - with the stress run, the index buckets 611 checks.

## Deviations from spec
- None. Wording beyond DESIGN.md's panel descriptions (route steps, signal definitions, row
  rules) is recorded in DESIGN.md.

## Known gaps
- Rows past what fits collapse into "+k more". The demo fits at 1440×900; B11's focus and
  drawer give full access.
- The canvases have no semantic mirror yet. The index as a table, and keyboard focus on rows
  and cells, are B11.
- Found while measuring: clearing a canvas in CSS pixels left a sub-pixel sliver uncleared.
  It also stopped Chrome from discarding pending draw operations on an undisplayed canvas,
  which produced 15–110 ms flush spikes in the benchmark. `PanelHost` now clears in device
  pixels; the spikes disappeared (max ≤ 1.9 ms). Separately, a dev server serving a stale
  stylesheet after a `git rebase` let canvases grow through their ResizeObserver to 33,554,434
  px. That is fixed by restarting the server; `PanelHost` now clamps sides to 4,096 CSS px.

## Dependencies added
None.

## Research notes
None.

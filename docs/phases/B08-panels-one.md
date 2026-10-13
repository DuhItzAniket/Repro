# B08 — Panels I: feed, execution, agent workspace, behaviour field

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B02, B03 |
| **Branch / PR** | `phase/B08-panels-one` · PR pending |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
The first four Canvas 2D panels beneath the stage: the investigation feed, execution lanes,
the agent workspace and the behaviour diff field. Each draws only from the event store, and
only when what it would draw has changed.

## Scope
- `panels/panel.ts`: the panel contract (`version`, `view`, `draw` on a `Ctx2D` subset of
  Canvas 2D) and `PanelHost`, which sizes the canvas at the device pixel ratio (capped at 2)
  and draws only when the version changes.
- `panels/recorder.ts`: a recording `Ctx2D` that turns draw calls into text, used for golden
  tests.
- `model/runs.ts`: `TestIndex` (one entry per test run, with the store indices of its start
  and finish) and `ObservationIndex` (cells per test × symbol, one entry per trace sample).
  Both are append-only and live in `CockpitModel`.
- `styles/palette.ts`: the DESIGN.md colours for canvas code, tested against `tokens.css`.
- The four panels (`feed.ts`, `execution.ts`, `workspace.ts`, `behaviour.ts`), the execution
  BASE · HEAD · BOTH toggle (`side-toggle.tsx`), and their wiring in `main.tsx` and `app.tsx`.

## Design notes
- **Versions, not dirty flags.** `version(t, cursor)` is a number that changes whenever the
  drawing would: the count of relevant events, plus an animation phase while something moves
  (`versionOf(cursor, phase)`). Because it is a pure function of (t, cursor), a paused clock
  never redraws and a scrub redraws exactly once.
- **Feed.** The last 32 `log.line` events before the cursor, newest at the bottom in bold. The
  newest row slides in over 150 ms (DESIGN.md), quantised to 8 steps, so an insert costs at most
  8 redraws. Warnings and errors are tinted `--flag`.
- **Execution.** A running test is a short dash whose x approaches the settle line as
  1 − exp(−elapsed / 350 ms). That is a pure function of t, so scrubbing is exact. Finished runs
  settle into a grid as dots coloured by outcome. While tests run, the panel redraws at about
  30 fps. "Running" is detected from the KindIndex as more `test.started` than `test.finished`,
  so the check is O(1) per frame.
- **A′ in the BASE lane.** The repeat base run (`base_repeat`) measures noise. It shares the BASE
  lane with dimmer particles, and its counts are shown separately ("BASE · 16 run · 2 failed
  A′ · 16 run · 3 failed"). BASE and HEAD stay comparable, and no pipeline activity is hidden.
  A first version drew only `base` and `head`, so the 20 A′ runs of the demo never appeared.
- **Agent workspace.** It follows the agent with the latest `agent.state` (B11 adds pinning). It
  shows that agent's recent lines with the newest typed at 18 ms per character, as a pure
  function of time since its event. The block cursor blinks (530 ms) only while the agent is
  working. A finished agent's panel is still.
- **Behaviour field.** One cell per observed (test, symbol), sorted by module, test and symbol.
  A HEAD cell is `differs` (`--flag`) if, for some call, base and head results differ while A and
  A′ agree. It is `unstable` (`--flag-deep`, masked) if A and A′ disagree. This is the engine's
  rule (ARCHITECTURE §4.3) applied per sample, so the field lights up during tracing. An engine
  `diff.behaviour` overrides the sample rule. The histogram underneath counts `differs` cells per
  module. Dots are capped at 3 px and spread over the grid, so a small field reads as a sparse
  matrix like the reference.
- **Fonts.** Panels draw in JetBrains Mono. Each panel is invalidated once on
  `document.fonts.ready`, so text drawn before the font loads is repainted.

## Acceptance criteria
- [x] AC1: Each panel is a pure `draw(ctx, view, size, t)` that redraws only when dirty.
      `PanelHost` draws once per version and again only after a resize or invalidation (unit
      test). In the browser (demo run, every panel's `clearRect` counted over 2 s):

      | Window | Frames | Feed | Execution | Workspace | Behaviour |
      |---|---|---|---|---|---|
      | ×1 from 23.4 s (tests and traces running) | 117 | 85 | 82 | 83 | 73 |
      | Paused | 118 | 0 | 0 | 0 | 0 |
      | ×1 from 10 s (log lines only) | 118 | 71 | 1 | 1 | 1 |

      The single redraws are from the seek. Cost per redraw on a real Canvas 2D with the stress
      run (1,810 test runs, 189 trace samples; `performance.now` resolution 0.1 ms):
      execution p95 0.8 ms (max 2.0); feed, workspace and behaviour p95 ≤ 0.3 ms.
- [x] AC2: View-model unit tests pass. Covered:
      - feed rows equal the KindIndex's last 32 log lines, and the insert progress;
      - execution counts per lane, including A′, recounted independently, with particle bounds
        and the side toggle;
      - workspace focus, typing progress and the blink stopping when the agent is done;
      - behaviour cells agreeing with every engine `diff.behaviour`, the histogram sum and order,
        and growth over time.
- [x] AC3: Per-panel screenshot tests pass as golden draw-call recordings
      (`panels/__snapshots__/*.txt`). Each recording is the exact sequence of draw calls, with
      colours and alpha, for a fixed moment of the demo run. Pixel screenshots across browsers
      are B12 (Playwright with SwiftShader).

## Evidence
- Tests: web 149 (+16: palette 1, PanelHost 1, feed 3, execution 4, workspace 3, behaviour 4).
- In the browser (demo run, 1,028 × 561 viewport):
  - at 26 s the execution label reads "BASE · 16 run · 2 failed   A′ · 16 run · 3 failed" and
    "HEAD · 15 run · 1 failed";
  - the workspace shows "A04 · PROBE · CLAUDE-SONNET-5-5" typing `read_symbol(...)` calls;
  - at 32 s the behaviour field shows rose HEAD cells over a dim histogram.

## Deviations from spec
- The roadmap's `draw(ctx, view, t)` also takes the panel's CSS size: `draw(ctx, view, size, t)`.
  Without the size a panel cannot lay out, and reading it from the context would make `draw`
  depend on canvas state.
- Panel screenshots are draw-call recordings for now. Pixel screenshot comparison
  (`docs/TEST_STRATEGY.md`, layer 8: Playwright) arrives with the UI quality gate in B12.

## Known gaps
- At stress scale (about 1,200 runs per lane) the execution settle grid saturates into solid
  stripes. The counts in the lane label stay exact.
- The behaviour view rebuilds from all samples on each new sample. That is cheap for the
  fixtures (189 samples), but real runs with many thousands of samples may need an incremental
  cell-status index. Measure in Stage D, when real traces arrive.
- The feed's DOM mirror (`role="log"`, throttled) and keyboard focus of rows and cells are B11.
- Replay speeds above ×1 shorten the 150 ms insert and the typing. B10 clamps them to
  wall-clock time (ADR-0011).

## Dependencies added
None.

## Research notes
None.

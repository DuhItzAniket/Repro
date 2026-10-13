# B11 — Focus, evidence drawer & accessibility

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B10 |
| **Branch / PR** | `phase/B11-focus-a11y` · [#22](https://github.com/DuhItzAniket/Repro/pull/22) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Let the user focus anything the cockpit shows, by mouse or keyboard, and read its evidence in a
plain drawer. Make the canvases' meaning available to assistive technology.

## Scope
- `focus/focus.ts`: the focus (claim, file, symbol, check, agent), its key, and what it
  highlights on the stage.
- `focus/evidence.ts`: the drawer's content, a pure function of (focus, events up to the
  cursor).
- Stage:
  - `stage/focus-layer.ts`: outlines on ring cards, rings on web nodes, edges;
  - ring pin: `rotationAt` with a focus, plus `RingModel.cardOf`;
  - `stage/hit.ts`: what is under a click.
- Panels: `targets()` on routes, dispatch and index (rows and cells, from the same geometry the
  panels draw with). `PanelHost` outlines the selected and keyboard targets, hit-tests, and
  reports target changes. The workspace follows a focused agent.
- Shell:
  - `drawer.tsx`;
  - `mirror.tsx` (feed log, panel mirrors, file picker);
  - `announcer.ts` (throttled feed summaries);
  - a drawer rectangle in `computeLayout`;
  - landmarks; the stage's live `aria-label`.
- Contrast: `--text-dim` raised to `#868686`; faint never used for text; callout and transport
  backgrounds opaque.
- Dev dependency: `axe-core` 4.14.0.

## Design notes
- **One focus.** Focus is UI state, not an event. It reaches the stage as `StageFrame.focus`,
  so a frame is a pure function of (events, t, motion, focus). Scrubbing with a focus set
  replays exactly.
- **Ring pin.** The first focused file with a card is pinned at 3 o'clock with no drift, until
  the focus changes. The pin is instant: the closed-form rotation of event-driven snaps stays a
  function of the log, and an interaction-triggered animation would need wall-clock state
  outside it.
- **Targets share the drawing geometry.** Routes, dispatch and index compute their row and
  column layout in one function used by both `draw` and `targets`, so a click lands on what is
  drawn. Panel goldens were unchanged by the refactor. In a hit, a cell wins over its row.
- **Keyboard.**
  - Index rows, route rows and agents are visually hidden buttons. The keyboard's position is
    drawn on the canvas as a white outline, the focused row as a light fill.
  - Index cells are reached through the row's drawer, which lists the row's checks as buttons.
    This keeps the tab order short.
  - Ring files are reachable through a "Focus a file" picker that appears when it has focus.
  - The drawer takes keyboard focus on open; Escape closes it and returns focus to the opener.
- **The drawer quotes the log.**
  - Claims: verdict rationale, quotes, agreement and model.
  - Checks: evidence summaries and data, payload fields, trace samples (base, A′, head) for
    behaviour diffs, and the claims citing them.
  - Files and symbols: changes with line ranges, routed tests, related checks.
  - Agents: their state.

  "Raw diff" is shown as line ranges, because the log carries no diff text (artifacts arrive
  with the engine).
- **Screen-reader feed.** At most one summary per 2 s of wall-clock time. Each summary batches
  every line since the previous one and counts warnings. A paused clock announces nothing, and
  scrubbing back resets quietly. Entries have growing ids: a first version keyed them by
  position, so trimming the oldest of 20 would have rewritten every remaining paragraph and a
  screen reader could re-announce them. A test now pins that the kept nodes are untouched.
- **Contrast** (WCAG 1.4.3, found by axe in Chromium; jsdom cannot compute it).
  - `--text-dim` `#6e6e6e` was 3.9:1 on the background; `#868686` is at least 4.5:1 on every
    surface text sits on (`#080808`, `#121212`, `#181818`, `#1c1c1c`).
  - `--text-faint` (1.76:1) is kept for marks only; its text uses moved to dim, on the canvases
    too, where axe cannot see.
  - Callouts and the transport were translucent over the stage; over a bright streak their dim
    text fell to about 2.3–3.8:1, so they are opaque now.

## Acceptance criteria
- [x] AC1: every focus action is reachable by keyboard. Rows and agents are mirror buttons
      (Enter focuses), cells are reached through the row's drawer, files through the picker,
      and the drawer closes with Escape. In jsdom (`a11y.test.tsx`) and in the browser: Escape
      closed the drawer; a focused "C4 deps" button outlined its row on the canvas, and Enter
      opened C4's evidence.
- [x] AC2: axe-core reports no serious violations. In fact none at all:
      - jsdom, every rule but colour contrast (CI);
      - Chromium, all rules including contrast: 0 violations and 0 incomplete, with the drawer
        closed and open and two callouts on screen.

      The first Chromium run found 32 contrast violations and 2 landmark findings; all are fixed.
- [x] AC3: a screen reader announces feed summaries at the throttled rate. Unit-tested (2 s
      throttle, batching, pause, scrub back). In the browser, replay from 23 s added
      summaries 2,012 and 2,016 ms apart, e.g. "17 new lines. Latest, run: head:
      tests/test_recur.py::test_monthly_edge skipped (66 ms) (4 warnings)".
- [x] Deliverables: click and keyboard focus on rows, cells and nodes; stage highlight and ring
      pin; evidence drawer; parallel accessible DOM (log, semantic tables, labelled canvases).

## Evidence
- Tests: web 223 (+23: focus and drawer 9, stage focus 4, panel targets 4, accessibility 6).
- The panel goldens changed only by colour: normalising `#868686` to `#6e6e6e`, and faint to
  dim in text lines, leaves 0 differing lines.
- In the browser (demo, end of run):
  - C3 focused: the drawer shows the contradicted verdict, the "base → '2h 0m', head → '2h'"
    quote and C3's related checks;
  - the ring pinned `fmt.py` and the web ringed its node (163 highlight segments);
  - a canvas click on the C2 row focused C2.
- Licence check: all dependencies on the allow-list (axe-core is MPL-2.0).

## Deviations from spec
- DESIGN.md's palette was sampled from the reference; `--text-dim` is now `#868686` to meet
  WCAG AA, and `--text-faint` no longer carries text. The look is otherwise unchanged.
- The ring pin is instant rather than a 500 ms snap (see Design notes).

## Known gaps
- The card's semantic table arrives with the card view (F05).
- Keyboard users reach index cells through the row's drawer rather than arrow keys in a grid.
- The stage's `aria-label` summarises the stage; it does not enumerate nodes. The file picker
  and the drawer give full access.
- No screen reader was run here; the announcement rate is measured on the `role="log"` DOM.

## Dependencies added
- `axe-core` 4.14.0 (dev, exact pin; MPL-2.0, on the allow-list). npm registry: published
  2026-10-05. Used only in tests and manual browser audits.

## Research notes
None.

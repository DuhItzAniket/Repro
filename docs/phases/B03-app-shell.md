# B03 — App shell, tokens, fonts, header & progress

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B02 |
| **Branch / PR** | `phase/B03-app-shell` · PR link added on creation |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
The cockpit's frame: the page loads a recorded run and replays it through the B02 model. The
header counters and the 7-segment stage progress follow the event stream, inside the DESIGN.md
grid, in the project's typeface.

## Scope
- Preact 11 + signals shell (`main.tsx`, `shell/app.tsx`, `shell/header.tsx`): header (title,
  subtitle with the run label, five counters, the progress bar), stage frame, and eight panel
  frames with titles and footers.
- `computeLayout(width, height)`: every rectangle (header, stage, panels, ring) from one pure
  function, covering the desktop and narrow (< 1100 px) rules.
- `createShellView`: folded state → signals, written only on change. `FrameLoop`:
  clock → cursor → view, with per-frame listeners for the stage (B04).
- CSS tokens from DESIGN.md, and self-hosted JetBrains Mono (variable woff2). The OFL licence
  is emitted next to the font files by a small Vite plugin.
- Fixture loading (`?log=stress` selects the stress run).

## Out of scope
- Stage rendering (B04–B07), panel contents (B08/B09), transport controls and keyboard
  shortcuts (B10), focus and the evidence drawer (B11).

## Design notes
- **Geometry is code, not CSS.** The header, stage, panels and ring come from
  `computeLayout`. The DOM applies the rectangles as inline styles, and the WebGL stage (B04)
  will size its canvas from the same values. CSS styles only what sits inside the rectangles.
  Rules:
  - desktop: header 56 px, panels in about 34% of the height (2 rows × 4), stage ≥ 55%;
  - if 34% would push the stage below 55%, the panels shrink, and below 112 px rows the page
    scrolls instead;
  - narrow (< 1100 px): stage 60% (≥ 50vh) and panels in 2 columns × 4 rows of 220 px, scrolling;
  - integer pixels throughout: the last column and row absorb rounding, so edges align to the
    8 px padding exactly.
- **Re-render only on information.** The frame loop calls `view.update` only when the fold
  cursor moves, and each signal is written only when its value changes. Measured in a test: a
  full replay writes the counters signal far fewer times than it updates, and every write
  differs from the last.
- **Viewport tracking** compares the window size every frame, besides the `resize` event.
  Found while previewing: the in-app browser's device emulation changes the viewport without
  firing `resize`. Two property reads per frame cost nothing.
- **The run is labelled.** The subtitle shows the run's repo and PR (`synthetic/timekeeper
  #128`), so the demo never looks like a real repository. FLAGGED is tinted `--flag` when
  non-zero, and the label still carries the meaning, so colour is not the only carrier.
- **Font licence.** `@fontsource-variable/jetbrains-mono` 5.3.0 (OFL-1.1). The plugin copies
  the package's own `LICENSE` to `assets/JetBrainsMono-OFL.txt`, beside the woff2 files, so it
  always matches the shipped font version. Only `wght.css` (upright) is imported. Browsers fetch
  only the subsets a page uses (the latin subset, 40 KB, for this UI).

## Acceptance criteria
- [x] AC1: The layout matches DESIGN.md dimensions at 1440×900 and 1920×1080. Exact rectangles
      are asserted in `layout.test.ts`. They were also measured in the running app
      (`getBoundingClientRect`) and match:
      - 1440×900: header 0,0,1440,56; stage 0,56,1440,522 (58%); panels 350×149 at
        y = 586/743 with 8 px gaps; no scroll;
      - 1920×1080: stage 641 (59%); panels 470×179/180; last panel ends at 1912,1072 (8 px
        padding).

      A property test checks the invariants for any viewport between 320×320 and 3840×2160.
- [x] AC2: Counters update from the fixture. `view.test.ts` replays every cursor of the demo
      run: counters start at 0, never decrease, and end at 4 / 12 / 147 / 28 / 4. Stages go
      pending → active → done in order, with never two active. `frame.test.ts` plays the run
      at ×16 to the end. `app.test.tsx` (jsdom) checks the rendered counters, segments and index
      footer.
- [x] AC3: The font licence file ships with the font. `build.test.ts` runs a real production
      build and checks that the latin woff2 and `JetBrainsMono-OFL.txt` (the OFL 1.1 text with the
      JetBrains Mono copyright) are emitted side by side.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `shell/layout.test.ts`; manual measurement in the in-app browser (above) |
| AC2 | `shell/view.test.ts`, `shell/frame.test.ts`, `shell/app.test.tsx` |
| AC3 | `build.test.ts` |

---

## What shipped
- `apps/web/src/main.tsx`, `shell/{app.tsx,header.tsx,layout.ts,view.ts,frame.ts,panels.ts}`,
  `styles/{tokens.css,shell.css}`, `data/load.ts`, `vite.config.ts` (font-licence plugin).
- The A02 placeholder `app.ts` and `main.ts` were removed.

## Evidence
- Tests: web 51 (B02's 34 model tests, minus the placeholder test, plus layout 5, view 3,
  frame 3, app 3, build 3).
- Production build: JS 41.2 kB (15.8 kB gzip) including Preact, signals and the model; CSS
  7.5 kB (3.8 kB gzip); latin font 40.4 kB. That is well inside the 300 kB gzip JS budget, which
  the build test now enforces.
- Licence check: all dependencies on the allow-list (OFL-1.1 was already permitted for fonts).
- CI run: see the PR checks.

## Deviations from spec
- None. DESIGN.md's ring wording was corrected: with the centre at x = 0.15·W, the left *part*
  of the circle is off-screen, not the centre. The geometry is unchanged.

## Known gaps
- The fontsource latin subset does not include U+2192 (→), which appears in two captions. The
  browser renders that one glyph from the fallback monospace font. If it shows, B12's
  visual-regression baselines will capture it. The fix would be a custom subset, deferred
  unless it does.
- Panel bodies are empty until B08/B09. The stage is an empty frame until B04.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| preact | 11.0.1 | MIT | Shell UI (decided stack) |
| @preact/signals | 2.11.3 | MIT | Fine-grained reactive state for the shell |
| @fontsource-variable/jetbrains-mono | 5.3.0 | OFL-1.1 | Self-hosted variable typeface (DESIGN.md) |
| jsdom (dev) | 30.1.2 | MIT | DOM for component tests (and axe-core in B11) |

## Research notes
None.

# Repro — Design

> Baseline v1 (A01). The rendering architecture is in ARCHITECTURE §13 and ADR-0008. The
> motion-safety amendments from ADR-0011 are marked **[ADR-0011]** below.

The look is taken from the Paper Lab reference video. Study `reference/frames/*.png` (full
frames) and `reference/panels/*.png` (header, stage and each of the 8 panels, upscaled) before
building Stage B. `reference/paper-lab-reference.mp4` shows the motion (22 s loop). These files
are third-party media, kept locally and not committed (see `reference/README.md`). This document
is the spec.

Note on orientation: the reference is **portrait** (1280×1600, with the stage taking about 70% of
the height). Repro is **landscape-first** for desktop monitors, with the same grid: the stage
takes at least 55% of the height and the panels sit beneath it. Matching the reference's visual
family matters, not its aspect ratio. The reference's progress bar has 5 segments aligned under
its counters. Repro uses 7, one per pipeline stage.

The Paper Lab mapping → Repro mapping:

| Paper Lab | Repro |
|---|---|
| Web of 64 papers | Dependency web of the repo's modules/symbols |
| Ring of extracted documents | Ring of **files** in the blast radius, as mini code cards |
| Radial streams to the right | Streams of **events**: test runs, trace samples, agent activity |
| Advection / particle solver | **Execution** — tests running on base ‖ head as particles |
| Method workspace | **Agent workspace** — live text of the focused agent's tool calls |
| Shared scene / difference field | **Behaviour diff field** — base vs head grids, red cells = diffs |
| Source / extraction routes | **Change routes** — file → symbol → test → check |
| Validation / sample buffer | **Signals** — test pass rate, behaviour drift, perf |
| 12 agents / dispatch | **Agents / dispatch** — same |
| Method / reference index | **Change × check index** — rows = changes/claims, cols = checks |

## Layout (desktop, landscape first)

```
┌ HEADER 56px ──────────────────────────────────────────────────────────────┐
│ REPRO                     CLAIMS  AGENTS  FILES  CHECKS  FLAGGED          │
│ agent changes → reproduced evidence  4      12     147     28      4      │
│ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬  (stage progress: 7 segments)   │
├ STAGE (flex, ≥ 55% of height) ────────────────────────────────────────────┤
│  dependency web (left, circle clipped by ring) │ ring │ event streams →   │
├ PANELS 2 rows × 4 cols (≈ 34% height, 8px gaps) ──────────────────────────┤
│ Investigation feed │ Execution        │ Agent workspace │ Behaviour diff   │
│ Change routes      │ Signals          │ Agents/dispatch │ Change×check idx │
└───────────────────────────────────────────────────────────────────────────┘
```

- The ring is a large circle whose **left part is off-screen** (centre ≈ x = 0.15·W, radius
  ≈ 0.55·H of the stage), so mainly the right arc shows, like the reference.
- Geometry is computed by one pure function, `computeLayout(width, height)`
  (`apps/web/src/shell/layout.ts`, B03). At 1440×900 the result is: header 56 px, stage 522 px
  (58%), panels 350×149. At 1920×1080: stage 641 px (59%), panels 470×179/180.
- Header counters are left-aligned columns with tiny uppercase labels above large numerals.
  CLAIMS = `claim.extracted` events; AGENTS = distinct spawned agents; FILES = distinct files of
  module nodes in the dependency graph; CHECKS and FLAGGED follow the check model (ADR-0015).
- Progress bar: one segment per stage (read, build, run, diff, check, review, card). The active
  segment is bright white, completed ones mid-grey, pending ones dark grey.
- < 1100 px wide: panels become 2 columns and scroll; stage keeps ≥ 50vh.

## Palette (sampled from the reference)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#080808` | page / stage background |
| `--panel` | `#121212` | panel fill |
| `--panel-border` | `#232323` | 1px panel borders |
| `--line` | `rgba(255,255,255,0.10–0.35)` | web lines, alpha by recency/weight |
| `--text` | `#d6d6d6` | primary text |
| `--text-dim` | `#6e6e6e` | labels, secondary columns |
| `--text-faint` | `#3a3a3a` | inactive rows |
| `--hot` | `#ffffff` | active edges, active segment, cursor |
| `--flag` | `#b48f9c` (dusty rose) | flagged / failing / behaviour diff cells |
| `--flag-deep` | `#6e4e5a` | flag fills, red tint in streams |
| `--ok` | `#8fb4a8` (muted teal) | verified (use sparingly — the reference is almost monochrome) |
| `--violet` | `#7d7390` | stream tint for agent activity |

Rule: the screen is ~95% greyscale. Colour only marks **state** (flagged / verified / agent).
Do not use pure saturated reds or greens.

Dark only for now (the look depends on it). Define tokens on `:root` anyway.

## Type

- One family: **JetBrains Mono** (fallback: IBM Plex Mono, ui-monospace).
- Title: 22px, 700, uppercase, letter-spacing 0.04em.
- Panel titles: 10px, 700, uppercase, letter-spacing 0.08em, `--text`.
- Body/log text: 10–11px, `--text-dim`; the newest/active row is `--text` and bold.
- Numerals in header: 14px, tabular figures.
- Micro labels: 8–9px uppercase `--text-dim`.

## The stage

### Dependency web (left)
- Nodes = modules (and symbols when zoomed). Edges = imports/calls.
- Draw edges as **thin 1px straight lines** with low alpha — thousands of them make the texture
  in the reference. Node markers: tiny 4px hollow circles, only for nodes in the blast radius.
- **Bundles**: when an event touches an edge path (e.g. a test traverses a call chain), draw a
  bright bundle of 8–20 near-parallel curves along it that fades over ~1.2 s. These are the
  bright white sweeps in the reference.
- Layout: force-directed (d3-force), computed once per run in a worker, then frozen. Positions are
  clipped to the inside of the ring. Initial positions are seeded from node-ID hashes (no trig),
  so the layout is reproducible, and it is cached by graph hash.
- Rendering: edges are instanced anti-aliased quads with recency alpha computed in the shader.
  Bundles are instanced Bézier segments. Blending is additive. There is no post-processing
  (ADR-0008).

### Ring (centre)
- A thick band (≈ 90px) made of stacked **file cards**: tiny monospace text blocks rendered from
  the actual file contents (first ~20 lines, 3–4px type — illegible texture is fine).
- Cards for files in the blast radius are brighter; changed files have a thin `--hot` edge.
- The ring rotates slowly (one card per ~2 s) and snaps the **focused file** to the 3 o'clock
  position when an event targets it.
- Thin tick marks + tiny labels on the outer edge (file paths), like the reference's scale.

### Event streams (right)
- Each event emits a streak from the ring's outer edge outward along a radial line, with a
  motion-blurred tail. Length ∝ duration/importance; alpha decays.
- Tint: white = engine, `--violet` = agent, `--flag-deep`/`--flag` = fail/diff, `--ok` = pass.
- Dense bursts are the point: a test batch should look like the reference's fan of streaks.

### Tooltips / callouts
- Small boxes with a 1px border (as at 12 s and 18 s in the video), label + one value,
  anchored to a streak or node. Max 2 visible at once.

## Panels

All panels: 1px `--panel-border`, `--panel` fill, 10px padding, title top-left, optional footer
caption bottom-left in `--text-dim` (the reference uses these, e.g.
"papers → equations → runnable source"). Keep footers:

1. **Investigation feed** — scrolling log: `seq  verb  message`. Verbs: read/build/run/diff/
   check/review. Newest row bold. Footer: none.
2. **Execution** — two lanes (BASE / HEAD): particles = test cases moving left→right while
   running; they settle as dots coloured by outcome. Bottom toggles: `BASE · HEAD · BOTH`.
3. **Agent workspace** — the focused agent's recent tool calls typed out like code, with a
   blinking block cursor (see reference: `eqs = extract_equations(papers)` style). Repro lines
   look like `claims = read_pr(diff)` / `obs = trace(base, head)` / `check_api(diff)`.
4. **Behaviour diff field** — two small grids, BASE and HEAD, one cell per observation
   (test × function). Cells differing between sides glow `--flag` on HEAD. Under them, a
   histogram strip of diff counts per module. Footer: "same input / different output".
5. **Change routes** — table: FILE · SYMBOL · TEST · CHECK, each a pill whose fill shows
   progress. Footer: "diff → symbols → tests → checks".
6. **Signals** — three live waveforms: PASS RATE, BEHAVIOUR DRIFT, PERF Δ. Footer:
   "illustrative until run completes" while partial.
7. **Agents / dispatch** — 2 columns × 6 rows: `id  role  [progress bar]` + tiny status under
   the bar (working / waiting / done / flagged). Flagged bars tinted `--flag-deep`. Footer:
   "independent jobs / shared event bus".
8. **Change × check index** — dot matrix: rows = claims/changes, columns = checks; filled =
   passed, rose = flagged, hollow = unassessed, dim = pending review (ADR-0015). Right column:
   status word (verified / flagged / review). Footer: "28 checks / 20 passed / 4 flagged /
   4 unassessed". (Header counters and this footer always come from the same projection, so
   they can never disagree.)

Clicking any row/cell/node **focuses** it: the stage pans/highlights, and a side drawer opens
with the evidence (raw diff, trace samples, verdict text). The drawer is the only "normal UI"
surface — it stays plain and readable.

## Motion

- Every animated element maps to an event. Idle state (no run) may use slow ambient drift of
  the web only.
- Durations: streak 600–1400 ms, bundle 1200 ms fade, panel row insert 150 ms, ring snap 500 ms
  ease-out-cubic.
- Replay supports speed ×0.5 / ×1 / ×4 / ×16 and scrubbing. Animation is a pure function of
  (events up to t, t).
- `prefers-reduced-motion`: no streaks or bundles, and state changes are instant. An in-app
  toggle mirrors this setting.
- **Global pause** (Space) freezes the presentation clock while ingestion continues (WCAG 2.2.2).
- **[ADR-0011]** Durations above are wall-clock and clamped at high replay speeds. A
  flash governor caps the bright area that can rise within any 333 ms window (WCAG 2.3.1). Above
  the cap, bundles aggregate per edge.

## Accessibility

- The canvas is not accessible to assistive technology, so every panel's meaning is mirrored in
  DOM:
  - the investigation feed is a visually hidden `role="log"` with throttled summaries (at most
    about one every 2 s);
  - the card, the change×check index and the evidence drawer are semantic tables;
  - the stage canvas has `role="img"` with a dynamic `aria-label`.
- Every focusable item (claim, file, agent, cell) is reachable by keyboard and triggers the same
  focus action as a click.
- Colour is never the only carrier of state. Flagged rows also show the word and a glyph.

## Performance budget

- 60 fps on a mid laptop with 10k edges and 2k live streaks. Use instanced geometry and one draw
  call per layer (about 6 stage draw calls). No per-frame allocations. Panels redraw only on new
  events, batched per animation frame.
- Initial load under 300 KB of JS, gzipped (fonts excluded). The measured baseline is about
  146 KB for three.js `WebGLRenderer`, Preact 11, signals and d3-force (research/05 §1.2).
- Measured, not assumed:
  - the perf HUD reports frame-time p50/p95/p99 and draw calls;
  - a nightly stress run gates on relative regression;
  - a manual check on a real mid laptop (Windows, integrated GPU) happens at each stage gate.
- Stage DPR is adaptive and capped at 2. It steps down (2 → 1.5 → 1) when frames are visibly
  dropped: the p95 frame interval exceeds 1.5× the 60 Hz budget, meaning more than 5% of frames
  took two refreshes. It probes back up after a run of good windows, with backoff. A plain "p95 >
  budget" rule fired on vsync jitter alone in B04.
- Measured in B04 (`docs/perf/B04-stress-bench.json`): on an integrated GPU (Intel UHD, Chromium
  152), 10k edges, 2,048 streaks, 360 cards and 720 ticks in 4 draw calls hold 60 fps at DPR 2.
  The p95 frame interval was 17.0 ms and stage CPU time under 1 ms at p95.

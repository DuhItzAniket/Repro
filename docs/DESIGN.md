# Repro — Design

> Baseline v1 (A01). The rendering architecture is in ARCHITECTURE §13 and ADR-0008. The
> motion-safety amendments from ADR-0011 are marked **[ADR-0011]** below.

The look is taken from the Paper Lab reference video. Study `reference/frames/*.png` (full
frames) and `reference/panels/*.png` (header, stage and each of the 8 panels, upscaled) before
building Stage B. `reference/paper-lab-reference.mp4` shows the motion (22 s loop). These files
are third-party media, kept locally and not committed (see `reference/README.md`). This document
is the spec.

Note on orientation: the reference is **portrait** (1080×1350 at 60 fps in the copy used since
B14), with a nearly square stage (about 1.15:1) taking about 70% of the height and the panels
beneath it. Its composition depends on that stage shape, so Repro keeps the stage near it (B14):
on a landscape screen the panels sit **beside** the stage; on a portrait one they sit beneath
it, as in the reference. Matching the reference's visual family matters, not its page aspect
ratio. The reference's progress bar has 5 segments aligned under its counters. Repro uses 7, one
per pipeline stage.

The reference also pans and zooms its camera now and then (for example 7.2–9.5 s). Repro keeps
its home view fixed: every movement on its stage maps to an event (see Motion).

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

## Layout (desktop: the stage keeps the reference's shape)

```
┌ HEADER 56px ─────────────────────────────────────────────────────────────────┐
│ REPRO                     CLAIMS  AGENTS  FILES  CHECKS  FLAGGED             │
│ agent changes → reproduced evidence  4      12     147     28      4         │
│ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬ ▬▬▬▬▬  (stage progress: 7 segments)      │
├ STAGE (≈ 1.15:1) ───────────────────────────┬ PANELS 4 rows × 2 ──────────────┤
│                                              │ Investigation feed │ Execution   │
│ dependency web │ ring │ event streams →      │ Agent workspace    │ Behaviour   │
│ (inside the ring, centre off-screen left)    │ Change routes      │ Signals     │
│                                              │ Agents/dispatch    │ Change×check│
│ ─ transport ─────────────────────────────── │                    │             │
└──────────────────────────────────────────────┴─────────────────────────────────┘
```

- Three modes, computed by one pure function, `computeLayout(width, height)`
  (`apps/web/src/shell/layout.ts`, B03, B14):
  - **side** (width ≥ 1100 and at least 1.3 × the height): the stage on the left, as close to
    1.15:1 as the panels allow, and the 8 panels in 4 rows × 2 columns beside it (each 256 px to
    1.6 × its height wide). At 1440×900: stage 904×844, panels 256×201. At 1920×1080: stage
    1178×1024, panels 359×246. The evidence drawer covers the panels, so the stage stays in view.
  - **stacked** (width ≥ 1100, portrait-ish): the reference's own arrangement, the stage on top
    (at least 55% of the height) and 2 rows × 4 panels in about 30% of the height.
  - **narrow** (< 1100 px): the stage keeps 60% of the height (≥ 50vh), and the panels become 2
    columns that scroll.
- B03–B13 used the stacked arrangement on landscape screens too. That made the stage a wide strip
  (1440×522 at 1440×900) into which the reference's composition did not fit; the owner's Gate B
  review found the stage still did not read as the reference's (B14).
- The ring, measured on the 1080×1350 reference by fitting circles to its rims (B14): the inner
  rim's radius is 1.02 × the stage height, its 3 o'clock point sits at 0.46 × the stage width (so
  the centre lies left of the stage), and the band is 0.215 × the inner radius thick. At 1440×900:
  centre (−445, 422), inner radius 861 px, band 185 px.
- Header counters are left-aligned columns with tiny uppercase labels above large numerals.
  CLAIMS = `claim.extracted` events; AGENTS = distinct spawned agents; FILES = distinct files of
  module nodes in the dependency graph; CHECKS and FLAGGED follow the check model (ADR-0015).
- Progress bar: one segment per stage (read, build, run, diff, check, review, card). The active
  segment is bright white, completed ones mid-grey, pending ones dark grey.

## Palette (sampled from the reference)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#080808` | page / stage background |
| `--panel` | `#121212` | panel fill |
| `--panel-border` | `#232323` | 1px panel borders |
| `--line` | `rgba(255,255,255,0.10–0.35)` | web lines, alpha by recency/weight |
| `--text` | `#d6d6d6` | primary text |
| `--text-dim` | `#868686` | labels, secondary columns (raised from the reference's `#6e6e6e` in B11 for WCAG 1.4.3: at least 4.5:1 on every background text sits on) |
| `--text-faint` | `#3a3a3a` | inactive marks: empty dots, rules, ticks. Never text (it is 1.76:1) |
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

### Dependency web (inside the ring)
- Nodes = modules, symbols and tests. Edges = imports, calls and covers.
- **Chord layout** (B14): modules sit on a circle under the ring's band (1.1 × the inner rim's
  radius), evenly spaced in the angular order a force-directed simulation gives them, so tightly
  connected modules are neighbours. Symbols and tests, the nodes a run touches, sit **in
  front**: spread across the sector of the disc the stage shows (within 28° of 3 o'clock, at 0.5–
  0.86 of the circle's radius), in the same order, like the nodes of a network. Where a node sits
  is a rule the engine can change later; today it is the simulation's order. The simulation
  (d3-force) runs once per graph in a worker, seeded from node-ID hashes (no trigonometry), with
  layout-only containment links that tie symbols and tests to their module; the result is cached
  by graph hash.
- Edges are **thin arcs**: quadratic curves bowed to one side by 25–60% of their length, with
  the side and amount taken from a hash of the endpoints. Every arc stays **inside the web's
  circle** (its control point is kept within it, so the curve is too), whose edge is under the
  ring's band: no edge bows out past the wheel. Before this rule, 82 of the demo's 1,500 arcs
  showed beyond the ring's outer rim. The circle's centre is off-screen to the
  left and its edge is under the band, so the stage shows long curves crossing the web, like the
  reference's hairball, not a ball of spokes. B03–B13 drew straight lines on a force-directed
  disc, which read as a starburst. Only the pieces on the stage are written. Alpha: imports 0.17,
  calls 0.22, covers 0.12, so the strands read over them.
- Symbols and tests are small hollow circles (tests 3.2 px, symbols 2.2 px): the points strands
  fire from, like the reference's scattered circles. Nodes in the latest blast radius get a
  brighter ring.
- **Bunches of strands** (bundles): when a test reaches a function (`trace.sample`;
  `diff.behaviour` in `--flag`), a **bunch** fires at the function's ring card, as the owner
  described the reference's (B14):
  - its strands come from **the nodes that reach the function**: its tests (by `covers` edges and
    trace samples) and its callers (by `calls` edges), the test that fired first; at most 12.
    Membership uses only the log up to the firing event (`ReachIndex`);
  - **one strand per node**, each from its own point; they converge side by side on one bar at
    one section of the wheel, ordered by their nodes' bearings so they do not cross there;
  - each strand is a **dim line** (alpha 0.32) revealed behind a **white bullet**, a bright 80 px
    stretch that shoots from its node to the ring in the first 40% of a 1 s life (smoothstep;
    each strand starts up to 6% later). Its node lights up while the bullet is in flight, and
    the bar flashes when they land;
  - the bunch aims at the card where it stood when the bunch fired, within 10° of the first
    node's bearing; it stays **attached to its nodes** while its landing end **follows that
    section of the ring** as it turns (by at most the ring's drift over the life), then fades from
    60% of its life on;
  - at most one bunch per function rises per 333 ms window (the flash governor's aggregation).

  Each strand arrives at the rim along the ring's radius, sweeping a little towards the turning
  direction; node, control point and landing point are inside the inner rim, so the strand is
  too. Measured on the reference: a strand's bright part travels to the ring in about 0.1 s.
- Rendering: edges are instanced anti-aliased quads with recency alpha computed in the shader.
  Arcs and bundles are chains of segments that do not overlap at their joints. Blending is
  additive. There is no post-processing (ADR-0008).

### Ring (centre)
- A thick, opaque band, 0.215 × its inner radius (185 px at 1440×900), drawn as a drum like the
  reference's (B14): a lit bezel and a ruler comb along the inner rim, the cards, and a second comb
  inside the outer rim. It hides the web behind it; every other stage layer is drawn over it or
  beside it.
- **File cards** fill the band from rim to rim, one per file, with text running outward. No v1
  event carries file contents, so a card is the file's **outline from events** (B06), laid out
  like the reference's code cards (B14):
  - a header, `// package / module`, with a rule after it;
  - rows of `line  code`: its functions, classes and tests with their line numbers (`graph.node`),
    changed ones in `--flag` (`symbol.changed`), then its imports as `from a import b`
    (`graph.edge`); at most 10 rows;
  - a neighbour fingerprint: a 16 × 4 grid of dots, one per bucket of the repo's modules in path
    order, lit where the file imports or is imported by a module in that bucket (the reference's
    dot matrices);
  - right-aligned labels on the outer column: imports, importers, symbols and changes.
- Each card takes its natural size, at the same scale along the arc as across the band, so text
  is not stretched (about 5–6 px on screen at 1440×900). At most 64 cards. They fill the circle
  for a repo of the demo's size and are scaled down if they overfill it. Files the run is about
  come first.
- Cards for files in the blast radius are brighter (ink 1.0, others 0.8). Changed files have a
  thin `--hot` edge on their leading side.
- The ring turns once every 24 s of wall-clock time at any replay speed (about 15° a second;
  B14, measured on the reference, whose cards pass 3 o'clock at about 280 px/s at mid-band; it
  was one card per ~2 s before). It snaps the **focused file** to the 3 o'clock position (500 ms
  ease-out-cubic) when an event targets it: `symbol.changed`, `claim.extracted`,
  `diff.behaviour/tests/perf/api`, `verdict.issued` or `missing.recorded`. A file the user
  focuses is pinned at 3 o'clock without drift.

### Event streams (right)
- Each event emits a streak from the ring's outer rim outward along a radial line, with a
  motion-blurred tail. Length ∝ duration/importance; alpha decays.
- Tint: white = engine, `--violet` = agent, `--flag-deep`/`--flag` = fail/diff, `--ok` = pass.
  Priority (B07): fail, then diff, then a passing test, then agent, then engine.
- Dense bursts are the point: a test batch should look like the reference's fan of streaks.
- Lanes (B07): an event streams along its file's lane, a hash of the file mapped onto the
  ring's right side, so one file's activity forms a band. Since B14 lanes span ±24°, the outer
  rim's visible arc on a stage of the reference's shape, and each event deviates by up to ±4.9°
  from its lane, so the bands merge into a field. Graph, stage, run and feed events do not stream;
  at most 2,048 streaks are live (the newest).
- **Rays** (B13's residue, restyled in B14): every streaming event also leaves a static ray along
  its lane, from the outer rim towards the stage's edge (0.55–1.3 of the way, further for
  findings and slow tests). It draws itself out over 900 ms of wall-clock time, behind its streak.
  It is brightest at the rim (0.42–0.92 by importance, 1.6 px), falls to 45% at its outer end,
  and fades over 90 s of run time. Busy files build dense bands, like the reference's
  long-exposure field. Rays are not flashes, by construction (ADR-0011, B14 note):
  - they blend with MAX, so overlaps never add up;
  - their fade never takes less than 40 s of wall-clock time.

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
   running; they settle as dots coloured by outcome. Bottom toggles: `BASE · HEAD · BOTH`. The
   repeat base run (A′) shares the BASE lane with dimmer particles and separate counts.
3. **Agent workspace** — the focused agent's recent tool calls typed out like code, with a
   blinking block cursor while it works (see reference: `eqs = extract_equations(papers)` style).
   The focused agent is the one with the latest state change unless the user pins one. Repro lines
   look like `claims = read_pr(diff)` / `obs = trace(base, head)` / `check_api(diff)`.
4. **Behaviour diff field** — two small grids, BASE and HEAD, one cell per observation
   (test × function). Cells differing between sides glow `--flag` on HEAD; cells whose base
   runs disagree (A ≠ A′) are unstable, masked in `--flag-deep` and not counted. Under them, a
   histogram strip of diff counts per module. Footer: "same input / different output".
5. **Change routes** — table: FILE · SYMBOL · TEST · CHECK, each a pill whose fill shows
   progress. Footer: "diff → symbols → tests → checks". One row per changed symbol. The step a
   route has reached is the pill: TEST fills as its tests finish on HEAD, CHECK as its checks
   resolve, with a white underline while in progress. A test routes to a symbol it was
   selected for, to a change its selected symbols call (≤ 3 hops), or to a module-level change
   of a module its test module imports (ARCHITECTURE §13).
6. **Signals** — three live waveforms: PASS RATE, BEHAVIOUR DRIFT, PERF Δ. Footer:
   "illustrative until run completes" while partial. PASS RATE is the share of the last 8 HEAD
   finishes that passed; DRIFT the share of the last 16 stable base/head sample pairs that
   differ; PERF Δ is head/base − 1 per repetition. Ticks mark the checks that resolve each
   signal, placed at the data point they are about; the time axis spans the series.
7. **Agents / dispatch** — 2 columns × 6 rows: `id  role  [progress bar]` + tiny status under
   the bar (working / waiting / done / flagged). Flagged bars tinted `--flag-deep`. Footer:
   "independent jobs / shared event bus". An agent is flagged when it failed or contradicted
   a claim; a working agent's status also names its tool.
8. **Change × check index** — dot matrix: rows = claims/changes, columns = checks; filled =
   passed, rose = flagged, hollow = unassessed, dim = pending review (ADR-0015). Right column:
   status word (verified / flagged / review). Footer: "28 checks / 20 passed / 4 flagged /
   4 unassessed". (Header counters and this footer always come from the same projection, so
   they can never disagree.)
   - Rows: each claim, then changed symbols no claim covers (grouped by file), then "other"
     for checks related to neither.
   - A check that names a symbol relates to the rows covering that symbol. Other checks relate
     through their file or a routed test. A claim also relates to every check its verdict cites.
   - Status: a claim is flagged if contradicted or any related check is flagged, verified if
     supported with nothing pending, otherwise review. An unclaimed change is flagged or review,
     never verified. When checks outnumber the columns, a column covers adjacent checks and
     shows the most urgent related result.

Clicking any row/cell/node **focuses** it: the stage pans/highlights, and a side drawer opens
with the evidence (raw diff, trace samples, verdict text). The drawer is the only "normal UI"
surface — it stays plain and readable.
- Focusable (B11): index rows (claims, unclaimed changes) and cells (checks), route rows
  (symbols), dispatch slots (agents), ring cards and web nodes (files, symbols). Rows in the
  drawer link onwards.
- Focus outlines the focused files' ring cards, rings their nodes and brightens their edges.
  The ring pins the first focused file with a card at 3 o'clock, without drift, until the focus
  changes. A focused agent is pinned in the agent workspace.
- The drawer opens over the right of the stage. Keyboard focus moves into it; Escape closes it
  and returns focus to where it was.

## Motion

- Every animated element maps to an event. Idle state (no run) may use slow ambient drift of
  the web only.
- Durations: streak 600–1400 ms, strand bunch 1 s (B14: the bullets' 0.4 s trip, then the
  attached strands follow the ring and fade), panel row insert 150 ms, ring snap 500 ms ease-out-cubic,
  one ring turn 24 s.
- Replay supports speed ×0.5 / ×1 / ×4 / ×16 and scrubbing. Animation is a pure function of
  (events up to t, t, motion), where motion is the replay speed and reduced motion.
- `prefers-reduced-motion`: no streaks or bundles, and state changes are instant. An in-app
  toggle mirrors this setting. Instant here also means: no recency flares, no ring drift, snaps
  in one step, whole feed rows and typed lines, a steady workspace cursor, and running tests
  held still.
- **Global pause** (Space) freezes the presentation clock while ingestion continues (WCAG 2.2.2).
  Space is left to a focused control (a button, the scrubber), which handles it itself.
- **Transport** (B10): a strip along the bottom of the stage with Play/Pause, ×0.5 ×1 ×4 ×16,
  a scrubber at 100 ms steps with an `m:ss.s` readout, Live and Reduce motion.
- **[ADR-0011]** Durations above are wall-clock, so in run time they scale with the replay speed;
  edge and marker flares (1,500 and 900 ms) and callouts (2.5 s) too. A flash governor caps the
  bright area that can rise within any 333 ms of wall-clock time (WCAG 2.3.1):
  - the cap is 43,648 CSS px², half of WCAG's 87,296 CSS px² flashing area;
  - areas are upper bounds from each element's geometry;
  - over the cap, streaks and bundles are not drawn, and edges and markers appear without their
    flare;
  - at most one bunch of strands per function rises per window (aggregation; per graph edge
    before B14);
  - stream rays are not counted: they blend with MAX and fade over at least 40 s of wall-clock
    time, so no pixel can lose 10% relative luminance within a second (B14).

## Accessibility

- The canvas is not accessible to assistive technology, so every panel's meaning is mirrored in
  DOM:
  - the investigation feed is a visually hidden `role="log"` with throttled summaries (at most
    one every 2 s, batching every line since the last);
  - the card, the change×check index and the evidence drawer are semantic tables;
  - the stage canvas has `role="img"` with a dynamic `aria-label` (time, edges, files, streams,
    focus), updated at most once a second;
  - routes and dispatch rows are lists of buttons; a "Focus a file" picker on the stage
    appears when it has keyboard focus.
- Mirror buttons are visually hidden; the canvas outlines the row the keyboard is on (white
  outline) and the focused row (light fill), so keyboard focus is always visible.
- Landmarks: the header (banner), `main` (stage, transport, panels) and the drawer (aside).
- Text uses `--text` or `--text-dim` (4.5:1 or better). Boxes over the stage (callouts,
  transport) are opaque, so their text keeps its contrast whatever passes behind.
- Every focusable item (claim, file, agent, cell) is reachable by keyboard and triggers the same
  focus action as a click.
- Colour is never the only carrier of state. Flagged rows also show the word and a glyph.

## Performance budget

- 60 fps on a mid laptop with 10k edges and 2k live streaks. Use instanced geometry and one draw
  call per layer (about 6 stage draw calls). No per-frame object allocations in the stage
  layers (B12 measured about 25 kB a frame at the stress burst and B14 24 kB, all of it V8
  boxing doubles at calls it does not inline, short-lived). The heap stays flat across frames (B12 gate). Panels
  redraw only on new events, batched per animation frame.
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
  The p95 frame interval was 16.9 ms and stage CPU time under 1 ms at p95.

# B06 — Ring layer (file-card atlas)

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B04 |
| **Branch / PR** | `phase/B06-ring-layer` · PR link added on creation |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
The stage's centre: a thick, turning ring of file cards with a tick scale, built from the event
stream. It snaps the file the run is looking at to 3 o'clock.

## Scope
- `ringContent`: which files get cards, each card's text, and its appear, blast-radius and
  change times. Also the focus events that turn the ring.
- `ringAngles` and `ringRotation`: card angles, and a closed-form rotation with drift plus
  500 ms ease-out-cubic snaps.
- The card atlas: packing (`atlasLayout`), Canvas 2D drawing (`drawAtlas`), a worker
  (`atlas.worker.ts`), and `AtlasService` (worker by default, inline fallback, cache by content
  key, stale bitmaps closed).
- Layers: `cardLayer` (a new **card primitive**: instanced sector quads sampling the atlas,
  normal blending) and `tickLayer` (rims and scale on the segment primitive).
- The segment primitive gained a rotation uniform about the ring centre (`uCenter`, `uSpin`), so
  turning layers never rewrite their buffers.

## Design notes
- **Cards come from events, not file contents.** No v1 event carries file text (B01 known gap),
  and a schema change is not justified for 3–4 px texture. So each card is the file's outline
  from what events do carry:
  - its path;
  - up to four `import` lines (`graph.edge` imports);
  - up to four `def`/`class` lines (`graph.node`).

  A metadata card in the outer column shows the file name, import and symbol counts, and
  `±n` for changed symbols. This keeps DESIGN.md's rule that every mark projects a real event.
- **Which files.** Every module file, up to 160. When there are more (stress: 2,000), the files
  the run is about come first: the blast radius, changed files, and focus targets. They are
  shown in path order, like an index.
- **Band geometry.** Two columns as in the reference: content from the ring radius −44 to +8 px,
  metadata from +10 to +44 px. Cards share the circle in proportion to their line count, with a
  small gap. A card is a sector quad: radial text at 3 o'clock, as in the reference.
- **Static data, time in the shader.** Each card carries the time its file appears, joins the
  blast radius (brighter ink) and is changed (a thin `--hot` edge). The card buffer is written
  once per content. Playback and scrubbing only move `uTime` and `uRotation`. The band uses
  **normal** blending (alpha 0.94), so it occludes the web like the reference's opaque ring.
  Every other layer is additive.
- **Rotation (closed form).** Drift is one card per 2 s. Each focus event snaps its card's
  centre to angle 0 over 500 ms, ease-out-cubic, the short way round. Focus events are
  `symbol.changed`, `claim.extracted`, `diff.behaviour/tests/perf/api`, `verdict.issued` and
  `missing.recorded`, with the file from `target.file` or the test id. A snap that interrupts
  another starts from that one's current offset. All snaps are precomputed once, so
  `rotation.at(t)` is a binary search: exact after any scrub, no history, no allocation.
- **The atlas is built off the main thread.** A module worker draws all cards into one
  OffscreenCanvas (2016 × 1260 px for the demo, at 1.5× scale) and transfers an `ImageBitmap`.
  The host uploads it once per content version, with `flipY` false because ImageBitmaps cannot
  be flipped on upload. Without `Worker` or `OffscreenCanvas` it falls back to the main thread.
  Verified in the browser: `atlas.worker.ts` was loaded, and the bound texture came from the
  worker.

## Acceptance criteria
- [x] AC1: One draw call for the cards. All 2 × N card quads (content and metadata) are
      instances of one mesh (`cardLayer`, `primitive: "cards"`). With 147 files the stage draws
      294 card instances; stress peaks at 320.
- [x] AC2: Snap timing matches the spec in golden tests (`rotation.test.ts`):
      - the focused card's centre is at 3 o'clock (|angle| < 1e-9) exactly 500 ms after its event;
      - the offset follows ease-out-cubic at 10/25/50/75%;
      - no jumps across interrupting snaps;
      - the rotation is a pure function of `t`;
      - snapping goes the short way;
      - 0 ms snaps are instant (for reduced motion, B10).

      The ring's render model and rotation are pinned at five times of the demo run.
- [x] AC3: The atlas builds off the main thread (`defaultAtlasBuild` → `workerBuild`; worker
      load observed in the browser). `AtlasService` is tested to build once per content key,
      keep only the newest result and close stale bitmaps.

## Evidence
- Tests: web 116 (+25: content 7, rotation 9, atlas 4, ring layers 5).
- Bench (`docs/perf/B06-ring-bench.json`): integrated GPU (Intel UHD), 1920×641 stage. Load:
  10,000 edges, 2,730 bundle segments, 608 markers, 320 cards, 1,184 tick/rim segments, plus
  2,048 proxy streaks. p95 interval 16.9–17.1 ms at DPR 1 and 2, CPU p95 ≤ 1.4 ms, frame work
  ≤ 2.5 ms worst case. 1–3% of frames took two refreshes. See below.
- In the browser, pixel read-back shows the band: card background with anti-aliased text
  strokes at 3 o'clock.

## Investigation: dropped frames
Dropped frames rose from 0.2–1.3% (B05) to 1.7–3.0% once the ring was added. Hypothesis: the tick
layer re-uploaded about 52 KB every frame. Rotating ticks in the shader instead (static buffers)
left the rate at 1.3–2.1%. Drops also occur at DPR 1 as often as at DPR 2, and the stage's own
frame work stays under 2.5 ms. So they are not rendering cost but host jitter in the embedded
browser. The shader rotation stays, because it is the right design (no per-frame uploads on the
ring at all). The variance is recorded as measured.

## Deviations from spec
- Card text is the file's outline from events, not its first ~20 lines (DESIGN.md is updated).
  No event carries file contents, and a schema change for decorative text was not justified.

## Known gaps
- The worker draws with the generic `monospace` font, because the variable JetBrains Mono is
  not loaded in the worker's font set. At 3–4 px this is not visible. Loading the font into the
  worker (`FontFace` in the worker) is optional polish.
- A card's text is squashed to fit its sector (cells are 120 × 40 px, sectors vary). This is
  intended texture.
- `RingModel` rebuilds on every growth of the log. That is fine for fixtures. For the live
  stream (C08) it should be throttled.

## Dependencies added
None.

## Research notes
None.

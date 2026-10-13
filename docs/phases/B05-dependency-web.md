# B05 — Dependency-web layer & bundles

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B04 |
| **Branch / PR** | `phase/B05-dependency-web` · PR link added on creation |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
The stage's left half: the repository's dependency web, laid out once and frozen. Blast-radius
nodes are marked, and bright sheaves of curves sweep along the paths events touch.

## Scope
- `GraphIndex` (model): the graph as append-only node and edge tables with each event's store
  index. `nodeForSymbol` maps module-level symbols to their module.
- Layout: `layoutInput`/`layoutHash` (main thread), `forceLayout` (d3-force 3.0.0) in a module
  worker, and `LayoutService` (cache by graph hash, newest request wins).
- Layers: `edgeLayer`, `markerLayer`, `bundleLayer` on the segment primitive.
- Segment primitive: a per-instance `appear` time with recency uniforms (`uTime`, `uFlare`,
  `uFlareMs`), and its TypeScript mirror `segmentAlpha`.
- Host: rebuilds a layer's geometry when its buffers are reallocated.

## Design notes
- **Edges are static; the clock reveals them.** Every edge is written once, with the
  presentation time of its `graph.edge` event. The vertex shader hides an edge before that time,
  then flares it (×3.5 alpha, decaying with τ = 1.5 s) back to its base alpha (0.10 imports,
  0.16 calls, 0.07 covers). Playback and scrubbing therefore change one uniform. Edges are
  rewritten only when the graph, the layout or the ring changes (tested: `version` stays fixed
  across frames). Hidden segments collapse to a point, so they cost no fill.
- **Layout.** Deterministic d3-force: hash-seeded start positions without trigonometry,
  d3-force 3's fixed-seed jiggle, and 300 ticks. Two additions make it read like the reference's
  even hairball:
  - **containment links** (layout only, never drawn) tie symbols and tests to their file's
    module; otherwise they float away as separate clusters;
  - **radial equalisation**: a hub-heavy import graph collapses into a saturated white core
    (seen in the first render). Each node keeps its angle and radial rank, and its radius moves
    85% of the way to that rank's position in a uniform disc.

  `sqrt` is used rather than `Math.hypot`, which the spec leaves implementation-approximated.
  The main thread builds the input and its hash. d3 ships only in the worker (and as a lazy
  chunk for the inline fallback).
- **Bundles are a pure function of (events in the last 1.2 s, t).**
  - Triggers: each `trace.sample` (test → traced function) and `diff.behaviour` (tinted
    `--flag`), newest first, at most 40.
  - Shape: 8–20 near-parallel quadratic Béziers per bundle, count and bow side from the
    event's hash, swept from source to target over the first 25% of their life, fading as
    (1 − life)².
  - Nothing persists between frames (property-tested).
- **Markers.** An 8-segment hollow circle (radius 3 px) on each node of the latest
  `blast.computed`: changed nodes at alpha 0.9, affected at 0.4.

## Defects found and fixed
1. **Nothing was drawn at all (shared primitive; B04's PR fixed before merge).** three.js
   culled every segment quad as a back face, because the shader's y flip reverses the winding.
   Bisected in the browser: attribute and uniform bindings were fine, and only geometry
   produced by the real vertex shader vanished. The fix and a pixel sanity check went into PR
   #13 before it merged, and B04's benchmark was re-measured and corrected there.
2. **Instance count silently capped.** three.js caches `_maxInstanceCount` per geometry from
   the first arrays it binds. After a layer's buffers grew (edges: 1,024 → 2,048), only 1,024
   instances were drawn. The host now builds a new geometry on reallocation.
3. **A per-frame allocation in window queries.** `WindowIndex.active()` returns a tuple.
   Per-frame layers now call `firstAtOrAfter`/`cursorAt` directly. `KindIndex.lastIndex` was
   added for the same reason.

## Acceptance criteria
- [x] AC1: 10k edges at the frame budget on the stress fixture.
      `docs/perf/B05-web-bench.json`, integrated GPU (Intel UHD), 1920×641 stage. Peak load:
      10,000 edges, 608 marker segments, 2,730 bundle segments, plus 2,048 proxy streaks,
      360 cards and 720 ticks, in 5 draw calls.

      | DPR | p95 / p99 interval (ms) | Dropped frames | CPU p95 (ms) |
      |---|---|---|---|
      | 1 | 16.9 / 17.5 (run 2: 17.0 / 17.4) | 0.6% (0.2%) | 1.1 (0.9) |
      | 1.5 | 17.1 / 33.3 | 1.3% | 1.2 |
      | 2 | 17.1 / 17.9 (run 2: 16.9 / 17.5) | 0.8% (0.2%) | 1.2 (0.8) |

      The pixel sanity check confirmed 0.34 M to 1.32 M lit device pixels. The stress layout
      takes 2.4–2.5 s in the worker, off the main thread.
- [x] AC2: The layout is identical across reloads. `forceLayout` is deterministic (tested), and
      the demo layout's digest is pinned. CI checks it on Ubuntu and Windows.
- [x] AC3: Bundles are pure functions of (event, t) and golden-tested:
      - a fresh layer and a reused layer give equal render-model hashes at 60 random times;
      - the combined web render model is pinned at four times of the demo run.

## Evidence
- Tests: web 91 (+20: graph 4, layout 8, layers 8). The B04 proxy pin changed once, as intended,
  because the segment render model gained the `appear` attribute.
- JS bundle: main chunk 155.6 kB gzip, layout worker 13.9 kB, lazy d3 chunk 5.5 kB gzip.
- CI run: see the PR checks.

## Deviations from spec
- The layout adds containment links and radial equalisation (Design notes). DESIGN.md's
  "force-directed (d3-force)" still holds; the equalisation only post-processes the radii.

## Known gaps
- Bundles follow one test → function hop. Multi-hop call chains, and aggregation under the
  flash governor, belong to B10 (ADR-0011).
- Live mode needs a policy for when to lay out while the graph is still growing (C08). With
  fixtures, the full graph is known after ingest.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| d3-force | 3.0.0 | ISC | Force layout (decided stack); brings d3-dispatch, d3-quadtree, d3-timer 3.0.1 (ISC) |
| @types/d3-force (dev) | 3.0.10 | MIT | Types |

## Research notes
None beyond the B04 correction entry in `docs/paper/LOG.md`.

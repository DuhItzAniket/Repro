# B04 — Stage foundation & performance harness

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B03 |
| **Branch / PR** | `phase/B04-stage-foundation` · [#13](https://github.com/DuhItzAniket/Repro/pull/13) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Put a WebGL stage behind the `Layer` interface. Measure the planned layer designs under the
stress load before building them, and do it on an integrated GPU.

## Scope
- `StageHost` (three.js `WebGLRenderer`, the only three.js importer): one instanced mesh per
  layer, `update → upload-if-changed → draw` per frame, adaptive DPR, frame statistics.
- The `StageLayer` contract: pure CPU layers that write preallocated instance buffers.
- The segment primitive: instanced anti-aliased quads in GLSL ES 3.00 (`?raw` imports),
  additive blending. Edges, streaks, ticks and bundles will all use it.
- `InstanceBuffers` and `hashRenderModels`: the GPU-free render-model harness (ADR-0008).
- `FrameStats`/`RollingSamples` (allocation-free percentiles), `AdaptiveDpr`, and the perf HUD
  (`?hud`).
- `bench.html` plus `src/bench`: proxy layers and the stress benchmark, results in `docs/perf/`.
- The app mounts the stage canvas (empty until B05); without WebGL 2 the rest still works.

## Out of scope
- The real edge, bundle, ring and streak layers (B05–B07), the nightly perf job and the
  allocation test (B12).

## Design notes
- **Pure layers, thin host.** A layer only writes `Float32Array`s. The host binds them to
  `InstancedBufferAttribute`s and uploads a layer only when its buffers' `version` changed, so
  static layers (edges between graph events, ticks) cost no upload per frame. Reallocation bumps
  `generation`, and the attributes are rebound. Layers are therefore tested in Node by hashing
  exactly what they would upload.
- **Hashing survives float noise.** Values are quantised to 1/256 px before hashing (two 32-bit
  FNV-style lanes, so 64 bits). Last-bit differences in `Math.sin`/`cos` between JavaScript
  engines cannot change a hash, but any visible change does (tested both ways).
- **Segment shader.** The quad is expanded from the segment by half its width plus one *device*
  pixel. Coverage is computed in device pixels, so 1 px edges stay crisp at DPR 2 and lines
  thinner than a pixel fade rather than vanish. A per-instance `tail` alpha gives streaks their
  fading tails with no extra geometry. Clip space is computed in the shader from a viewport
  uniform: no matrices, no culling.
- **Adaptive DPR, revised after measuring.** DESIGN.md said to drop "when p95 frame time exceeds
  budget". In the embedded Chromium, an **idle** stage already showed p95 intervals of about
  18.2 ms (vsync jitter), and a literal threshold dropped the DPR from 1.75 to 1 with nothing on
  screen. The controller now steps down only when frames are visibly dropped: the window's p95
  interval is above 1.5× the 60 Hz budget, meaning more than 5% of frames took two refreshes.
  It ignores 60 warm-up frames. Intervals are vsync-locked, so headroom cannot be read from
  them. Instead it probes one step up after 8 good windows, and doubles that wait (up to 64)
  whenever a probe fails. Levels: the display's ratio capped at 2, then 1.5, then 1. DESIGN.md
  is updated.
- **Benchmark design.** Proxy layers reproduce the planned load:
  - every graph edge as a random chord inside the ring (longer than force-directed edges, so
    more fill rate than the real layer: a conservative proxy);
  - up to 2,048 live streaks from `WindowIndex.active(t, 1400)`;
  - 360 ring cards and 720 ticks.

  The busiest second of the stress run is looped for 8 s after a 1 s warm-up. Each case gets a
  fresh WebGL context. Positions come from id hashes, without trigonometry.

## Acceptance criteria
- [x] AC1: The empty stage plus the HUD runs. In the app (`/?hud`), the stage canvas renders
      at 60 fps with CPU under 0.4 ms (p99) and the DPR stays at the display's 1.75.
- [x] AC2: Render-model hashes are stable across runs (`proxies.test.ts`):
      - the same hashes come out for any order of frames;
      - the demo run's hashes at four times are pinned;
      - CI checks the same pins on Ubuntu and Windows.
- [x] AC3: A stress benchmark is recorded (`docs/perf/B04-stress-bench.json`, two runs) and
      decides the layer design. See Evidence: **no change needed** before B05–B07.

## Evidence
- Tests: web 71 (+20: stats 4, dpr 6, instances 6, proxies 4).
- **Stress benchmark.** Integrated GPU: Intel UHD Graphics via ANGLE D3D11, in the Claude
  desktop app's Chromium 152 on Windows 11. Load: 1920×641 stage, 10,000 edges, 2,048 streaks
  at peak, 360 cards, 720 ticks, 4 draw calls.

  | DPR | Interval p50 / p95 / p99 (ms) | Dropped frames | CPU p95 (ms) |
  |---|---|---|---|
  | 1 | 16.7 / 17.0 / 17.6 (run 2: 16.8 / 33.3) | 0.8% (1.3%) | 0.8 (0.5) |
  | 1.5 | 16.7 / 17.1 / 33.2 | 1.1% | 0.8 |
  | 2 | 16.7 / 17.0 / 33.2 (run 2: 17.0 / 33.1) | 1.1% (1.1%) | 0.9 (0.8) |

  Reading:
  - The budget holds at every DPR, including 2.
  - About 1% of frames take two refreshes at **every** DPR, including 1. They do not grow with
    pixel count, so they come from the host browser's frame jitter, not the GPU (the idle stage
    shows the same p99 spikes).
  - CPU work is under 1 ms at p95, so the main thread has more than 15× headroom for the real
    layers' logic.
- **Bundle:** JS 572 kB raw, **149 kB gzip** with three.js. That matches research/05's estimate
  of about 146 kB, and the build test's 300 kB gzip budget holds.

## Deviations from spec
- The adaptive-DPR rule changed as described in Design notes. A literal reading caused
  spurious drops on an idle stage.
- The "mid laptop" is this machine's **integrated** GPU (Intel UHD). Its CPU (i7-14650HX) is
  stronger than a mid laptop's, so CPU numbers are optimistic. The headroom is large enough that
  this does not change the decision. The stage-gate manual check on a mid-range machine
  (DESIGN.md) remains.

## Known gaps
- WebGL has no GPU timer here (`EXT_disjoint_timer_query_webgl2` is commonly unavailable), so
  GPU cost is inferred from dropped frames rather than measured directly.
- three.js's own per-frame allocations are not covered by "no allocation in `frame()`". The B12
  allocation test measures the whole frame and will show whether they matter.
- `bench.html` is a dev-server page. B12's nightly job decides how to run it in CI.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| three | 0.186.1 | MIT | Stage renderer (ADR-0008) |
| @types/three (dev) | 0.186.0 | MIT | Types for three (latest published for 0.186) |

## Research notes
Logged in `docs/paper/LOG.md`: rendering cost at the stress load, for the system-description
section.

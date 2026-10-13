# B12 — UI quality gate

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B11 |
| **Branch / PR** | `phase/B12-ui-gate` · [#23](https://github.com/DuhItzAniket/Repro/pull/23) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Guard the cockpit with four CI gates: visual regression, allocation, bundle size and frame
cost. Each gate is shown to fail on an injected regression of its kind.

## Scope
- **Visual:** `playwright.config.ts`, `e2e/visual.spec.ts`, and `src/test-hook.ts`, which
  provides `renderAt(t)` behind `?test`. The `visual` CI job runs in the Playwright 1.64.0 image
  pinned by digest. Baselines are in `e2e/__screenshots__`.
- **Allocation:** `src/perf/pipeline.ts` (the frame work without GPU or DOM) and
  `src/perf/alloc.test.ts`.
- **Size:** `.size-limit.json` (size-limit 14.2.0, `@size-limit/file`); a step in `test`
  (Ubuntu).
- **Perf:** `src/perf/frame-cost.perf.ts`, `vitest.perf.config.ts`, and
  `perf/frame-cost-baseline.json`; `.github/workflows/nightly.yml`.
- **Self-tests:** the `gates` job, plus the self-test step in `visual`. `REPRO_INJECT` injects a
  regression of each kind.

## Design notes
- **Visual determinism.**
  - Chromium renders WebGL through SwiftShader (`--use-angle=swiftshader`,
    `--enable-unsafe-swiftshader`), in the pinned image, at 1440×900 and DPR 1.
  - In `?test` mode the stage's DPR is fixed (no adaptive DPR).
  - `renderAt(t)` waits for the log, the web layout worker, the ring's atlas worker and the web
    font weights, then pauses the clock at `t` and waits three frames.
  - The tolerance is 50 differing pixels. The injected regression (every panel shifted by 1 px)
    changes thousands of pixels.
  - Each test also requires more than 10,000 lit stage pixels, so a blank WebGL canvas can never
    become a baseline.
- **Baselines only from CI** (ADR-0009). With none committed, the `visual` job writes them,
  uploads them as an artifact and fails until they are committed. Run 38462556161 did that: its
  six screenshots were checked by eye (stage, panels, drawer, reduced motion) and committed. The
  perf baseline works the same way, from the `gates` job's artifact. On this machine the
  calibrated p50 ratio is about 0.037; in CI it is 0.0496, which is why baselines are never
  local.
- **Allocation.** Two checks:
  - "Flat heap": after 1,000 warm-up frames and a full GC, 1,000 more frames of the stress burst
    may retain under 512 kB. The measure is JS heap plus ArrayBuffers. A first version measured
    only the JS heap and passed an injected `Float64Array` leak, because typed-array backing
    stores live outside it.
  - Stage-layer bytes per frame, measured with V8's allocation counter where the runtime
    exposes it (Node 25 here). The test is reported as skipped otherwise.
- **What allocation really is.** The stage layers allocate no objects, but V8 boxes doubles
  passed to calls it does not inline, about 25 kB a frame with 2,048 live streaks.
  - The budget is 40 kB: new per-event objects would exceed it.
  - DESIGN.md, IMPLEMENTATION_PLAN and `StageLayer.update` said "no allocation"; they now state
    what was measured.
  - Short runs overstate allocation (interpreted code boxes every double), so the strict check
    measures after 3,000 warm-up frames.
- **Perf.** Frame cost (stage layers, callouts, all eight panels) over 1,500 frames of the
  stress burst. p50 and p95 are divided by a fixed calibration workload timed in the same
  process, so runner speed largely cancels out. The gate fails at 30% above the CI baseline;
  run-to-run spread here was 4% (p50) and 6% (p95).
- **Size.** size-limit measures every shipped JS file (`dist/assets/*.js`, workers included),
  gzip: 188.5 kB against 300 kB. The injected 300 kB of random data takes it to 498 kB.

## Acceptance criteria
- [x] AC1: all gates run in CI.
      - Size: `test` (Ubuntu), every PR.
      - Allocation: `test`, Ubuntu and Windows, every PR.
      - Visual: the `visual` job, every PR.
      - Perf: the `gates` job, every PR; and `nightly.yml`.
- [x] AC2: each gate fails on an injected regression of its type, in CI.
      - Size: injected bloat rejected (locally 498 kB; CI runs 38462556161 and 38463117924).
      - Allocation: injected 2 kB-per-frame leak rejected (both runs; locally it retained
        2,176,872 bytes).
      - Perf: injected 2 ms per frame rejected (run 38463117924, calibrated p50 ratio 0.258
        against the baseline's 0.0496).
      - Visual: injected 1 px panel shift rejected (run 38463117924). The same run passed the
        six screenshots against the baselines from the earlier run, on a fresh runner: the
        rendering is deterministic.

## Evidence
- Tests: web 225 (+2 allocation). The perf gate runs separately (`pnpm --filter @repro/web perf`).
- Local, clean:
  - flat heap: −85 kB over 1,000 frames;
  - stage allocation: 24.7 kB per frame (budget 40 kB);
  - size: 188.49 kB gzip;
  - perf: passes against a local baseline and fails with injected work.
- CI run 38463117924: all jobs passed, including `visual` (compare plus self-test) and `gates`
  (size, allocation and perf self-tests, plus the perf gate against the baseline).
- Runner variance: the calibration workload took 5.46 ms on the baseline's runner and 8.86 ms on
  a later one. The calibrated ratio is what makes one baseline usable across runners.

## Deviations from spec
- The roadmap's "frame() ×1000 with flat heap" is met as stated. The stricter per-frame
  allocation check is skipped on runtimes whose V8 does not expose `total_allocated_bytes`
  (`@types/node` 24 does not declare it).
- The visual job and the gate self-tests are new CI jobs, but they are not yet *required*
  checks. Adding them to branch protection is an owner setting.

## Known gaps
- Visual baselines are Linux/SwiftShader only (ADR-0009). Windows developers rely on the
  render-model goldens and the browser checks.
- The perf gate measures CPU work, not GPU time. GPU timing in CI would be SwiftShader's software
  rasterizer, not a meaningful frame budget; the in-browser bench (`docs/perf/`) covers the GPU.
- Updating visual baselines after an intended change: delete the affected PNGs and push. The
  job regenerates them and fails until they are committed.

## Dependencies added
- `@playwright/test` 1.64.0 (Apache-2.0), the version verified in research/05 and
  IMPLEMENTATION_PLAN; npm registry: published 2026-10-07.
- `size-limit` 14.2.0 and `@size-limit/file` 14.2.0 (MIT); npm registry: published 2026-10-07.
- CI image `mcr.microsoft.com/playwright:v1.64.0-noble`, pinned by index digest
  `sha256:06a9939e…971f`.
- `actions/upload-artifact` v7.0.2, pinned to commit `cf430e03…`.

## Research notes
None.

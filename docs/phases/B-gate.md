# Stage B gate — Cockpit on fixtures

| | |
|---|---|
| **Phases** | B01–B14 (B13 added before the gate, B14 at the owner's review) |
| **Release** | `v0.2.0` (tagged once the owner confirms the re-checked side-by-side) |
| **Gate date** | 2026-10-14 (re-opened and re-checked the same day) |

## Stage acceptance criteria
| Criterion (ROADMAP Gate B) | Result | Evidence |
|---|---|---|
| Side by side with the reference frame at 6 s, it reads as the same visual family | **failed at the owner's review**; re-checked after B14 (judgement, for the owner to confirm) | The first check failed on the stage, and B13 fixed its geometry. The owner's review then found that the stage still did not match, using a sharper copy of the reference (1080×1350). B14 measured that copy and rebuilt the stage composition to it (see "Re-opened" below). The side-by-sides are kept locally, because the reference is third-party media; the after-B14 CI baselines are in `apps/web/e2e/__screenshots__` |
| The reference log replays at ×1 at 60 fps on a mid laptop (measured, method recorded) | partial | Measured with the whole cockpit running (stage, panels, DOM) on an **integrated GPU** (Intel UHD, Chromium 152): demo run at ×1, 1920×1080, DPR 1.75, 2,867 frames, p50 16.7 ms, p95 17.0 ms, 1.85% of frames over 25 ms (host jitter, as in every bench). Re-measured after B14 on the production build at 1440×900, DPR 1.75: 3,081 frames, p50 16.7 ms, p95 17.0 ms, 1.14% over 25 ms, stage CPU p95 0.7 ms. The CPU (i7-14650HX) is stronger than a mid laptop's; a run on a mid laptop is still owed (owner, see gaps) |
| Scrubbing and all speeds work | pass | B10: playing at 60 fps to four checkpoints equals a fresh scrub at ×1 and ×16 (stage render models, pinned on both OSes); panels draw identically for equal versions at ×1, ×16 and reduced motion. Transport tests; browser checks of Space, ×16 and Reduce motion |
| All panels are driven only by events | pass | Every panel is a pure `view(t, cursor, motion)` over the event store plus `draw`, with golden draw-call recordings; the app replays recorded logs only. Focus is UI state passed in, not read from elsewhere |
| Visual-regression, allocation and bundle-size gates are active in CI | pass | B12: `visual` (Playwright, SwiftShader, pinned image), the allocation test in `test` (both OSes), size-limit in `test`, and the perf gate (`gates`, nightly). Each rejected an injected regression in CI run 38463117924 |

## Re-opened (B14)
At the gate review the owner judged that the cockpit still did not look like the reference video,
and supplied a sharper copy of it (1080×1350 at 60 fps).
Measured against it at the same stage height, three things differed:
- the web was a ball of straight spokes, because the ring's centre was on the stage;
- the ring was a thin band of sparse cards, not an opaque drum of full-width code cards;
- the right of the stage was nearly empty (mean luminance 9/255 against the reference's 41).

Underneath was the stage's shape: 2.76:1 against the reference's 1.15:1. B14 moved the panels
beside the stage on landscape screens and rebuilt the web, ring and streams from measurements of
the reference (`phases/B14-reference-parity.md`). The release was held: `v0.2.0` is tagged only
after the owner confirms the new side-by-side.

The SDLC quality bar "projections and store coverage ≥ 90%" (§5) had not been measured during
the stage. The gate added `pnpm coverage` and a CI step enforcing it (lines, statements and
functions ≥ 90% for `src/model/**`).

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest | 3.13 (`.python-version`) | 24 (`.node-version`) | pass | [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| windows-latest | 3.13 | 24 | pass | [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| ubuntu-latest + Playwright image (pinned by digest) | — | 24 | pass | `visual` job, [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| All of the above, after B14 | 3.13 | 24 | see the B14 PR | B14's PR checks, with the visual baselines regenerated in CI |

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 497; Vitest 319 after B14 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 238; in CI on Node 24 one web test is skipped, see gaps); 6 visual screenshots; the perf gate |
| Web code | after B14, 10,403 lines of TypeScript outside tests and 4,421 in tests, counting every `.ts`/`.tsx` file under `apps/web/src` (the same count at the first gate gives 9,624 and 4,033; the 8,885 first recorded used a narrower set) |
| Model coverage (`src/model/**`) | lines 99.15%, statements 96.96%, functions 98.43%, branches 84% |
| JavaScript, gzip (all shipped JS, workers included) | 192.87 kB of the 300 kB budget (188.96 kB before B14) |
| Frame time, demo ×1, whole app | p50 16.7 / p95 17.0 / p99 33.3 ms at 1920×1080, DPR 1.75, integrated GPU |
| Frame time, stress stage at full load | p95 16.9–17.0 ms at DPR 1 and 2, stage CPU p95 1.2–1.7 ms (`docs/perf/B10-motion-bench.json`) |
| Heap | flat over 1,000 frames of the stress burst (−96 kB after B14); stage allocation 19.1 kB per frame after B14, 24.7 kB before (local, V8 counter; budget 40 kB) |
| Flash safety | worst 333 ms window ≤ 43,648 CSS px² (half the WCAG area) at ×0.5–×16 on both fixtures; stream rays are flash-safe by construction (MAX blending, a 40 s wall-clock fade floor; ADR-0011 B14 note) |
| Accessibility | axe-core 4.14.0: 0 violations in jsdom (CI) and in Chromium including contrast |
| Decisions | 15 ADRs (0001–0015), all accepted |

## Retrospective
**Went well**
- Determinism paid off. Render-model pins agree across Ubuntu and Windows. "Scrub = play" became
  a test, not a hope, and the visual baselines held on a fresh runner.
- Property and gate tests found real defects:
  - a float32 lane cache (B07);
  - panels showing stale drawings between version steps (B08, found in B10);
  - a leak check blind to typed arrays (B12);
  - a residue layer that allocated 104 kB a frame (B13).
- Accessibility work changed the design for the better: WCAG contrast on text, opaque boxes over
  the stage, and an onset-budgeted flash governor.

**Slipped or surprised us**
- B04's first benchmark drew nothing (back-face culling). It was corrected openly, and benches
  now require lit pixels.
- Visual parity was only checked at the gate. The ring geometry had been copied from the
  portrait reference, and the stage did not read as its family until B13. Next stage: compare
  against the reference while building, not at the end.
- B13's parity "pass" rested on our own judgement of a low-bitrate copy, and the owner's review
  overturned it. B14 measured instead: circle fits for the geometry and per-region luminance for
  brightness. A judgement criterion now closes only after the owner has looked.
- A `git rebase` left the dev server serving stale CSS. That exposed an unbounded
  canvas-resize feedback loop, now clamped.
- jsdom cannot check contrast; the reference palette's `--text-dim` failed WCAG AA.
- Node 24 does not expose V8's allocation counter, so the strict allocation check runs locally
  only.

**Roadmap changes made during the stage (explicit edits)**
- B13 Visual parity, added before the gate (ROADMAP Stage B table and phase list).
- DESIGN.md changes, each recorded with its reason:
  - the execution lane shows A′ (B08);
  - the change×check index rows and relations (B09);
  - wall-clock motion, the flash governor and the transport (B10);
  - focus, the drawer, the accessible DOM, and `--text-dim` raised to `#868686` (B11);
  - landscape ring geometry, the card cap and the stream residue (B13).
- ADR-0011 gained implementation notes (B10). ADR-0015 was decided in B01 under the owner's
  delegation.
- The gate added the model-coverage step to CI (SDLC.md §5).

## Decisions for the owner
- Confirm the visual-family judgement from the new local side-by-side (B14). `v0.2.0` waits for it.
- The landscape layout (B14): the panels sit beside the stage in 4 rows × 2, so the stage keeps
  the reference's near-square shape. Portrait screens keep the reference's own arrangement.
- ADR-0011's B14 notes: stream rays are made flash-safe by MAX blending and a 40 s wall-clock
  fade floor instead of B13's 9% cap.
- ADR-0015 (the check model) was decided under delegation. ADR-0011's implementation notes:
  - over the cap, streaks are dropped rather than dimmed;
  - bundles aggregate at every speed.
- `--text-dim` is `#868686` instead of the reference's `#6e6e6e` (WCAG 1.4.3).
- Branch protection: make `visual` and `gates` required checks. Until then auto-merge can land a
  PR whose gate jobs fail.

## Carried-over gaps
| Gap | Owner phase |
|---|---|
| Manual 60 fps check of the demo at ×1 on a mid laptop (Gate B criterion measured on an integrated GPU with a strong CPU) | owner |
| `visual` and `gates` are not required checks | owner setting |
| Dependency graph disabled, so `dependency review` is off | owner setting |
| Dependabot #17 (`@types/node` 26: decline, CI runs Node 24) and #18 (uv_build floor 0.13: fine) | owner |
| The ubuntu-latest image moves to Ubuntu 26 from 2026-10-19 (runner notice). The perf baseline may need re-recording; the visual job is container-pinned | nightly will show; re-record if it fails |
| Card view and its semantic table | F05 |
| Index cells reached through the drawer, not grid keyboard navigation | backlog |
| Flash check is model-based (area bounds), not a frame-based luminance analysis | backlog (paper) |
| Raw diff text in the drawer (line ranges only; no artifacts yet) | D/E |
| Portrait and phone layout rule (portrait desktops now use the reference's stacked arrangement; phones still the narrow rule) | backlog |
| The reference's camera moves (it pans and zooms at times, for example from about 7.2 s to 9.5 s) are not reproduced: the stage keeps its home view | backlog, if wanted (an event-driven "tour" camera) |
| Strict per-frame allocation check skipped on Node 24 (no V8 counter) | when CI moves to a Node with it |
| Stage A carried gaps (uv `required-version` floor, schema packaging, fixtures, tracer overhead) | as in `A-gate.md` |

## Research log entries
`docs/paper/LOG.md`:
- 2026-10-13: B01 (check model and synthetic reference run), B04 (rendering cost) and the B04
  correction.
- 2026-10-14: B10 (motion safety as a bounded onset budget), B12 (quality gates that prove they
  can fail), B13 (geometry transfer from a portrait reference; ×1 replay at 60 fps).

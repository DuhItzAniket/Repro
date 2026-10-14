# Stage B gate — Cockpit on fixtures

| | |
|---|---|
| **Phases** | B01–B15 (B13 added before the gate, B14 and B15 at the owner's reviews) |
| **Release** | `v0.2.0`, tagged after the owner approved the look |
| **Gate date** | 2026-10-14 (re-opened at the owner's review and closed again the same day) |

## Stage acceptance criteria
| Criterion (ROADMAP Gate B) | Result | Evidence |
|---|---|---|
| Side by side with the reference frame at 6 s, it reads as the same visual family | **pass**: the owner approved the look on 2026-10-14, after B14 and B15 | The first check failed on the stage, and B13 fixed its geometry. The owner's review then found that the stage still did not match, using a sharper copy of the reference (1080×1350). B14 measured that copy and rebuilt the stage composition to it over seven owner reviews, and B15 added the owner's settings and whole-wheel view (see "Re-opened" and "Closed" below). The side-by-sides are kept locally, because the reference is third-party media; the CI baselines are in `apps/web/e2e/__screenshots__` |
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

## Closed (B14, B15)
B14 took seven owner reviews, each checked against frame-by-frame captures of the reference and
of the app: strands that follow the wheel and stay attached to their nodes, bunches from many
nodes converging on a section, and lines outside the wheel only where strands hit, bouncing back
into the rim. The last review also asked for settings, wider node spread and a whole-wheel view,
which became B15. On 2026-10-14 the owner approved the look ("current looks are good"), with
further changes left to later phases, and `v0.2.0` was tagged.

The SDLC quality bar "projections and store coverage ≥ 90%" (§5) had not been measured during
the stage. The gate added `pnpm coverage` and a CI step enforcing it (lines, statements and
functions ≥ 90% for `src/model/**`).

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest | 3.13 (`.python-version`) | 24 (`.node-version`) | pass | [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| windows-latest | 3.13 | 24 | pass | [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| ubuntu-latest + Playwright image (pinned by digest) | — | 24 | pass | `visual` job, [#25 checks](https://github.com/DuhItzAniket/Repro/pull/25/checks) |
| All of the above, after B15 | 3.13 | 24 | pass | [CI run 38544368141](https://github.com/DuhItzAniket/Repro/actions/runs/38544368141) on [#27](https://github.com/DuhItzAniket/Repro/pull/27): 8 visual baselines from run 38536427818, checked by eye |
| All of the above, after B14 | 3.13 | 24 | pass | [CI run 38532608296](https://github.com/DuhItzAniket/Repro/actions/runs/38532608296), after the seventh review: baselines from run 38532085767, checked by eye; the visual self-test rejected its injected shift (first green after B14: [run 38525044683](https://github.com/DuhItzAniket/Repro/actions/runs/38525044683)) |

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 497; Vitest 347 after B15 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 266; in CI on Node 24 one web test is skipped, see gaps); 8 visual screenshots; the perf gate |
| Web code | after B15, 11,403 lines of TypeScript outside tests and 5,084 in tests (10,846 and 4,643 after B14), counting every `.ts`/`.tsx` file under `apps/web/src` (the same count at the first gate gives 9,624 and 4,033; the 8,885 first recorded used a narrower set) |
| Model coverage (`src/model/**`) | lines 99.15%, statements 96.96%, functions 98.43%, branches 84% |
| JavaScript, gzip (all shipped JS, workers included) | 196.0 kB of the 300 kB budget (188.96 kB before B14) |
| Frame time, demo ×1, whole app | p50 16.7 / p95 17.0 / p99 33.3 ms at 1920×1080, DPR 1.75, integrated GPU |
| Frame time, stress stage at full load | p95 16.9–17.0 ms at DPR 1 and 2, stage CPU p95 1.2–1.7 ms (`docs/perf/B10-motion-bench.json`) |
| Heap | flat over 1,000 frames of the stress burst; stage allocation 3.4 kB per frame after B15 (fewer bunches fit at the burst in the arc view), 11.7 kB after B14, 24.7 kB before (local, V8 counter; budget 40 kB) |
| Flash safety | worst 333 ms window ≤ 43,648 CSS px² (half the WCAG area) at ×0.5–×16 on both fixtures; the dim strands and the lines outside the wheel are flash-safe by construction (MAX blending at no more than 0.32; ADR-0011 B14 note); viewer settings stay inside the bound in every view (ADR-0011 B15 note) |
| Accessibility | axe-core 4.14.0: 0 violations in jsdom (CI, with the settings menu open since B15) and in Chromium including contrast |
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
- Each owner review became tests, not only pixels: the bounce law, lines only from the hit
  section, strands attached to their nodes, render models independent of the viewer's look.
  The CI screenshots of B15 then caught a real defect (a callout cut off in the whole-wheel view).

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
- Reference parity took seven owner reviews in B14. The reviews were about motion (what moves
  with what), which stills cannot show; captures of the app and the reference frame by frame
  were what settled each one.
- A visual request had a flash-budget cost: spreading the nodes over the whole disc (B15) left
  the default view with fewer nodes and fewer admitted bunches (13 against 20 on the demo at
  ×1). The owner kept it.

**Roadmap changes made during the stage (explicit edits)**
- B13 Visual parity, added before the gate (ROADMAP Stage B table and phase list).
- B14 Reference parity II and B15 Stage settings and the whole wheel, added at the owner's
  reviews after the gate was first passed.
- DESIGN.md changes, each recorded with its reason:
  - the execution lane shows A′ (B08);
  - the change×check index rows and relations (B09);
  - wall-clock motion, the flash governor and the transport (B10);
  - focus, the drawer, the accessible DOM, and `--text-dim` raised to `#868686` (B11);
  - landscape ring geometry, the card cap and the stream residue (B13);
  - the side layout, the measured ring, the chord-layout web, bunches of strands and the lines
    outside the wheel; streaks and the residue removed (B14);
  - the view and the viewer's look, nodes over the whole disc (B15).
- ADR-0011 gained implementation notes (B10, B14, B15). ADR-0015 was decided in B01 under the
  owner's delegation.
- The gate added the model-coverage step to CI (SDLC.md §5).

## Decisions for the owner
- Approved on 2026-10-14: the look after B14 and B15, including the landscape layout (panels
  beside a near-square stage) and the run's nodes over the whole disc.
- ADR-0011's B15 notes: viewers can only dim the uncounted dim lines; the governor counts
  bullets and mesh flares at the viewer's width, and decides for the view on screen.
- ADR-0011's B14 notes: the dim strands and the lines outside the wheel are flash-safe by MAX
  blending at no more than 0.32, so the governor counts only bullets, node rings and bars, and
  aggregates one bunch per section of the wheel per window.
- ADR-0015 (the check model) was decided under delegation. ADR-0011's implementation notes:
  - over the cap, bunches are dropped rather than dimmed (B10: streaks, removed in B14);
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
  can fail), B13 (geometry transfer from a portrait reference; ×1 replay at 60 fps), B14
  (measuring a visual reference instead of eyeballing it), B15 (viewer settings inside a flash
  bound, and the cost of spreading the nodes).

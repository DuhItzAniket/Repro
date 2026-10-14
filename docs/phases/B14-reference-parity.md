# B14 — Reference parity II: the stage composition

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B13 |
| **Branch / PR** | `phase/B14-reference-parity` · [#26](https://github.com/DuhItzAniket/Repro/pull/26) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Meet Gate B's first criterion after the owner's review: side by side with the reference, the
stage reads as the same visual family. Added to the roadmap at that review, which re-opened the
gate and held the `v0.2.0` tag.

## Why this phase exists
At the gate review the owner judged that the cockpit still did not look like the reference video,
and supplied a sharper copy of it (1080×1350 at 60 fps). Measured against that copy at the same
stage height, after B13:

| Element | Reference | Repro after B13 | Cause |
|---|---|---|---|
| Web | a uniform hairball of long, gently curved lines | a ball of straight spokes with bright hubs | the ring's centre was on the stage, so the whole web disc showed, and a force layout draws short spokes into its hubs |
| Ring | an opaque drum about 0.22·H thick: bezel, ruler combs, code cards from rim to rim | a thin band of sparse cards with gaps | band proportions and card layout |
| Streams | a dense field of radial rays; mean luminance 41/255, 64–83 next to the ring | nearly empty; mean 9/255 | the residue's 9% cap; few, short traces |
| Stage shape | about 1.15:1 | 2.76:1 (1440×522 at 1440×900) | panels beneath the stage on a landscape screen |

Luminance is the mean of 8-bit encoded grey over the same region of each stage (the reference's
frames at 3, 6 and 12 s; Repro's CI baseline at 30.5 s).

## Scope
- Layout (`computeLayout`): three modes. **side** (landscape): the stage on the left, near
  1.15:1, and the panels in 4 rows × 2 beside it (904×844 and 256×201 at 1440×900); the drawer
  over the panels. **stacked** (portrait): the reference's arrangement. **narrow**: unchanged.
- Ring geometry measured on the reference: inner rim radius 1.02·H, 3 o'clock point at 0.46·W,
  band 0.215 of the inner radius (`stage/geometry.ts`: `ringBand`, `outerRadius`, `webRadius`).
- Ring:
  - an opaque band of 120 pieces under the cards;
  - one card per file spanning the band, in a card shader with bezel, groove and seams;
  - rims and ruler combs in the tick layer;
  - cards from events, laid out like the reference's: header, numbered rows (changed rows in
    `--flag`), a neighbour dot grid and labels (`content.ts`, `atlas.ts`, column-packed atlas at
    up to 2 device px per band unit);
  - natural card angles (`UNIT_ANGLE`).
- Web:
  - a chord layout from the force simulation's angular order (`force.ts`);
  - edges as arcs, only their pieces on the stage (`web/arcs.ts`);
  - tests as squares (`nodeLayer`);
  - bundles as brushes that land on their function's card at the inner rim.
- Streams: lanes ±24° with ±4.9° per event; rays from the outer rim, brightest there, growing
  out over 900 ms (`growMs`), MAX-blended, with a 40 s wall-clock fade floor (`fadeWallMs`).
- Renderer: a `blend: "max"` layer option (premultiplied output, `MaxEquation`), `uGrowMs`,
  `uBand`, and no end overlap between chained segments.
- The focus highlight split into a web part, drawn under the ring, and a ring part, drawn on top.
- Docs: DESIGN.md (orientation, layout, web, ring, streams, motion), ADR-0011 note, ROADMAP,
  CHANGELOG, `docs/paper/LOG.md`, the Gate B record, `reference/README.md`.

## Design notes
- **Measure the reference.**
  - Geometry: circles fitted through three points on each rim of the 6 s frame give the inner
    radius as about 957 px on its 935 px stage, the centre about 461 px left of it, and the band
    about 205 px. Rays and web brightness were compared by region statistics, not by eye.
  - The reference also pans and zooms at times (for example from about 7.2 s to 9.5 s). Repro
    keeps the home view, because its motion must map to events.
- **Why the panels moved.** The reference's look needs a near-square stage: the ring's arc spans
  its height, the web fills the inside of the arc, and the rays fill the right. No radius
  reproduces that on a 2.76:1 strip. The ring is either flat or the web is a visible ball.
  Beside the stage, the panels are about the reference's panel size (256×201 against its
  258×165). Portrait screens keep the reference's own arrangement.
- **A hairball from real edges.** Modules sit evenly on a circle under the band, in the order the
  existing force simulation (d3-force, unchanged) gives their angles, so connected modules are
  neighbours. With the centre off-screen, the 1,446 import edges of the demo become long arcs
  crossing the stage. No line is invented; the layout changed, not the data. Hub modules (130
  importers for `_util`) sit on the same circle, so their edges converge under the band or off
  the stage.
- **Cards from events, in the reference's layout.** v1 events carry no file contents, so the rows
  are the file's symbols with their line numbers, then its imports. The dot grid is the file's
  neighbours, bucketed by module path order, standing in for the reference's dot matrices. Each
  card keeps the same scale along the arc as across the band, so text is not stretched.
- **Bright rays, safe by construction.** B13 capped the residue at 9% luminance, so it read as
  empty. B14 lets rays reach 0.92 at the rim and makes them unable to flash:
  - MAX blending bounds a pixel by its brightest ray;
  - a ray fades over at least 40 s of wall-clock time, so a pixel loses at most 0.023 a second;
  - a 10% fall in relative luminance needs at least 0.05, which takes over 2 s.

  A first, additive version was not safe in principle: many overlapping rays fading together at
  ×16 could lose 10% in under a second. Both bounds are unit-tested against the sRGB curve.
- **Joints.** Segments used to extend one device pixel past both ends for anti-aliasing. Chained
  into arcs and bundles, the overlaps added up into bright dots at every joint, which showed as a
  ladder across the bundles. Segments now end exactly at their endpoints, with anti-aliasing
  across them only.
- **Pins changed, explained.** Every stage pin changed because every stage layer's geometry did:
  ring, streaks, web (and its layout digest), and the B10 stage golden. The B04 proxy-layer pins
  did not change once their test was given a fixed stage (B13's geometry) instead of reading the
  cockpit layout, which shows the proxy layers themselves are untouched. The panel goldens did
  not change. Behavioural properties hold unchanged:
  - scrub = play at ×1 and ×16;
  - bundles and streaks are pure functions;
  - the governor's worst window stays within the cap at ×0.5–×16 on both fixtures.

## Acceptance criteria
- [x] AC1: the side-by-side reads as the same visual family (judgement; the owner confirms).
      Measured at the same stage height:

      | Region (mean, 8-bit) | Reference (3, 6, 12 s) | After B13 | After B14 (30.5 s, end) |
      |---|---|---|---|
      | Web | 42–43 | 48 (a starburst) | 37 |
      | Rays | 33–42 | 9 | 29 |
      | Rays next to the ring | 55–83 | — | 48–54 |

      Comparison images stay local, because the reference is third-party media.
- [x] AC2: all tests and gates pass, with every changed pin explained:
  - `@repro/web` 238 tests (6 new for the rays);
  - bundle 192.87 kB of 300 kB;
  - frame-cost ratios p50 0.0296 and p95 0.2474, against the baseline's 0.0496 and 0.2749;
  - heap flat (−96 kB over 1,000 frames);
  - stage allocation 19.1 kB per frame, within the 40 kB budget.

  The visual baselines are regenerated in CI and checked by eye.
- [x] AC3: flash safety holds. The governor's worst-window test passes at every speed, and the
      rays' bound is unit-tested.

## Evidence
- The demo at ×1 with the whole cockpit, production build, 1440×900, DPR 1.75, integrated GPU
  (Intel UHD, Chromium 152, ANGLE D3D11):
  - 3,081 frames, p50 16.7 ms, p95 17.0 ms, p99 33.1 ms, 1.14% over 25 ms;
  - stage CPU p95 0.7 ms;
  - 11,789 instances in 7 draw calls (edge pieces 6,466, ticks 4,292).
- Tests: web 238; render-model pins for ring, streaks, web, layout and the stage golden updated;
  the proxy pins unchanged.

## Deviations from spec
- DESIGN.md's layout (panels beside the stage on landscape screens), dependency web (chord layout,
  arcs), ring (drum, card layout) and streams (rays) sections are rewritten, each with its
  reason. ADR-0011 gains B14 implementation notes. The d3-force simulation stays, now as the
  source of the order around the circle.

## Known gaps
- The web's density follows the repo: a small graph draws fewer arcs than the reference shows.
- Camera moves and the reference's moving chains of small circles are not reproduced; no events
  stand behind them.
- At 256 px, the Dispatch panel's second column of agent bars reaches the panel's edge.
- Portrait phones still use the narrow rule.

## Dependencies added
None.

## Research notes
`docs/paper/LOG.md`, 2026-10-14 · B14.

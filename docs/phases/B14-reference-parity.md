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
  - the run's nodes (symbols and tests) in front, as small circles (`nodeLayer`);
  - bunches of strands (bundles): one dim line from each node that reaches the function, each
    with a white bullet, converging on one ring section; they stay attached to their nodes and
    follow that section as it turns, then fade (1 s), as the owner's second to fifth reviews
    asked (below). Membership comes from `ReachIndex` (`web/reach.ts`);
  - arcs kept inside the web's circle (`web/arcs.ts`).
- Ring rotation: one turn per 24 s of wall-clock time at any replay speed (`RING_TURN_MS`), the
  reference's measured speed.
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

## Second owner review (same day)
The owner found the stage better but still not like the video: its strands move along with the
section of the wheel they shoot to, and their tails move from their origin, before disappearing.
Studied frame by frame at 30 fps (5.8–6.4 s):
- a strand lives about 0.3–0.35 s. Its head shoots in from the web for about 0.1 s and a short
  bar appears on the rim. Its tail then slides along the path into the bar while the bar moves
  with the ring, and it is gone;
- the ring itself turns fast. Cross-correlating the card column at 3 o'clock between frames gives
  a steady 5–17 px per frame at 30 fps, about 280 px/s, or about 15° a second (a turn in about
  24 s, close to the 22 s loop). The web does not move. Repro's ring drifted about 2.8° a second
  (one card per 2 s), so strands landing on it barely moved.

Changes:
- the ring turns once per 24 s of wall-clock time, also at ×4 and ×16 (it scaled with the replay
  speed before);
- strands shoot in over 30% of their life and land on their card at this frame's ring angle;
- their curves arrive along the ring's radius and sweep up into the rim from the side the cards
  are moving towards, like the reference's. Before, they bowed to a random side, which drew
  "eye" shapes where two strands met one card.

## Third owner review (same day)
"Still no changes": the owner described the strands as coming from the nodes of a network. They
fire from those points towards the wheel and stay attached to them, while their other end
follows the section of the wheel they shot towards. The second pass had the tail detach and
slide in, and the origins were invisible: symbols and tests sat on a circle under the rim, and a
strand started wherever its reach was clamped.

Changes:
- symbols and tests sit in front, spread across the sector of the web the stage shows
  (`FRONT_ANGLE`, `FRONT_RADII`), in the simulation's order, and are drawn as small circles;
- a strand fires from its test's node (the node lights up), stays attached to it, lands within
  10° of the node's bearing (`AIM`, `aimRange`), follows that ring section by at most the ring's
  drift over its life (`FOLLOW`, `landingAngle`), and fades (`strandFade`). It lives 500 ms;
- the flash governor bounds each strand from its node to the far end of the arc it can land on
  (`strandReach`). Aiming near the node's bearing keeps strands short enough to fit the cap: on
  the demo it admits 24 of 190 strands at ×1, with 2–4 visible at once during the trace burst,
  against 8 when strands could aim across the whole visible arc.

## Fourth owner review (same day)
The owner pointed out that a bunch of strands came from a single node, which is wrong. There are
many nodes scattered inside the circle, and from each, one single strand emerges and shoots
towards the wheel. In the video these strands are really dim lines, with a bullet-like white
light shooting along each from its origin node to the wheel, and the rest of the mesh is
curvier. At 60 fps (5.85–6.1 s) the reference's bright part is a short stretch travelling along
a curve to the rim in about 0.1 s.

Changes:
- one strand per event, a single line, not a sheaf of 6–9 curves (`drawStrand`);
- it fires from the test's node (`strandOrigin`). Each test is its own node, so a burst fires
  from many nodes, and the governor aggregates one strand per node per window;
- the strand is dim (alpha 0.32) and revealed behind a white bullet (80 px, 2 px wide) that
  travels from the node to the ring in the first 40% of a 1 s life (`bulletAt`, `TRAVEL`). The
  node lights up while the bullet is in flight, and a bar flashes on the rim where it hits;
- the front sector is wider (±28°, radii 0.5–0.86), so nodes scatter across the visible web;
- the mesh's arcs bow by 25–60% of their length (was 18–42%) and are dimmer (imports alpha 0.17),
  so the dim strands read over them;
- the cap now admits 31 of 190 demo strands at ×1 (24 before).

## Fifth owner review (same day)
"Almost there": a single strand went from one node to one section. It should be a bunch, with
strands from several nodes shooting together towards one section of the wheel. And some strands
were going outside the wheel.

Changes:
- a bunch fires per event at the function's ring card. One strand comes from each node that
  reaches the function: its tests (by `covers` edges and trace samples) and its callers (by
  `calls` edges). The membership is real data from the log up to that event (`ReachIndex`, keyed
  by store index, so it is prefix-pure). `parse_date` has 7 tests and 8 callers, capped at 12;
- the strands converge side by side on one bar, ordered by their nodes' bearings so they do not
  cross (`sortByBearing`), each starting up to 6% of the life later (`memberLife`);
- the governor bounds a bunch by the sum of its strands' longest lengths plus its bar, and
  aggregates one bunch per function per window. The demo admits 12 bunches at ×1;
- "going outside the wheel": with the strongest bows, 82 of the 1,500 mesh arcs bowed out past
  the ring's outer rim into the streams. Each arc's control point is now kept inside the web's
  circle, so the curve is too; the farthest point of any arc is now 1.1 r, under the band
  (outer rim 1.215 r).

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
  - `@repro/web` 249 tests (17 new for the rays, strands, bunches, reach and front nodes);
  - bundle 193.98 kB of 300 kB;
  - frame-cost ratios p50 0.028–0.033 and p95 0.245–0.272 over three runs, against the
    baseline's 0.0496 and 0.2749 (one earlier run on a busy host read 0.376 and failed; the gate
    allows 30%);
  - heap flat (−84 kB over 1,000 frames);
  - stage allocation 24.1 kB per frame with the bunches (19.1 kB before them), within the 40 kB budget.

  The visual baselines are regenerated in CI and checked by eye.
- [x] AC3: flash safety holds. The governor's worst-window test passes at every speed, and the
      rays' bound is unit-tested.
- [x] AC4 (second and third reviews): strands fire from visible nodes, stay attached to them,
      and follow the ring section they land on, and the ring turns at the reference's speed.
      Unit-tested:
  - a strand starts at its test's node at every age (attached), and the node's ring shows
    while its bullet is in flight;
  - a bunch fires one strand from each of its nodes, each from its own point, and lands on one
    bar as long as the bunch is wide; its nodes are ordered by bearing;
  - the reach index collects tests and callers, never the function itself, and a bunch uses only
    nodes that had joined by its event (agrees with an index built from the log prefix);
  - every mesh arc stays inside the web's circle;
  - landing bars lie on the inner rim, within the landing arc or as far as they have followed;
  - the aim, follow, bullet and fade laws; the reach bound over the whole landing arc;
  - the run's nodes are in the front sector, evenly spread, a file's members together;
  - the ring's turn per wall-clock second is the same at ×0.5–×16.

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

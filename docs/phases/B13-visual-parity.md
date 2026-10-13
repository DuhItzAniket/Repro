# B13 — Visual parity with the reference

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B12 |
| **Branch / PR** | `phase/B13-visual-parity` · [#24](https://github.com/DuhItzAniket/Repro/pull/24) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Meet Gate B's first criterion: side by side with the reference frame at 6 s, the cockpit reads
as the same visual family. Added to the roadmap before the gate, because the gate check failed.

## Why this phase exists
The gate's side-by-side (the reference frame at 6 s next to CI's 1440×900 baseline at 30.5 s)
showed two things.
- The header and all eight panels read as the reference's.
- The stage did not:
  - the ring was a thin band of illegible cards, 147 cards of about 12 px with 3.4 px type;
  - the right 60% was nearly empty;
  - the web was a compact ball.

The cause was geometry. DESIGN.md's ring rule (centre 0.15·W, radius 0.55·H) was measured on the
reference's portrait stage. Applied unchanged to a landscape stage (2.76:1), it gives a small
circle.

## Scope
- `computeLayout`: radius 0.9·H, with the 3 o'clock point at 0.46·W (centre x = 0.46·W − r).
- Ring:
  - content band r − 72…r + 10, metadata r + 12…r + 50, web inset 80 px;
  - at most 64 cards (was 160);
  - atlas cells 96×48 and 48×48, 5.2-unit type on a 6-unit line;
  - non-blast ink 0.72 (was 0.55).
- Streams: lanes ±28° (was ±64°); tails trail 160 ms of head speed (was 110 ms).
- `stage/streams/residue.ts`: the stream residue. The segment shader gains an optional linear
  fade (`Recency.fadeMs`, uniform `uFadeMs`), mirrored in `recencyFactor`.
- DESIGN.md (layout, ring, streams), ROADMAP (this phase), ADR-0011 note.

## Design notes
- **Geometry from the reference, not its numbers.** What the reference shows is an arc spanning
  the stage height with its 3 o'clock point near mid-width, a band of large, dense text cards,
  and streams filling the right. On a landscape stage that means a larger radius relative to
  the height. Only about 67° of the circle is on screen at 1440×900, so 64 cards give about a
  dozen visible cards, each about 40 px tall: close to the reference's proportions.
- **Lanes inside the visible arc.** With the larger ring, ±64° lanes would start off-screen.
  ±28° keeps every lane on the visible arc and makes streams near-horizontal, like the
  reference's.
- **Residue instead of brighter streaks.** The reference's right half is a dense field of
  horizontal streaks. Brighter or more numerous moving streaks are exactly what the flash
  governor (ADR-0011) limits, and should. The residue reaches the look honestly:
  - each streaming event leaves one faint, static trace along its lane;
  - it adds at most 9% luminance, under WCAG 2.3.1's 10% flash threshold, and never moves;
  - it fades over 90 s of run time, so the bands show where the run has been busy.
- **Residue cost.** A first version rewrote up to 4,096 traces per frame and raised the stage's
  per-frame allocation from about 25 kB to 104 kB, which B12's allocation gate caught. The final
  version works like the edge layer:
  - each trace is written once, with its event's time as its appearance time;
  - the shader hides it before then and fades it after;
  - so the layer is append-only, free per frame, and trivially pure.
- **Pins changed, explained.** Five render-model pins changed: ring, streaks, web, proxies, and
  B10's stage pin. With the old geometry constants and atlas cells restored temporarily, the
  first four matched their B05–B10 values exactly, so nothing changed except what was
  intended. The B10 stage pin also includes the new residue layer. The panel goldens did not
  change.
- **Flash governor.** The larger ring makes edges and bundles larger, so the governor admits
  somewhat fewer at the same cap, and the bound still holds at every speed:

  | Fixture | Speed | Worst window (px²) | Streaks | Bundles | Edge flares |
  |---|---|---|---|---|---|
  | demo | ×1 | 43,647 | 537 / 540 | 50 / 190 | 787 / 1,500 |
  | demo | ×16 | 43,648 | 277 / 540 | 6 / 190 | 135 / 1,500 |
  | stress | ×1 | 43,648 | 2,466 / 5,789 | 14 / 192 | 1,866 / 10,000 |
  | stress | ×16 | 43,647 | 530 / 5,789 | 3 / 192 | 209 / 10,000 |

## Acceptance criteria
- [x] AC1: the side-by-side reads as the same visual family. The ring is a large arc of legible
      text cards, the web fills the left, and the right shows dense horizontal streams.
      The comparison image stays local (the reference is third-party media); this is a judgement
      the owner confirms at the gate.
- [x] AC2: all B01–B12 tests and gates pass. Web 225 tests; the allocation gate (stage at about
      25 kB per frame again); scrub = play; the flash bound at every speed. Visual baselines were
      regenerated in CI run 38464807432 and checked by eye: stage, focus with drawer, reduced
      motion, and the early graph-only moment.

## Evidence
- In the browser (1440×900, `?test`):
  - lit stage pixels 294,875 / 303,803 / 315,330 at 24.5 / 30.5 / 48.7 s;
  - at the end, 128 card instances (64 files × 2), 704 ticks and 540 residue traces.
- Tests: web 225 (5 pins and 2 tests updated for the new geometry and card cap).

## Deviations from spec
- DESIGN.md's ring rule changes (geometry, band, card count) and the residue is new. Both are
  recorded in DESIGN.md with the reason.

## Known gaps
- Portrait or very narrow viewports use the same rule; on a phone the ring dominates. The
  narrow layout already scrolls the panels; a portrait rule is future work.
- The reference's web shows long curved lines; ours is a force-directed graph with straight
  edges. The family resemblance holds, but the lines are different.

## Dependencies added
None.

## Research notes
None.

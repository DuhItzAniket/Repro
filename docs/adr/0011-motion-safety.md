# ADR-0011: Wall-clock-clamped motion and a flash governor

- **Status:** accepted (approved by the project owner on 2026-10-13)
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in B10)

## Context
DESIGN.md defines motion durations in run time (bundle fade 1.2 s, streak 600–1400 ms).
Replay runs at up to ×16, so a 1.2 s fade becomes 75 ms of wall-clock time. White bundles on
`#080808` are large luminance changes. WCAG 2.2 SC 2.3.1 (Level A) allows no more than three
general flashes per second over a large area. SC 2.2.2 (Level A) requires a way to pause
auto-updating content, with no five-second exception (research/05 §7).

## Decision
1. Visual durations are expressed in **wall-clock** time and clamped to the DESIGN.md ranges,
   while staying pure functions of `(event, t, speed)`.
2. A **flash governor** caps the total bright area that may rise within any 333 ms window.
   Above the cap, bundles aggregate (one per edge per window) and streak intensity is reduced.
3. One global **pause** (Space) freezes the presentation clock. Ingestion continues.
4. `prefers-reduced-motion` keeps DESIGN.md's rule: no streaks or bundles, and instant state
   changes. An in-app toggle mirrors it.

## Consequences
At ×4 and ×16 the stage shows aggregated activity rather than every event. That is the honest
rendering at those speeds anyway. A unit test checks that the burst fixture at ×16 never exceeds
the governor threshold.

## Implementation notes (B10)
These record how B10 built the decision. They add precision and change no scope; flagged for the
owner at the Stage B gate.
- **Threshold.** The WCAG 2.2 Understanding document for SC 2.3.1 gives the combined flashing
  area as 341 × 256 CSS px, or 87,296 CSS px², at 1024 × 768 [V: research/05 §7, source 55]. The
  governor's cap is half of that, 43,648 CSS px², as a margin for estimation error. It applies to
  the whole stage rather than per 10° field, which is stricter.
- **Why an onset cap bounds flashing.** If at most B px² can rise in any 333 ms, at most 3B can
  rise in any second, so the area that flashes more than three times a second is at most 3B/4.
- **Areas** are upper bounds from each element's own geometry: line length and width plus 2 px of
  anti-aliasing fringe. Streaks use their longest visible stretch; bundles their control polygon
  widened by the curves' spread. A unit test checks the streak bound at every age.
- **Over the cap** a streak is not drawn. Decision 2 says its intensity is reduced; it is reduced
  to zero, because under WCAG's 10% rule a dimmed but visible streak still counts in full once
  streaks overlap additively. Edges and markers appear without their flare: a rise that never
  falls is not a flash.
- **Aggregation** (one bundle per graph edge per window) applies at every speed, not only ×4 and
  ×16, so repeated bundles on one edge do not crowd out others within the cap.
- **Purity.** Decisions are made greedily in log order and depend only on the events up to each
  onset, the speed and the stage geometry. They are therefore the same when playing or
  scrubbing, and are never revised as events arrive.
- **Measured** (unit-tested, with B10's stage geometry; B13's larger ring changes the counts but
  not the bound): every 333 ms window at ×0.5, ×1, ×4 and ×16, on the demo and
  stress fixtures, stays within the cap. At ×16 the stress run draws 717 of 5,789 streaks, 3 of
  192 bundles and 337 of 10,000 edge flares.

## Implementation notes (B14)
Flagged for the owner at the re-opened Stage B gate; no change of scope.
- **Stream rays are not flashes.** B13's residue was capped at 9% luminance so that it could not
  flash. B14 drops the cap so the rays can be as bright as the reference's, and makes them safe
  by construction instead:
  - they blend with MAX, so a pixel is as bright as its brightest ray (at most 0.92, encoded),
    however many overlap;
  - a ray fades over 90 s of run time, but never faster than over 40 s of wall-clock time, so a
    pixel loses at most 0.023 a second. A 10% fall in relative luminance needs a fall of at least
    0.05 (from 0.92, more from anything dimmer): over 2 s. No pixel can complete a rise and a fall
    within one second.

  A unit test checks both against the sRGB luminance curve at every replay speed.
- **Areas.** An edge's flare counts only its arc pieces on the stage, since most of the web is
  off-screen from B14. A bundle counts its longest possible reach (0.32 × the stage height). The
  worst-window test (×0.5–×16, both fixtures) still holds.

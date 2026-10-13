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

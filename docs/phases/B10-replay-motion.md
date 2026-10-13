# B10 — Replay controls & motion safety

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B05–B09 |
| **Branch / PR** | `phase/B10-replay-motion` · PR pending |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Make replay controllable and motion safe (ADR-0011):
- transport controls and a global pause;
- every visual duration in wall-clock time at any replay speed;
- a flash governor that keeps the stage under WCAG 2.3.1's flash threshold;
- reduced motion that stops the decorative motion.

## Scope
- `motion/motion.ts`: `Motion` (replay speed, reduced motion), passed by the frame loop to
  every stage layer (`StageFrame.motion`), panel and callout.
- `stage/governor.ts`: `FlashGovernor`, plus area bounds next to the code that draws each
  element (`streakArea`, `bundleArea`, `segmentArea`, `MARKER_AREA`).
- Segment primitive: a per-instance `flare` attribute (the governor's per-edge decision). The
  host scales each layer's flare decay by the speed and turns flares off under reduced motion.
- Layers:
  - streaks and bundles: wall-clock lives, governed, none under reduced motion;
  - edges and markers: governed flares;
  - ring: snaps take 500 ms of wall-clock time; reduced motion snaps instantly and does not drift;
  - callouts: shown for 2.5 s of wall-clock time.
- Panels: feed inserts, typing, the cursor blink and execution particles in wall-clock time;
  all instant or still under reduced motion. `PanelHost` also redraws when the motion changes.
- `shell/transport.tsx`: the transport strip (rectangle from `computeLayout`), `spaceToPause`,
  `syncTransport`. `main.tsx` follows `prefers-reduced-motion` and the in-app toggle.

## Design notes
- **Wall-clock durations, still pure.** An element's age is `(t − t_event) / speed` in wall-clock
  ms, so a streak lives 600–1,400 ms of wall-clock time at ×0.5 as at ×16. Everything stays a pure
  function of (events, t, motion). Speed changes re-time elements rather than carrying state.
- **The governor** (details in ADR-0011's implementation notes).
  - It caps the bright area that can rise in any 333 ms of wall-clock time at 43,648 CSS px²,
    half of the 87,296 CSS px² flashing area in WCAG 2.2's Understanding document for SC 2.3.1.
    That source was re-checked in this phase; research/05 §7 cites it.
  - Areas are upper bounds from each element's geometry.
  - Over the cap, streaks and bundles are not drawn, and edges and markers appear without their
    flare. At most one bundle per graph edge rises per window.
  - It decides greedily in log order, so its decisions are pure and are only ever extended.
  - With an infinite budget it is off entirely; the stress bench uses that to keep measuring full
    load.
- **Transport.** Play/Pause, ×0.5–×16, a 100 ms-step scrubber with `aria-valuetext`
  ("0:24.5 of 0:48.7"), Live and Reduce motion, in a `<fieldset>` along the bottom of the stage.
  `syncTransport` writes its signal only when the 100 ms step, speed, pause or mode changes. Space
  toggles the clock unless focus is on a control, and ignores key repeats.
- **Two B08 bugs found by the new "scrub = play" property.** The feed's version stepped its
  insert in eighths while the view slid continuously. The execution panel's version stepped at
  33 ms while particles moved continuously. In both, a host would keep showing a stale drawing
  that a fresh scrub would not reproduce. Both views now quantise like their versions.
  `versionOf` also wrapped its phase at 4,096 steps, so a long quiet stretch could repeat a
  version; it now allows 2^26 phases per cursor.
- **Pins.** The B05–B07 render-model pins changed only by the new `flare` attribute. With that
  attribute excluded from the hash, all four old pins matched exactly, so the ×1 rendering is
  unchanged.

## Acceptance criteria
- [x] AC1: scrubbing anywhere gives the same frame as playing to that point (golden).
      - Stage: playing every layer at 60 fps to 12, 24.5, 30.5 and 34 s, at ×1 and ×16, gives the
        same render-model hash as fresh layers scrubbed there. Those hashes are pinned
        (`stage/__snapshots__/motion.test.ts.snap`).
      - Panels: across three busy 2 s stretches, at ×1, ×16 and reduced motion, every frame
        whose version equals the previous frame's draws exactly the same calls. So a host that
        redraws on change shows what a fresh scrub would.
- [x] AC2: the ×16 burst fixture never exceeds the flash threshold. Every 333 ms window, checked
      by brute force over admitted onsets, at every speed:

      | Fixture | Speed | Worst window (px²) | Streaks drawn | Bundles drawn | Edge flares |
      |---|---|---|---|---|---|
      | demo | ×0.5 | 30,065 | 539 / 540 | 66 / 190 | 1,500 / 1,500 |
      | demo | ×1 | 43,647 | 539 / 540 | 52 / 190 | 1,257 / 1,500 |
      | demo | ×16 | 43,642 | 323 / 540 | 16 / 190 | 182 / 1,500 |
      | stress | ×1 | 43,648 | 2,907 / 5,789 | 24 / 192 | 3,101 / 10,000 |
      | stress | ×16 | 43,648 | 717 / 5,789 | 3 / 192 | 337 / 10,000 |

      The cap is 43,648 px², half of WCAG's 87,296. ×4 is in the test too.
- [x] AC3: reduced motion disables streaks and bundles (unit tests). In the browser during the
      24 s trace burst, the toggle gave 0 streak and 0 bundle instances.
- [x] Deliverables: transport (play/pause, four speeds, scrubber, live), Space, wall-clock
      clamping, flash governor, `prefers-reduced-motion` plus the in-app toggle.

## Evidence
- Tests: web 200 (+28: stage motion 12, panel motion 7, transport 9). The B05–B07 pins and the
  feed and execution goldens were updated; the reasons are above.
- In the browser (demo):
  - Space (focus on the stage) resumed the replay without scrolling the page, and the button
    read "Pause";
  - ×16 from 20 s showed up to 270 live streaks and the 16 admitted bundles, each living 1.2 s of
    wall-clock time;
  - Reduce motion set `aria-pressed="true"` and emptied the streak and bundle layers.
- Bench (`docs/perf/B10-motion-bench.json`, cap lifted, same method as B07): p95 16.9–17.0 ms at
  DPR 1 and 2, CPU p95 1.2–1.7 ms. Lit pixels equal B07's exactly, so there is no regression.

## Deviations from spec
- ADR-0011 says over-cap streaks are drawn at reduced intensity. They are reduced to zero,
  because a dimmed streak still counts toward the flash area once streaks overlap additively.
  Bundle aggregation applies at every speed, not only ×4 and ×16. Both are recorded in the ADR's
  implementation notes for the owner at Gate B.
- At ×1 the governor also limits the demo: 52 of 190 bundles and 539 of 540 streaks are drawn.
  That is the cost of meeting the threshold with a margin, and it is visible against B05–B07.
- `Panel.version` and `Panel.view` take an optional `motion` (default: normal), so B08–B09 tests
  and callers that do not animate are unchanged.

## Known gaps
- The flash check is a model with conservative area bounds, not a frame-by-frame luminance
  analysis (the kind of tool used for broadcast flash testing). B12's pixel screenshots could add
  a coarse frame-based check.
- `prefers-reduced-motion` is read with `matchMedia` and its `change` event in `main.tsx`. The
  OS setting was not toggled in a browser here; the in-app toggle path is tested.
- The ring's slow drift stays in run time, so it turns 16 times faster at ×16. It changes no
  luminance (not a flash). Reduced motion stops it.
- Live mode is exercised only with recorded logs until the engine streams events (Stage C).

## Dependencies added
None.

## Research notes
- Re-verified against the source: the 87,296 CSS px² (341 × 256) flashing area in WCAG 2.2's
  Understanding document for SC 2.3.1, already cited in research/05 §7 (source 55, [V]).

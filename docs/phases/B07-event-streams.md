# B07 — Event-stream layer & callouts

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | B04 |
| **Branch / PR** | `phase/B07-event-streams` · PR link added on creation |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
The stage's right half: every pipeline event shoots a streak out of the ring. Bursts of tests
fan out like the reference's streams, and at most two callouts name the latest findings.

## Scope
- `style.ts`: which events stream; their tint, importance, travel distance and lifetime.
- `streakLayer`: streaks on the segment primitive, at most 2,048 live (newest kept), with
  eased heads, velocity-stretched tails and decaying alpha.
- `callouts.ts`: notable events, their label and value, selection of at most two (newest
  first, 2.5 s each), anchoring on the event's lane, and an allocation-free `CalloutTracker`.
  `callouts-view.tsx` is a small DOM overlay (aria-hidden).
- The app and the bench now draw every stage layer for real; no proxies remain in `layers=real`.

## Design notes
- **What streams.** Pipeline activity: tests, traces, perf samples, agents, claims, symbols,
  environments, differences, invariants, evidence, verdicts, missing items and the card. Graph
  events have their own layer. Stage, run and feed bookkeeping (`stage.*`, `run.*`, `log.line`)
  does not stream.
- **Lanes.** An event streams along its file's lane: a hash of `target.file`, or the file part of
  `target.test`, mapped into ±64° on the ring's right side, plus ±1.7° of per-event jitter. One
  file's activity forms a band, like the reference's horizontal streams. Events with no file use
  their kind's lane. Lane angles are cached per event in a `Float64Array`. A first version cached
  them as float32; the purity property test caught that a reused layer then drew differently from
  a fresh one, so the cache is float64.
- **Motion.** Lifetime is 600–1400 ms (DESIGN.md) by importance, from 0 (traces) to 1 (findings).
  The head eases out over the travel distance. The tail trails by the head's current speed ×
  110 ms, so it is long while fast and short as it slows, and it fades to zero (motion blur).
  Alpha decays as (1 − p)^1.5. Travel distance is 90 + 360 × importance px, plus 22·log₂(1 +
  duration) for tests, capped at 620 px. A first version weighted duration at 40·log₂, which made
  a 60 ms test outrun a behaviour diff; a test caught it.
- **Tints (DESIGN.md), in priority order:**
  1. `status: fail` → `--flag-deep`;
  2. any `diff.*` → `--flag`;
  3. a passing `test.finished` → `--ok`;
  4. an agent's event → `--violet`;
  5. the engine → white.
- **Pure function of (events, t).** The layer walks the window `[t − 1400 ms, t]` newest-first
  and recomputes every streak from its event and age. Nothing carries between frames.
- **Callouts** go to findings:
  - verdicts and rejections;
  - behaviour, test-tampering, dependency and perf differences;
  - P2F/F2P outcomes;
  - failed invariants;
  - missing items;
  - the card.

  Each shows a label and one value, e.g. "C3 contradicted · 2 evidence" or "P2F ·
  test_format_duration_hours". Each is anchored on its event's lane at a fixed point, so
  positions do not change while it is shown. A second box moves at least 26 px away from the
  first. The tracker checks the visible set each frame with integers only, and re-renders the
  overlay only when the set or the ring changes.

## Acceptance criteria
- [x] AC1: 2k streaks at the frame budget (`docs/perf/B07-streams-bench.json`). With **every
      layer real**, the stress burst peaks at 2,048 live streaks, alongside 10,000 edges,
      2,730 bundle segments, 608 markers, 320 cards and 1,184 tick segments:

      | DPR | p95 interval (ms) | Dropped frames | CPU p95 (ms) |
      |---|---|---|---|
      | 1 | 17.0 (run 2: 17.0) | 1.5% (1.5%) | 1.5 (1.6) |
      | 2 | 17.0 (run 2: 17.1) | 1.7% (1.1%) | 1.5 (1.5) |

      Worst stage frame: 2.8 ms. The dropped frames match B06's host jitter.
- [x] AC2: Tint mapping follows DESIGN.md. `style.test.ts` checks each state on real fixture
      events, the priority order, and the exact palette hex values.
- [x] AC3: Streak state at any `t` is reproducible after a scrub.
      - A fresh layer and a reused layer give equal render-model hashes at 80 random times
        (fast-check).
      - The drawn count equals an independent recount of the streaming events within their life.
      - The stream is pinned at four demo times.

## Evidence
- Tests: web 133 (+17: style 6, streak layer 7, callouts 4).
- In the browser (demo run): a single test streak leaves the ring at 19.8 s. At 30.5 s, 22 are
  live and the callouts read "F2P test_offset_negative" and "F2P test_offset_aware". At 34 s they
  read "no new dependencies fail" and "missing perf not assessable".

## Deviations from spec
- None. Wall-clock clamping of durations and the flash governor are B10 (ADR-0011). Streak
  lifetimes are in presentation time until then.

## Known gaps
- At ×4 and ×16 the streaks currently shorten with the clock. B10 clamps them to wall-clock
  ranges and caps flashes.
- Callouts are anchored at fixed points on their lane, not to the moving streak head. That is
  deliberate, so the overlay does not re-render every frame.

## Dependencies added
None.

## Research notes
None.

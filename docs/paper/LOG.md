# Research log

Append-only and dated. Record observations, decisions with research impact, measurements,
surprises and negative results. Link the phase record and any artifacts. Never rewrite an
entry. If something turns out wrong, add a correcting entry.

---

## 2026-10-13 · A01 · Research baseline

- Ran six research tracks (landscape, literature, engine technology, agents and standards, web
  stack, evaluation). Notes are in `docs/research/` with verification tags.
- **Positioning change.** Execution-capable AI reviewers already exist (Codex review, Greptile
  TREX, Claude ultrareview). Base-vs-head differencing has long prior art (BERT, PATCH-SIM) and
  recent agent-specific work (PatchDiff, **Testora**, both ICSE 2026). The novelty claim moved to
  the combination: claim-relative explained-delta oracle, evidence-constrained verdicts, Missing
  inventory, and a comparative study.
- **Design changes driven by the literature:**
  - differential probe generation, because existing tests rarely expose divergences
    (Shadow SE, PatchDiff);
  - test-tampering detection (ImpossibleBench);
  - A/A′ noise control and a DeFlaker check (Gruber et al.: 170 reruns for 95% confidence);
  - order-swap stability checks for verdicts (Wang et al. ACL 2024; CodeJudgeBench).
- **Evaluation redesign** (ADR-0010): fresh post-cutoff tasks, a CI-only baseline, Testora as
  the academic baseline, two blinded annotators, exact McNemar, k = 5.
- **Corrections to the original brief:** arXiv 2601.07189 is a position paper, not a survey.
  PaperBench's 21.0% is an average replication score.
- **Spot-checked on arXiv by the maintainers:**
  - Testora: sole author M. Pradel; ICSE 2026 per the arXiv comment.
  - PatchDiff: Wang, Pradel, Liu; DOI 10.1145/3744916.3764576.
  - PR-MCI: Gong et al.; 23,247 PRs; 45.4% "claim unimplemented changes".
- **Known gap:** literature discovery for 2025–2026 is incomplete (search budget exhausted). A
  follow-up search is needed before J10.

## 2026-10-13 · A04 · Evidence-constrained output, by construction

- The event schema v1 defines verdicts so that `cited_evidence` has `minItems: 1` and contains
  only `ev_`-prefixed ULIDs. Agent-facing schemas are derived from the source schemas by
  `to_draft07()`, because the Agent SDK validates draft-07 only.
- Design rule worth reporting: the derivation **rejects** keywords draft-07 cannot express
  instead of dropping them. Dropping a constraint would let an LLM emit output the source
  schema forbids, silently widening what counts as a valid verdict. A hygiene test keeps such
  keywords out of all source schemas, so derivation is total over the v1 schema set.
- Tests show the derived schemas agree with the source schemas on every model example
  (valid accepted, invalid rejected) and accept every valid payload example (380 tests).

## 2026-10-13 · A08 · Feasibility measurements

- **Tracer overhead** (16 configurations: CPython 3.12–3.15 × Windows/Linux × 2 workloads; 5
  interleaved rounds × 15 repetitions; process per configuration):
  - `sys.monitoring` with everything `DISABLE`d runs at baseline (0.94–1.06×).
  - Per-call dispatch for an instrumented target: 114–197 ns, against 193–547 ns for `sys.settrace`.
  - Full argument and return capture with structural encoding plus BLAKE2b: 2.3–11.4 µs per call.
    The encoder dominates, and settrace capture is only 2–35 % slower.
  - A per-target budget of 200 captured calls returns overhead to baseline in steady state.
  - **Implication for the paper:** value capture is affordable only with budgets. The cost
    model belongs in the evaluation's RQ5 (cost), and encoder design is a performance
    contribution, not an implementation detail.
- **Sandbox:** Docker `--network none` verifiably blocks network on Windows Home (WSL2), at about
  0.3–0.9 s per container. Offline provisioning from a warm uv cache: 0.79 s vs 9.9 s cold
  (pallets/click 8.5.0).
- **Negative and surprising results worth reporting:**
  - Docker's default `noexec` tmpfs caused 3 sandbox-induced test failures in click. A naive
    sandbox can *create* behaviour differences, which is a threat to validity. Base and head
    share the sandbox, so the effect is symmetric, but it must still be avoided.
  - 24 click tests fail in a slim image because `less` is missing. Environment-induced failures
    are common, which is why outcome comparison must be base-vs-head (F2F) rather than absolute.

## 2026-10-13 · B01 · Check model and synthetic reference run

- ADR-0015 defines a *check* as a result-bearing event (`diff.*`, `invariant.result`) with a
  status that does not depend on claims: `ok`, `fail` (a problem on its own) or `warn` (needs
  explaining, or not comparable). A `warn` check counts as passed only when a **supported**
  verdict cites its evidence. If review ends with no such citation, it counts as flagged
  (an unexplained difference). This states the claim-relative explained-delta oracle in a
  form that can be checked directly against the event log, with counters that only rise during
  a run.
- The synthetic reference run (`@repro/synth`, `DEMO`, seed 1) has 28 checks: 20 passed,
  4 flagged, 4 unassessed. It also contains a test-tampering case, a masked unstable
  observation and a rejected-then-retried verdict. It is a UI fixture, **not** evaluation
  data, and must never be reported as a result.
- Record: `docs/phases/B01-fixture-generator.md`.

## 2026-10-13 · B04 · Rendering cost of the cockpit at stress load

- The animated cockpit is not a performance risk. On an **integrated** GPU (Intel UHD, ANGLE
  D3D11, Chromium 152), the stress load holds 60 fps at DPR 2 with a 1920×641 stage: 10,000
  dependency edges and 2,048 concurrent event streaks, drawn as instanced anti-aliased quads in
  4 draw calls. The p95 frame interval was 17.0 ms, about 1% of frames were dropped, and stage
  CPU time was under 1 ms at p95. The ~1% of dropped frames also occurs at DPR 1 and on an idle
  stage, so it is host jitter rather than rendering cost.
- Method, hardware and raw numbers: `docs/perf/B04-stress-bench.json`. The CPU (i7-14650HX) is
  stronger than a typical mid laptop's. The large CPU headroom makes that immaterial to the
  conclusion, but a paper should state the hardware exactly.

## 2026-10-13 · B04 · Correction: the first stage benchmark drew nothing

- The B04 entry above is **wrong as first recorded**. Its timings came from a stage that drew no
  pixels: three.js culled every segment quad as a back face, because the shader's y flip
  reverses the triangle winding. Instance and draw-call counters looked normal, so nothing hinted
  at the missing fill.
- Re-measured after the fix (`side: DoubleSide`), with a pixel read-back confirming 0.40–1.57 M
  lit device pixels: on the same integrated GPU the stress load still holds 60 fps at DPR 2. The
  p95 frame interval was 16.9 ms, dropped frames ≤ 0.4%, and stage CPU p95 ≤ 0.7 ms. The
  conclusion stands; the numbers in `docs/perf/B04-stress-bench.json` are the corrected ones.
- Lesson for the evaluation chapter: a performance benchmark needs an output check (here, lit
  pixels), not only counters. The bench now refuses to report timings without it.

## 2026-10-14 · B10 · Motion safety as a bounded onset budget
- WCAG 2.2 SC 2.3.1 limits flashing area. Its Understanding document gives 341 × 256 = 87,296
  CSS px² at 1024 × 768 (research/05 §7, source 55, re-checked in B10). For an event-driven
  visualisation whose bursts are the point, we cap the bright area that can *rise* within any
  333 ms of wall-clock time at half that area.
- The argument: if at most B can rise per 333 ms, then at most 3B can rise per second, so the area
  that flashes more than three times a second is at most 3B/4 < B. Decisions are greedy in log
  order, so they are a pure function of (events, speed, geometry), identical when playing or
  scrubbing.
- Measured (unit-tested): the worst window is within the cap at ×0.5, ×1, ×4 and ×16 on both
  fixtures. The cost is visible. At ×1 the 10k-edge stress run draws 2,466 of 5,789 streaks;
  at ×16, 530 (B13 geometry). A frame-based luminance analysis would be a stronger check and is
  future work.

## 2026-10-14 · B12 · Quality gates that prove they can fail
- Four CI gates guard the cockpit: visual regression, a flat heap over 1,000 frames, bundle size
  and calibrated frame cost. Each also runs a self-test that injects a regression of its kind
  (a 1 px layout shift, a 2 kB-per-frame leak, 300 kB of bloat, 2 ms of work per frame) and must
  fail. All four held in CI run 38463117924.
- Two measurement lessons:
  - A leak check on the JS heap alone misses typed-array leaks, because their backing stores
    live outside the heap; count ArrayBuffers too.
  - Frame cost on shared runners varies about 60% between machines (calibration 5.46 vs
    8.86 ms). Dividing by a calibration workload timed in the same process made one baseline
    usable.

## 2026-10-14 · B13 · Geometry transfer from a portrait reference
- The visual reference is a portrait recording. Its ring geometry, measured as fractions of the
  stage (centre 0.15·W, radius 0.55·H), was copied directly onto a landscape stage. That gave a
  small circle and an empty right half; the side-by-side gate check caught it. What transfers
  is the relationship: the arc spans the stage height with its 3 o'clock point near mid-width.
  On landscape that means radius 0.9·H.
- The reference's dense streams were reproduced without breaking the flash budget, with a static
  residue: each event's faint trace (≤ 9% luminance, under the 10% flash threshold), faded by
  the shader. Motion stays tied to events, and the look comes from accumulation, not brightness.
- With the whole cockpit running, the demo run replays at ×1 at 60 fps on an integrated GPU
  (Intel UHD) at 1920×1080, DPR 1.75: p50 16.7 ms, p95 17.0 ms over 2,867 frames, with 1.85%
  of frames over 25 ms (host jitter). The CPU, an i7-14650HX, is stronger than a mid laptop's.

## 2026-10-14 · B14 · Measuring a visual reference instead of eyeballing it
- B13's parity check passed on our own judgement, and the owner's review overturned it. A sharper
  copy of the reference (1080×1350 at 60 fps) and two measurements replaced the
  judgement:
  - Geometry: circles fitted through three points on each rim give the inner radius as 1.02 ×
    the stage height, the band as 0.215 of that radius, and the 3 o'clock point at 0.46 × the
    width.
  - Brightness: per-region statistics of 8-bit encoded luminance, compared at the same stage
    height. In the reference the web's mean is 43 and the rays' 41 (64–83 next to the ring).
    After B13, Repro's rays measured 9.
- The look depends on the stage's shape. The reference's 1.15:1 composition cannot fit a 2.76:1
  strip, so the panels moved beside the stage on landscape screens.
- Its hairball can be reproduced from real edges by changing the layout, not by adding lines. A
  chord layout ordered by the force simulation, with the circle's centre off-screen, turns 1,446
  import edges into long crossing arcs instead of a ball of spokes.
- Bright, persistent elements can be made flash-safe by construction rather than by budget. MAX
  blending bounds a pixel by its brightest element, and a wall-clock floor on the fade bounds
  how fast it can dim, so no 10% luminance fall fits in a second.
- Motion was measured the same way. Cross-correlating a column of the ring between frames
  gives its rotation, about 280 px/s at mid-band (about 15° a second), while the web stays still.
  At 30 fps a strand lives 0.3–0.35 s: it shoots in for about 0.1 s and then rides the turning
  ring. Our first pass had matched the stills but not this.
- The owner's reading of the strands decided the model: one dim line per node of a network,
  carrying a white bullet to the wheel, staying attached to its node and following the wheel
  section it hit. Under a flash cap, how much each strand draws and how far it may aim decide how
  many can be shown. Aiming within 10° of the node's bearing let the cap admit 24 of 190 demo
  strands at ×1, against 8 when they could aim across the visible arc. A single line with a short
  bullet, instead of a sheaf of curves, brought it to 31. The owner's last correction made each
  event fire a bunch, one strand from every node that reaches the function (tests and callers,
  from the log so far). The bunch is honest data, and the cap then admits 12 bunches at ×1.
- A containment rule fixed what read as strands leaving the wheel. 82 of 1,500 mesh arcs bowed
  past the ring's outer rim; keeping each arc's control point inside the web's circle bounds the
  whole curve there, because a quadratic Bézier lies in the triangle of its points.
- After B14 the demo replays at ×1 with the whole cockpit at 60 fps on an integrated GPU
  (production build, 1440×900, DPR 1.75): p50 16.7 ms, p95 17.0 ms over 3,081 frames, with 1.14%
  over 25 ms.

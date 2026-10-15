# Stage E gate — Behaviour evidence

| | |
|---|---|
| **Phases** | E01–E07 |
| **Release** | `v0.5.0` |
| **Gate date** | 2026-10-15 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate E) | Result | Evidence |
|---|---|---|
| A change that alters a function's output **without failing any test** is detected | pass | `apps/web/gate/gate-e.spec.ts` builds the `silent-change` fixture (head rounds `to_celsius` to whole degrees; no test checks the value) and runs `repro run` on it in full: no test fails on BASE, A′ or HEAD, and the engine sends two `diff.behaviour` checks for `units.convert:to_celsius#0`, one per test that calls it |
| … shown as a stable behaviour diff with a reproducer | pass | Both checks are `result_changed` and `stable`, reproduced by a second run of their tests on each side (E04), with that run's values: `to_celsius(fahrenheit=100)` base `37.8`, head `38` (`test_describe_mentions_celsius`); `to_celsius(fahrenheit=32)` base `0.0`, head `0` (`test_freezing`). The cockpit's behaviour field shows the two cells differing (fed by the run's `trace.sample` events), Signals' DRIFT ends at `1.00`, Change routes reads "to_celsius 2 tests 2 flagged" and the index "4 checks / 2 passed / 2 flagged" (unexplained without review, ADR-0015) |
| … and is not confused with noise in the A/A′ control | pass | The same spec on `noisy` (functions returning the time, a random draw and a set's order, rewritten by head without changing behaviour): no `diff.behaviour` at all; the `stamp`, `roll` and `fruit` cells unstable, `total` the same, no cell differing; DRIFT `0.00`; "5 checks / 5 passed / 0 flagged". A′ differs from A in test order, hash seed and (since E03) the `random` seed; without that seed the random draw looked stable (E03's evidence) |

Both scenarios passed on Windows in Edge (process sandbox), 57 s each, and were checked by eye;
the `gate E` CI job runs them on Linux in containers (CI matrix).

## Phases
| Phase | PR | What it brought |
|---|---|---|
| E01 | [#46](https://github.com/DuhItzAniket/Repro/pull/46) | The tracer: every call of a change's functions per test, as stable digests, 200 a test and function, beside coverage.py; the overhead benchmark |
| E02 | [#47](https://github.com/DuhItzAniket/Repro/pull/47) | The canonical encoder: objects, exceptions and library values read through the interpreter's own descriptors, no target code run; normalised paths and addresses; guards; previews |
| E03 | [#48](https://github.com/DuhItzAniket/Repro/pull/48) | Observations joined across A, A′ and H; A vs A′ noise masked per call and field; deterministic CBOR artifacts |
| E04 | [#49](https://github.com/DuhItzAniket/Repro/pull/49) | Behaviour differences classified, reproduced and cited: `behaviour_diff` and `diff.behaviour`; input mutation |
| E05 | [#50](https://github.com/DuhItzAniket/Repro/pull/50) | The public API's breaking changes (griffe, statically, plus annotations) and dependency differences (lock or declared, and installed) |
| E06 | [#51](https://github.com/DuhItzAniket/Repro/pull/51) | Input-replay probes: Hypothesis-generated inputs for JSON-typed changed functions on both sides |
| E07 | [#52](https://github.com/DuhItzAniket/Repro/pull/52) | The behaviour field and Signals from real runs (`trace.sample`); Gate E's browser test |

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest (Docker: L3 suites required) | 3.13 | 24 | pass (7 min 34 s) | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| windows-latest | 3.13 | 24 | pass (14 min 48 s) | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| ubuntu-latest, Gate E (Chromium from Playwright 1.64.0, containers) | 3.13 | 24 | pass (2 min 36 s) | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| ubuntu-latest, Gate D (containers) | 3.13 | 24 | pass (2 min 2 s) | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| ubuntu-latest, Gate C (`--analyse-only`) | 3.13 | 24 | pass | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |
| ubuntu-latest + Playwright image (visual) | — | 24 | pass | [CI run 38688305111](https://github.com/DuhItzAniket/Repro/actions/runs/38688305111) on [#52](https://github.com/DuhItzAniket/Repro/pull/52) |

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 1,297 (Windows locally: 1,285 pass, 12 skip with Docker Desktop stopped; CI runs the container tests on Ubuntu); Vitest 379 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 298); 8 visual screenshots; Gates C, D and E |
| Engine code | 14,784 lines of Python under `engine/src` (10,548 at Gate D) and 10,448 in `engine/tests` |
| Web code | 11,894 lines of TypeScript outside tests and 5,355 in tests, under `apps/web/src` |
| JavaScript, gzip | 197.88 kB of the 300 kB budget (197.75 kB at Gate D) |
| Tracer overhead (E04, 8 rounds, BCa 95 %) | point estimates 1.05–1.24× on the benchmark's three tests over Python 3.12–3.15; no interval above 1.20× (its rule), the highest low end 1.17× |
| A change through `repro run`, process sandbox | Gate E: `silent-change` and `noisy` 57 s each on Windows (two sides, three traced runs, reproducers, probes, timing) |

## Retrospective
- **The encoder is the tracer's cost.** E02's first full encoder put the dict-heavy benchmark
  test at 1.35–1.55×; measuring per call showed encoding, not dispatch, and a flush per record
  costing as much again. One walk for both digests, sorting only for results and a flush per
  test brought it to 1.14–1.18×; E04's mutation check added about five points back on that
  test. Every step is in `docs/perf/E01-tracer-bench.jsonl`, including the ones that failed.
- **Noise has to be varied to be seen.** The plugin seeds `random` per test, so A and A′ drew
  the same numbers until E03 gave A′ its own seed; a random result then looked stable. A′ now
  differs from A in everything the sandbox fixes (order, hash seed, random seed).
- **Measured runners, not assumed ones.** A slow Windows CI runner ran out of the test job's
  15 minutes with nothing failed (E03; the limit is now 30); Docker reported a memory-killed
  container without its `OOMKilled` flag once (E05; the test accepts the kernel's SIGKILL).
- **Libraries are what they are, not what they were.** griffe 2.x became a meta-package
  (`griffelib` holds the library); its annotation checks are still TODOs, as ADR-0006 found;
  its explanations carry host paths. `python -I -S` does not know it runs in a virtual
  environment (`site` sets that), which the installed-set listing had to learn.
- **The gate test found a naming drift.** DESIGN.md calls the signal BEHAVIOUR DRIFT and the
  panel labels it DRIFT; the first Gate E run caught the spec reading the wrong one.
- **Roadmap adjustments**, made in the schema and recorded in the phases: `BehaviourChange`
  gains `calls_changed` (E04), `diff.deps` sources gain `declared` (E05); timing runs after the
  other runs of the sides (E06).

## Gaps and owed items
- Stage E: calls past a test's budget (200) and arguments too large to encode are not compared
  (listed as missing); single-module libraries have no API diff; annotation changes are
  compared as text; probes cover only JSON-typed module-level functions, and short random text
  rarely forms structured values; the behaviour field samples each function's first four calls
  per test; Windows container runs were not repeated for Stage E (Docker Desktop was stopped;
  Ubuntu CI runs the container suites and Gate E in containers).
- Owed by the owner: the decision on rewriting the 32 merge commits on `main` that carry the
  personal email (#1–#34); making the `visual` and gate jobs required checks; the dependency
  graph and the Dependabot PR #17; the mid-laptop 60 fps check.

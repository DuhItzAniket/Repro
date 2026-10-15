# Stage F gate — Policy & deterministic card

| | |
|---|---|
| **Phases** | F01–F05 |
| **Release** | `v0.6.0` |
| **Gate date** | 2026-10-15 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate F) | Result | Evidence |
|---|---|---|
| Each invariant has a passing and a failing fixture | pass | Through `repro run`, `test_run_stage.py`: `invariants-pass` passes all five (`public_api_stable`, `no_new_dependencies`, `forbidden_paths`, `no_network`, `perf_budget`); `api-break` fails `public_api_stable`, `new-dep` `no_new_dependencies`, `forbidden-path` `forbidden_paths`, `net-call` `no_network`, `perf-regress` `perf_budget`. `no_network` passes `enforced` in containers (`test_no_network_rests_on_enforcement_in_containers`, Ubuntu CI) and `detected-only` with a `network_not_enforced` item in the process sandbox |
| Every fixture repo yields the expected deterministic status | pass | All 17 fixtures through `repro run`: each status decided from its own log (F04) and published in its card (F05) equals its expectation file's: 13 FLAGGED, 3 UNVERIFIABLE (`flaky`, `noisy`, `untested`), 1 VERIFIED (`invariants-pass`). `honest-fix` and `selection` are FLAGGED without claims (their `deterministic_status`); their differences need Stage G's claims to be explained. Each card matches its golden file (`engine/tests/golden/cards/`) |
| `repro replay` regenerates identical cards | pass | Every end-to-end run (17 fixtures and two runs whose environment cannot be built) assembles its card again from its stored log and gets the published bytes, digest and `cards` row; `repro export` refuses a card that differs from its log and `repro replay` reports it (`test_card.py`, on a real run's log and a tampered copy) |

## Phases
| Phase | PR | What it brought |
|---|---|---|
| F01 | [#54](https://github.com/DuhItzAniket/Repro/pull/54) | `repro.yml` read from base, validated against a JSON Schema with line-numbered errors; head's edit to it as `policy_change` evidence |
| F02 | [#55](https://github.com/DuhItzAniket/Repro/pull/55) | `public_api_stable`, `no_new_dependencies`, `forbidden_paths` from the run's evidence; `Job.after`, so a failed job leaves the invariants not evaluated rather than skipped |
| F03 | [#56](https://github.com/DuhItzAniket/Repro/pull/56) | `no_network` (enforced or detected-only) and `perf_budget` (D07's regressions past the budget) |
| F04 | [#57](https://github.com/DuhItzAniket/Repro/pull/57) | The status engine: VERIFIED, FLAGGED or UNVERIFIABLE from the log alone, every reason citing evidence |
| F05 | [#58](https://github.com/DuhItzAniket/Repro/pull/58) | The Reproduction Card: assembled from the log, published, stored, exported (Markdown, canonical JSON), checked on replay, shown in the cockpit |

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest (Docker: L3 suites required, incl. `no_network` enforced) | 3.13 | 24 | pass (12 min 39 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| windows-latest | 3.13 | 24 | pass (15 min 52 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| ubuntu-latest, Gate E (containers) | 3.13 | 24 | pass (3 min 22 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| ubuntu-latest, Gate D (containers) | 3.13 | 24 | pass (2 min 26 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| ubuntu-latest, Gate C (`--analyse-only`) | 3.13 | 24 | pass (59 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| ubuntu-latest + Playwright image (visual, baselines regenerated in F05) | — | 24 | pass (2 min 43 s) | [CI run 38754368209](https://github.com/DuhItzAniket/Repro/actions/runs/38754368209) on [#58](https://github.com/DuhItzAniket/Repro/pull/58) |

Gate F's criteria are engine criteria: `test_run_stage.py` and `test_card.py` demonstrate them
in the `test` jobs on both operating systems (process sandbox), and in containers on Ubuntu.

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 1,452 (Windows locally: 1,439 pass, 13 skip with Docker Desktop stopped; CI runs the container tests on Ubuntu); Vitest 385 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 304); 8 visual screenshots; Gates C, D and E |
| Fixtures through `repro run` | 17, each with its status and a golden card; 5 invariants with a passing and a failing fixture each |
| Status engine | 40 table rows; the never-VERIFIED property over 2000 generated inputs a run |
| Engine code | 17,015 lines of Python under `engine/src` (14,784 at Gate E) and 12,169 in `engine/tests` (10,448), counted with `wc -l` over tracked files |
| Web code | 12,064 lines of TypeScript outside tests and 5,602 in tests, under `apps/web/src`, counted the same way |
| JavaScript, gzip | 199.22 kB of the 300 kB budget (197.88 kB at Gate E) |
| A change through `repro run`, process sandbox | `test_run_stage.py`'s 20 end-to-end runs in 11 min 3 s on Windows, 33 s on average (`perf-regress` alone 49 s): two sides, three traced runs, probes, timing, the invariants and the card |

## Retrospective
- **A review before each PR found what the tests did not.** F02's first version passed its own
  fixtures, yet a dependency added to `pyproject.toml` in a project installed from requirement
  files went unseen, `migrations/` matched nothing, and one failed job skipped every invariant.
  Each became a fix and a test before the PR. The common thread: a rule that can pass
  vacuously must be an error or "not evaluated", never a pass.
- **The status needs the log to hold everything it reads.** F04 found the policy's thresholds
  in no event and added `policy` evidence; F05 found the seeds in none and recorded them as
  `environment` evidence. A replay can only decide what the log records.
- **Deterministic and reviewed statuses differ, and the fixtures say so.** Without claims an
  honest fix is FLAGGED (its behaviour change is unexplained, ADR-0015 §3); `honest-fix` and
  `selection` carry a `deterministic_status` beside the status Stage G must reach.
- **Timing is sensitive to the machine.** A type check and a lint running beside the fixture
  runs once turned `perf-regress`'s steady test into a regression; alone it was steady. Timing
  evidence is only as quiet as the machine it is taken on.
- **A hidden browser pane does not animate.** The cockpit's drawer follows the frame loop; with
  the pane hidden it never opened, so the card view was checked in headless Edge instead. The
  first version's five-column tables wrapped a letter a line in the 380 px drawer.
- **Roadmap adjustments**, made in the schema and recorded in the phases: `Job.after` (F02);
  `EvidenceType` gains `policy` (F04); `card.published` may carry the card, and the card model
  is completed at version 1 (F05).

## Gaps and owed items
- Stage F: Poetry's own dependency table is not read; setuptools' `dynamic` dependencies count as
  unread even when a compared requirement file holds them; detection-only network evidence is
  the target's to tamper with under L2 (the card says so); budgets under D07's 10 % effect are
  rarely decided on a laptop; the synthetic demo log carries no full card; test helpers outside
  test files count as changed symbols.
- Owed by the owner: the decision on rewriting the 32 merge commits on `main` that carry the
  personal email (#1–#34); making the `visual` and gate jobs required checks (F05 had to hold
  its auto-merge until its regenerated baselines were committed, since `visual` is not
  required); the dependency graph and the Dependabot PR #17; the mid-laptop 60 fps check.

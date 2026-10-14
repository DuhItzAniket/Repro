# D07 — Performance pass

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | in progress |
| **Depends on** | D06 |
| **Branch / PR** | `phase/D07-performance-pass` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Say whether a change made the code it tests slower or faster, with a confidence interval and
the noise this machine produces, and say explicitly when a test is too fast to tell.

## Scope
- **Timing runs** (`repro.runner.perf.time_tests`): the selected tests that pass on both sides
  (`P2P`), untraced, base and head interleaved in ABBA blocks until each side has 10 runs; the
  sample is pytest's *call* phase (the plugin now reports it, `call_s`).
- **Statistics** (`repro.runner.perf`): the ratio of medians (head / base) with a BCa bootstrap
  95 % interval (9,999 resamples, a seeded generator per test, the jackknife acceleration of
  each sample); a two-sided Mann-Whitney U test (normal approximation with tie and continuity
  corrections), Benjamini-Hochberg across tests.
- **Floors**: a test whose medians are both under 5 ms is not assessable; the noise floor is the
  larger of 10 % and the A/A spread (the 95th percentile, across tests, of how far the ratio of
  base's first-position to last-position samples lies from 1).
- **Verdicts**: `regression` (interval above 1, ratio ≥ 1 + floor, adjusted p < 0.05),
  `improvement` (the mirror image), else `no_change`. `perf_diff` evidence with `diff.perf`;
  `perf.sample` per test and run; a `perf_not_assessable` item naming every test too fast to time.
- **Pipeline**: `perf` (run stage) and `perf-diff` (diff stage) jobs after `tests`.
- Fixture `perf-regress` (TEST_STRATEGY §3).

## Out of scope
- Benchmarks other than the selected tests; a profile of where the time went; tuning the machine
  (pyperf's `system tune`); the `perf_budget` invariant itself (F03).

## Design notes
- **What a sample is.** The call phase is the test's body; fixtures (setup and teardown) carry
  their own noise and are left out. Only passing runs count: a failure's time measures something
  else.
- **ABBA without a calibration run.** research/03 §9 asks for an A/A calibration (base against
  base). ABBA already gives two base samples per block, in the first and last positions; the
  ratio between those two halves is an A/A comparison of the same code on the same machine,
  under the same drift, at no extra cost. Its 95th percentile across tests becomes the noise
  floor whenever it is larger than 10 %.
- **Three guards against noise.** The interval must exclude 1, the effect must clear the floor,
  and the Mann-Whitney test must stay significant after Benjamini-Hochberg across all timed
  tests, so that timing many tests does not manufacture a regression.
- **Too fast is not "no change".** A test under the timing floor on both sides says nothing about
  speed; it is a `perf_not_assessable` item, never a `no_change` (Ground Rule 3). A test fast on
  one side and slow on the other is assessed: that is the regression a floor must not hide.
- **Validated against reference implementations,** computed outside the project: Mann-Whitney
  p-values equal SciPy 1.18.1's `mannwhitneyu(method="asymptotic")` to 1e-16;
  Benjamini-Hochberg equals statsmodels' `fdr_bh`; the BCa interval agrees with
  `scipy.stats.bootstrap(method="BCa")` within Monte Carlo error on continuous data (both with
  99,999 resamples: e.g. a 1.3× shift gives (1.2811, 1.3836) here and (1.2806, 1.3836) there).
  Neither library is a dependency.

## Acceptance criteria
- [x] AC1 (roadmap): `perf-regress` is flagged with a CI excluding 1.
- [x] AC2 (roadmap): an A/A run on an unchanged repo produces no perf diff over 20 repetitions.
- [x] AC3: tests under the timing floor are `perf_not_assessable`, never `no_change`.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_run_stage.py::test_a_run_reproduces_the_fixture[perf-regress]`: `perf_diff:regression` for the quadratic loop, `no_change` for the test whose time it does not change, through `repro run`; 30 `perf.sample` events a side |
| AC2 | `test_perf.py::test_an_aa_run_of_real_tests_shows_no_change`: base against a copy of base, 20 runs a side, both timed tests `no_change` |
| AC3 | the same fixture's `test_unique_tags_small`; `test_perf.py::test_verdicts`; the other fixtures' fast `P2P` tests |
| — | `test_perf.py`: SciPy and statsmodels reference values, ABBA order, interval sanity, the A/A floor |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.runner.perf`; the plugin's `call_s`; `perf` and `perf-diff` jobs.
- Fixture `perf-regress`; the other fixtures' expectations name their untimeable tests.
- The run stage's check events now carry exactly ADR-0015's statuses (`P2F` and test-tampering
  findings `fail`; `F2F`, removed, modified, flaky and `test_modified` `warn`; a perf
  regression `warn`), asserted end to end against the ADR's table.
- Tests: `test_perf.py` (8), `perf-regress` end to end. pytest 1063 → 1073 (1071 pass and 2
  skip on Windows with Docker Desktop).

## Evidence
- Windows: `perf-regress` through `repro run` flags `test_unique_tags` as a regression (about
  9 ms a call on base, about 190 ms on head, measured here with `timeit`), `test_report_is_sorted`
  no change, `test_unique_tags_small` not assessable; the A/A run (20 runs a side) gives no
  change for both timed tests.
- CI run: linked in the PR.

## Deviations from spec
- The A/A calibration comes from the ABBA runs themselves, not from a separate base-against-base
  pass (Design notes).

## Known gaps
- Timing runs share the machine with everything else on it; nothing pins CPUs or raises
  priority (pyperf does both). A busy machine raises the A/A floor rather than producing false
  regressions.
- The 5 ms and 10 % floors are research/03 §9's starting points, not measured here for every
  machine; they are constants, not yet settings.
- Only `P2P` tests are timed: a test that changed outcome has no comparable time.

## Dependencies added
None.

## Research notes
- research/03 §9 (pyperf, Kalibera & Jones, `scipy.stats.bootstrap` with BCa, the recommended
  method and floors). Reference implementations used for validation: SciPy 1.18.1 and
  statsmodels from PyPI, in a throwaway environment.

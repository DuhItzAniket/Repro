# D06 — Two-sided execution, outcome & test-change diff, flake control

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | done |
| **Depends on** | D05 |
| **Branch / PR** | `phase/D06-two-sided-execution` · [#43](https://github.com/DuhItzAniket/Repro/pull/43) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
`repro run` runs the tests a change can affect on both sides, in sandboxes, and records what
differs as evidence: each test's base→head outcome class, the changes to the tests themselves,
and, explicitly, what could not be checked (flaky tests, unfinished runs, uncovered code).

## Scope
- **Runs** (`repro.runner.twosided.reproduce`): A (base, mapped, every test; only the selected
  ones when the base map is cached), head's test list, the selection (D05), A2 (base again, the
  selected tests in reverse order with `PYTHONHASHSEED=1`), H (head, mapped), *k* = 3 reruns of
  each flip on both sides, and the base version of each edited test against head's code.
- **Classification** (`repro.runner.outcomes`): `new`, `removed`, `flaky` (A and A2 disagree, or a
  flip's reruns do not all repeat it), `modified`, `P2P`, `F2F`, `F2P`, `P2F`. A test passes when
  it is `passed`, `xfailed` or `xpassed`; a skip does not pass. DeFlaker's check marks a flip
  whose runs executed none of the changed code as *likely flaky*. `test_outcome` evidence and
  `diff.outcome`; `unstable_observation` items for flaky tests.
- **Test-file diff** (`repro.runner.testdiff`): `test_removed`, `skip_added`, `xfail_added`,
  `assertion_removed`, `assertion_weakened`, `raises_widened`, `test_modified`, and
  `base_test_fails_on_head` from running. `test_change` evidence and `diff.tests`.
- **The pipeline's run and diff stages** (`repro.run_stage`): `sandbox-<side>` (Docker when asked
  or available, else the process sandbox; the environment; `sandbox.ready`, `env.provisioned`),
  `tests` (`test.selected`, `test.started` / `test.finished` per test and attempt), `outcomes`
  (evidence, diffs, detections, missing items). `repro run --analyse-only` keeps the build stage
  alone.
- Overlays for "base tests on head": a copy of head's snapshot with base's test files written
  over it, in either sandbox (`Side.overlay`, `DockerSandbox.overlay`); `run_tests(hash_seed=...,
  directory=...)`.
- Fixtures `flaky` and `test-tamper` (TEST_STRATEGY §3); expected evidence for `honest-fix`,
  `selection`, `untested`, `flaky` and `test-tamper`.

## Out of scope
- Timing runs and performance evidence (D07); behaviour traces (Stage E); verdicts and the card's
  status (Stages F–G).

## Design notes
- **A2 changes only what should not matter.** A2 differs from A in test order and hash seed, and
  nothing else, so a test whose outcome changes between them depends on them, not on the change.
  Selected tests run in collection order (A's), so H and the reruns differ from A only by side.
- **Reruns only where they decide something.** A flip (A and A2 agreeing, H differing) is the
  only case where a rerun changes a conclusion; each one runs *k* = 3 more times on both sides
  (research/03 §10), and becomes evidence only if every rerun repeats it.
- **DeFlaker as a label, not a verdict.** DeFlaker labels a newly failing test that executed no
  changed code as flaky, with no reruns (research/02 §5.5). Repro still reruns: a failure that
  runs no changed function can come from module-level code, data files or dependencies, which
  the map does not see. The label stays on the evidence (`likely_flaky`).
- **Skips do not pass.** A test skipped on head verifies nothing there, so `passed → skipped` is
  a `P2F`, and SWE-bench-style "pass" (passed or xfailed) is extended only by `xpassed`.
- **The test diff reads the tests, never runs them;** running is for the base versions. An edited
  test is compared with its base version from the source: its markers, its assertions (count,
  then strength: exact `==`/`is`, a looser comparison, a mere truth test) and its
  `pytest.raises` (broadened to `Exception`/`BaseException`, or `match` dropped).
- **An environment that cannot be built is unverifiable, not a failed run.** The sandbox job
  records `environment_failed` with uv's reason and the run goes on without tests (D03's rule:
  never a crash).
- **One run, one state.** The run's jobs share a `RunState`; closing it removes the containers'
  volumes with the scratch directory, whether the run completed or not.

## Acceptance criteria
- [x] AC1 (roadmap): the `honest-fix`, `flaky`, `untested` and new `test-tamper` fixtures produce
  exactly the expected evidence.
- [x] AC2: so do they through `repro run`, as stored events of a schema-valid log (the process
  sandbox everywhere, containers on Linux and Docker Desktop).
- [x] AC3: flips are rerun on both sides; A2 runs in the reverse order with another hash seed.
- [x] AC4: a project that cannot be provisioned gives `environment_failed` items with the
  reason, and a completed run.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_twosided.py::test_each_fixture_gives_exactly_its_evidence[…]` (five fixtures, `selection` too), against each expectation file's `evidence` and `missing` |
| AC2 | `test_run_stage.py` (`honest-fix`, `test-tamper` in the process sandbox; `test-tamper` in containers) |
| AC3 | `test_a_flip_is_run_again_on_both_sides`, `test_the_reverse_order_and_another_hash_seed`, `test_test_events_count_attempts` |
| AC4 | `test_an_environment_that_cannot_be_built_is_unverifiable` |
| — | `test_outcomes.py`: every class, reruns, skips, DeFlaker's label, the test diff's findings on source snippets, schema validation of every payload |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.runner`: `outcomes.py`, `testdiff.py`, `sides.py`, `twosided.py`; `run_tests` options.
  `repro.run_stage`; `pipeline.pipeline_jobs`; `repro run --analyse-only`.
- `DockerSandbox.overlay`; `JobContext.log` takes the schema's levels only.
- Fixtures `flaky` and `test-tamper`, expectations for five fixtures.

## Evidence
- Windows with Docker Desktop: all five fixtures give exactly their expected evidence through
  `reproduce`, and `honest-fix` and `test-tamper` through `repro run` (process sandbox), with
  `test-tamper` also in containers (L3, network enforced). pytest 1019 → 1063 (1061 pass and 2
  skip).
- CI run: linked in the PR (#43).

## Deviations from spec
- DeFlaker's label does not replace reruns (Design notes).
- Gate C's browser spec now runs `repro run --analyse-only`: Gate C is the build stage, and the
  run stage's own end-to-end check is Gate D's.

## Known gaps
- A2 reverses the order of the selected tests only; tests that were not selected still ran
  before them in A.
- The test diff's strength heuristics see `assert`, unittest `assert*` and `pytest.raises`;
  other assertion libraries are only `test_modified` (THREAT_MODEL T10).
- A test whose function is outside the snapshot root (a plugin's test items) is classified but
  has no test diff.

## Dependencies added
None.

## Research notes
- ImpossibleBench (research/02 §1.9) and DeFlaker (research/02 §5.5), both already in the
  bibliography; reruns k = 3 and A/A2 policy from research/03 §10.

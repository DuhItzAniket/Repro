# H02 — Performance & scale

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | done |
| **Depends on** | H01 |
| **Branch / PR** | `phase/H02-performance` · [#72](https://github.com/DuhItzAniket/Repro/pull/72) |
| **Started / finished** | 2026-10-17 / 2026-10-17 |

## Objective
Repro runs in reasonable time on real repositories of increasing size, a second run of a change
is cheaper than the first, and the caches never change what the card says. Each target is set
from an earlier measurement and checked by a repeatable benchmark.

## Scope
- **A benchmark on three pinned real repositories** (`repro_bench.scale`). Three Pallets
  projects (BSD-3-Clause) of increasing size, cloned at run time and never vendored. Each change
  runs cold, then warm, into one fresh data directory. Rows go to `bench/results/scale.csv`.

  | Reference | Python at head | Change |
  |---|---|---|
  | itsdangerous | 15 files, 1,736 lines | `93ae366..7f4dcf8` (Gate C's pair) |
  | flask | 83 files, 18,334 lines | `de8429f..7203fea`, "Fix IPv6 server name parsing" |
  | click | 91 files, 29,214 lines | `6d5bac5..f67c2bb`, "Fix short help abbreviation" |

- **Profiling** each reference from its run's own events (stage and job timings), before and
  after each change below.
- **What the profile found, and the fixes:**
  - *Provisioning installed every dependency group.* `uv export --all-groups` pulled in
    documentation, type-checking and release tools. flask's environment held 80 packages and
    took 237 s to build; click's 74 packages took 193 s. Repro now installs the groups the
    tests need: `test`, `tests` or `testing` when present, else `dev`. flask's environment
    now holds 16 packages (6.3 s), click's 8 (5.0 s). A `requirements/` directory of test
    requirements (itsdangerous's) adds the project's own dependencies; such a project used to
    be of unknown kind.
  - *The project's pytest configuration was overridden whole.* `-o addopts=` also dropped
    click's `-m 'not stress'`: Repro collected 33,117 tests where click's own configuration
    selects 2,117. Base's mapped run hit the 900 s limit. The selection options of the
    project's `addopts` are now read from the file pytest would use and passed again
    (`runner/pytest_config`).
  - *Base and head ran one after the other.* They are separate sandboxes. Base's mapped run
    now runs with head's listing, base's second run with head's run, and each rerun of a flip
    on both sides at once. Each pair is recorded in a fixed order, so the log does not depend
    on which finished first.
  - *The timing pass timed tests too fast to time.* A test under the timing floor in every
    traced run is not a timing candidate. After the first ABBA block, a test whose every
    sample is under the floor on both sides is run no more. Both are reported as too fast to
    time, as before.
  - *A file name that is not UTF-8 failed the outcomes job* (click: a test writes one).
    Python holds the byte as a lone surrogate, which JSON cannot carry. Text now shows it
    escaped (`\udcff`), a target path as U+FFFD.
  - *In containers, none of the three could be installed.* A snapshot reaches its container as
    a tar stream, and every entry's time was zero (1970), so that a commit always gives the
    same stream. The project's own install builds a wheel, a zip, and a zip holds no time
    before 1980. All three references build with flit_core, and the install failed ("ZIP does
    not support timestamps before 1980"). Neither side had an environment: flask and click
    were UNVERIFIABLE. The container tests' projects (hatchling, pdm, poetry, setuptools)
    installed, so the tests never met it. Each entry now carries the commit's committer time,
    as `git archive` gives a commit's files (git 2.55.0's documentation), and never earlier
    than 1980-01-02.
- **Caches that do not change the card.** A run from the cached base map used to differ from
  the run that made the map in three ways:
  - base's first run never reached the cockpit;
  - base's collection errors were not reported, so their missing items vanished;
  - the attempts (network, process, file writes) of base's first run differed: the cold run
    reported those of tests outside the selection, the warm run its session's own.

  Now base's first run is observed in both. The map keeps the collection errors it was made
  with (map format 2). Of base's first run, only the selected tests' attempts count; its
  second run, over the same tests either way, reports the session's own. The log says where
  the map came from.

## Out of scope
- **Caching the import graph.** On click (91 modules), the import graph is ready about 1 s
  after the run starts, snapshots included; there is little to save.
- **Reusing test outcomes across runs.** A run's evidence is what it measured: every run runs
  its tests again. A re-run reuses the dependencies' environments and base's map; `repro
  replay` shows a past run without running anything.
- **Faster timing runs.** Each sample is a pytest process (D07's design). On flask, the timed
  tests' bodies take 0.36–0.52 s of each 2.2–3.0 s timing run; the rest is the process, its
  collection and the fixtures. Fewer runs would mean fewer samples than research/03 §9 asks
  for; several samples per process would no longer be independent runs.

## Design notes
- **What a project selects is part of the project.** Repro overrides `addopts` so that
  coverage, parallel workers, `--lf` or `-x` cannot change a run. But `addopts` is also where a
  project says which tests it runs. Running tests its authors deselect judges the change on
  them and can take hours. Only selection, collection and strictness options are kept; output,
  plugin and reporting options are not.
- **A cache is correct only if the card cannot tell.** Each cache is checked by running a
  change twice and comparing the cards. The attempts rule is the subtle one: made with the
  map, base's first run runs every base test, from the cached map only the selected ones.
  What a test outside the selection attempted is not about the change, so it is left out of
  both; the session's own attempts come from base's second run, which is the same either way.
- **Pairs, not a pool.** Only runs with no data dependency run at once, two at a time, on
  different sides. Each pair is recorded in the order the sequential code used, so the logs
  and the golden cards are unchanged.
- **Pruning, and what it gives up.** A test dropped after the first block is not assessable
  from the samples it has, by D07's own rule (both medians under the floor). With ten samples
  it could have crossed the floor only if its later runs were slower than all four so far.
  The tests that remain still get ten samples a side, and the A/A noise floor is computed from
  them, as before.

## Acceptance criteria
- [x] AC1 (roadmap): targets set from A08 and D-stage measurements are met and recorded.
  - T1 (D03: provisioning from a reused environment took 1.4–4.6 s a side in the process
    sandbox, about 6 s in a container with the tests' run): a warm run reuses both sides'
    dependencies' environments, within 4.6 s a side (process) or 6 s (container).
  - T2 (A08 defect 3, D05): Repro collects the tests the project's own configuration selects.
  - T3 (D06: base's map is cached): a warm run does not run every base test again. Its card
    has the same status, selected tests, gap items and missing items as the cold run's, and
    the same evidence apart from timings. Which tests are timed varies between any two runs
    (flask: 38 to 40 in four runs): noise decides which tests near the 5 ms floor clear it.
  - T4 (H01: 900 s per run): every reference's run, cold or warm, ends with a card in under
    half that.
- [x] AC2: the benchmark is repeatable and checked: one command, pinned commits, results in a
  CSV, and a nightly job that fails when a target is missed.

## Test plan
| Criterion | Check |
|---|---|
| AC1 T1, T3, T4 | `uv run python -m repro_bench.scale --repos <dir> --append --check`: `provision_s`, `env_cached`, `map_cached` and the card's counts per pass; `test_bench_scale.py` for the check itself |
| AC1 T2 | `test_pytest_config.py`; `test_pytest_plugin.py` (the suite's `-m "not stress"` deselects a test that fails if it runs); click's selected tests against pytest's own summary |
| AC1 T3 | `test_twosided.py::test_a_cached_map_reports_what_the_run_that_made_it_did` |
| — | `test_perf.py::test_tests_too_fast_in_the_first_block_are_timed_no_more`; `test_run_stage.py[perf-regress]`; `test_provision_project.py`; `test_bus.py` (an undecodable name) |
| AC2 | `bench/results/scale.csv`; the nightly `scale` job |

---
*Filled in at the end of the phase:*

## What shipped
- **Code.**
  - `repro.runner.pytest_config`: the selection options of the project's `addopts`, from the
    file pytest would use; `run_tests` passes them after `-o addopts=`.
  - `repro.provision.project`: the dependency groups the tests need (`chosen_groups`,
    `export_options`); a `requirements/` directory of test requirements.
  - `repro.runner.twosided`: runs on both sides in pairs (`pair`); `TwoSided.detections`; the
    map's collection errors in `problems`. `TestMap.uncollected`, map format 2.
  - `repro.runner.perf`: the first block's pruning (`time_tests`); the run stage's
    `too_fast_to_time` before it.
  - `repro.scrub`: encodable text (`encodable`); targets with U+FFFD.
  - `repro.gitops.snapshot.tar_tree`: the commit's time on every entry, at least 1980-01-02.
  - The run's log line `base map: N tests, made by running every base test` or `from the
    cache`.
- **Benchmark.** `repro_bench.scale` (`--append`, `--check`, `--keep`, `--only`,
  `--sandbox`); `bench/results/scale.csv`; the nightly `scale` job.
- **Docs.** ARCHITECTURE §4 (what is kept of a project's `addopts`); TEST_STRATEGY layer 9;
  `bench/README.md`; CLAUDE.md (the benchmark's command); the paper log.
- **Tests.**
  - New: `test_pytest_config.py` (11), `test_bench_scale.py` (2), and in
    `test_provision_project.py` (2), `test_twosided.py` (1), `test_perf.py` (1),
    `test_bus.py` (1), `test_gitops_snapshot.py` (1).
  - The plugin suite's `pytest.ini` now also deselects a stress test that fails if it runs.
  - Updated: the tar stream's times; `perf-regress`'s samples per test.

## Evidence
- **Times.** Windows 11, 24 logical CPUs, process sandbox; the recorded run is in
  `bench/results/scale.csv`, with the spread over today's runs of the final code in
  brackets. "Before" is the span of one run's events on H01's code (`ebd612e`), same machine.

  | Reference | Before H02, cold | After, cold | After, warm |
  |---|---|---|---|
  | itsdangerous | 38 s | 17.7 s (16–18 s, 3 runs) | 15.5 s (15–16 s) |
  | flask | 402 s | 109.8 s (85–110 s, 3 runs) | 90.4 s (81–92 s) |
  | click | 1,151 s, base's run stopped at its 900 s limit | 34.1 s (34–41 s, 3 runs) | 25.7 s (24–27 s) |

- **In containers** (Docker Desktop 29.8.2, Linux containers): itsdangerous 26.3 s cold and
  26.2 s warm, flask 96.4 s and 97.7 s, click 49.5 s and 46.3 s. flask has 9 gap items here and
  16 on the host: 7 of its CLI tests fail on both sides on Windows (F2F, pre-existing), not
  in Linux.
- **The targets**, in the recorded runs (`--check` passed for both sandboxes):
  - T1: warm provisioning 1.3, 1.8 and 1.7 s a side (process), 4.5–4.8 s (container).
  - T2: Repro selects click's tests as its configuration does: 2,117 on head, where pytest's
    own run reports "2014 passed, 102 skipped, 31000 deselected, 1 xfailed".
  - T3: every warm run used the cached map. Status, selected tests, gap items, missing items
    and evidence were the same as the cold run's; the tests timed were 38 and 38 (process),
    7 and 6 (container).
  - T4: the longest run took 109.8 s, under half the 900 s limit.
- **Where flask's time goes now** (one cold run of 80 s): the timing pass's 20 pytest
  processes took 48 s, the timed tests' bodies about 0.4 s of each.
- **Local suite**, Windows with Docker Desktop running (`-m "not agent_eval and not chaos"`):
  1,854 passed, 2 skipped (POSIX-only checks), 1 failed, `net-call` (Known gaps).
  `pytest -m chaos`: 7 passed. `pytest -m agent_eval`: passed.
- CI run: linked in the PR (#72).

## Deviations from spec
- **Caching: environments and the base map, not the graph.** Both were already cached (D03,
  D05). H02 made the map's cache report what the run that made it did, and leaves the import
  graph uncached (Out of scope).
- **Incremental re-runs** are a warm run: the environments and base's map are reused, and every
  test runs again, because the evidence is what the run measured.

## Known gaps
- **Paths that resolve elsewhere look like writes outside the sandbox.** The audit hook
  compares a written path with its roots as written, not resolved. On this machine, Repro run
  from a packaged desktop app writes through a redirected folder, so tests that resolve
  `tmp_path` produce `file_attempt` records (flask: 86 a run). They are the same in every run,
  and no reference enables an invariant that reads them. A link or a short (8.3) name would do
  the same. H03 resolves both sides.
- **Evidence summaries carry absolute paths**, the home directory included, as the cards'
  missing items no longer do (H01). H03's secret-scrubbing audit of logs and events covers it.
- **With Docker, "cold" is not cold for the dependencies.** Their environments are Docker
  volumes, shared by every data directory; the benchmark reports whether a run reused them.
- **`net-call`'s end-to-end test is flaky on Windows with Docker Desktop running.** Its head's
  refused connection sometimes costs enough for the test to be timed, and slower on head, as
  it is, so the run has a `perf_diff` its expectation and golden card do not list. It failed
  on main's code too (1 of 14 runs; 5 of 23 here, one of them a package-index request that
  failed). Without Docker Desktop, and in CI, it has not failed. The fixture's timing needs to
  be made deterministic (a follow-up).

## Dependencies added
None.

## Research notes
- What made real repositories slow was the target's own configuration, read wrongly: every
  dependency group installed, and the project's deselection overridden. Toy fixtures have
  neither. A benchmark on real projects of increasing size found both in its first run.
- Running a change twice and comparing the cards is a cheap oracle for caches. It found three
  differences the fixture suite had never shown. It also needs care: which tests are timed
  legitimately differs between any two runs, so the comparison leaves timings out.

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
- **On Linux** (the nightly `scale` job, Ubuntu on GitHub's runner, process sandbox, run
  39026482930 on this branch): itsdangerous 4.8 s cold and 4.0 s warm, flask 35.0 s and
  36.2 s, click 19.3 s and 12.9 s; `--check` passed. flask has 9 gap items there, as in a
  container.
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
  be made deterministic (a follow-up). *Resolved on 2026-10-20: see "Follow-up: `net-call`'s
  timing" below.*

## Dependencies added
None.

## Research notes
- What made real repositories slow was the target's own configuration, read wrongly: every
  dependency group installed, and the project's deselection overridden. Toy fixtures have
  neither. A benchmark on real projects of increasing size found both in its first run.
- Running a change twice and comparing the cards is a cheap oracle for caches. It found three
  differences the fixture suite had never shown. It also needs care: which tests are timed
  legitimately differs between any two runs, so the comparison leaves timings out.

## Follow-up: `net-call`'s timing (2026-10-20)
Branch `fix/net-call-timing`. The fixture came with F03, so the fix carries F03's ID.

- **Where the time went.** Each step of head's `_ping` was timed inside a test, on its first
  call in a fresh pytest process, through Repro's own `ProcessSandbox`, plugin and audit hook:
  `plugin_env` with the guard on, 10 processes per setting. Python 3.13.13, Windows 11, Docker
  Desktop 29.8.2 running. Medians:

  | First call in the process | Sandbox: guard and hook | Host environment: guard, no hook | Sandbox's environment: guard, no hook |
  |---|---|---|---|
  | `getaddrinfo("192.0.2.1", 80, 0, SOCK_STREAM)` | 4.03 ms | 3.95 ms | 3.99 ms |
  | `socket()` | 0.056 ms | 0.052 ms | 0.057 ms |
  | `connect`, refused by the guard | 0.063 ms | 0.027 ms | 0.029 ms |

  The lookup is the cost; the same lookup again in that process takes 0.02 to 0.04 ms. The
  guard refuses in all three settings; the hook adds about 0.03 ms to the refused connection,
  its record.
- **Why the first lookup is slow.** CPython's `getaddrinfo` encodes a `str` host with the
  `idna` codec and passes `bytes` as they are. In `socket_getaddrinfo`
  (`Modules/socketmodule.c`, branch 3.13), the call is
  `PyUnicode_AsEncodedString(hobj, "idna", NULL)`,
  https://github.com/python/cpython/blob/3.13/Modules/socketmodule.c **[V]** 2026-10-20. The
  codec's module imports `stringprep` and `unicodedata` (`encodings/idna.py` and
  `stringprep.py` of the installed 3.13.13) **[V]**. The first lookup loads `unicodedata.pyd`.
  With `b"192.0.2.1"`, `encodings.idna` is not imported, and the first lookup takes 0.03 ms.
- **Per interpreter.** The first lookup of the `str` host, in fresh `python -I` processes
  with `re` already imported, 7 each:
  - 3.12.13: 8.7 to 10.2 ms;
  - 3.13.13: 3.9 to 4.4 ms;
  - 3.14.4: 9.5 to 10.6 ms;
  - 3.15.0: 11.6 to 12.7 ms;
  - with `bytes`, 0.02 to 0.10 ms on all four.

  On this machine, 3.14's cached bytecode for `stringprep` is stale and cannot be replaced
  (`python -v`: "bytecode is stale", "could not create … FileExistsError"), so it is compiled
  on every import. 3.12 and 3.15 were not checked. The cost depends on the interpreter's
  install as well as the machine.
- **Why it flaked.** Each timing sample is a fresh pytest process, so head paid the import in
  every sample. Before the fix: 20 sequential runs of the end-to-end test on `349d011`, Docker
  Desktop running.
  - Head's samples: median 4.44 ms (3.72 to 9.47 ms, 80 samples). Base's: about 0.11 ms.
  - Every run timed the test: in each, a traced run's call was at 5 ms or more.
  - 1 of 20 runs failed: the median of head's ten samples reached 5 ms, and the run reported
    `perf_diff:regression`.

  The margin was about half a millisecond, so any background load could decide the verdict.
  Why Docker Desktop made failures more frequent was not isolated.
- **Not a Repro bug.** The import belongs to the code under test and costs the same outside
  the sandbox. A real change like head's is slower, and its timing is reported from whichever
  side of the floor the run lands on (AC1 T3 above).
- **The fix.** The fixture pings `b"192.0.2.1"`, so its lookup skips the codec. The guard and
  the hook see the same lookup and connection (`192.0.2.1:80`, two `network_attempt`
  records), and `no_network` fails on them as before.
  - In the sandbox, head's first ping now costs 0.23 ms (0.21 to 0.32 ms, 20 processes),
    against 3.92 ms (3.35 to 4.90 ms) with the `str` host.
  - Only head's commit changes on the golden card.
- **After the fix:** 25 sequential runs of the end-to-end test on `b2f9256` with the fix,
  Docker Desktop running.
  - 25 of 25 passed.
  - Head's samples: median 0.93 ms (0.78 to 1.42 ms, 50 samples). Base's: median 0.106 ms.
  - In every run, the first block's four samples were under the floor, the test was timed no
    more, and the card lists it as too fast to time.
  - Three copies of the test at once, twice: 6 of 6 passed, head's samples 0.88 to 1.38 ms.
  - In the Docker sandbox (Linux, L3, network enforced), one run: the same two attempts,
    `no_network` failed, FLAGGED, and no test was timed at all.
- **The first ABBA block still runs.** Head's traced call takes 7.7 to 9.5 ms and base's 2.6
  to 3.3 ms (3 runs); the map and the tracer account for the difference. So the shortcut above
  (under the floor in every traced run) does not apply. The untraced samples prune the test
  after the block, and the outcome rests on them, as D07 intends.
- **To reproduce.**
  - The first lookup:
    `python -I -c "import re, socket, time; t = time.perf_counter(); socket.getaddrinfo('192.0.2.1', 80, 0, socket.SOCK_STREAM); print((time.perf_counter() - t) * 1000)"`.
    Then the same with `b'192.0.2.1'`.
  - The end-to-end runs: `uv run pytest
    "engine/tests/test_run_stage.py::test_a_run_reproduces_the_fixture[net-call]"
    --basetemp=<dir>`, one at a time, then read the `perf.sample` events in
    `<dir>/test_a_run_reproduces_the_fixt0/run.jsonl`.
  - Keep `<dir>` short: past about 260 characters, the fixture builder's `git add` fails with
    "Filename too long".
- **Measured on the way, outside Repro.** The hook's fifth record in a process took about
  1 ms. Plain Python appends to a fresh file on the same disk show the same thing: the write
  that takes the file past about 600 bytes costs up to 1.3 ms (20 files, 150-byte lines).
  Head's call writes only the log's first two records.

# D04 — Repro pytest plugin v1 & deterministic run config

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | in progress |
| **Depends on** | D03 |
| **Branch / PR** | `phase/D04-pytest-plugin` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
A side's tests run under Repro's own pytest plugin and Repro's own command, whatever the project
configures, and report each test's outcome through a results file the engine reads as untrusted
input. The same tests run twice give the same outcomes.

## Scope
- **The plugin** (`repro_pytest`, in `engine/src/repro/sandbox/_hook/`): the standard library and
  pytest only, for Python 3.12 to 3.15. It writes `results.jsonl` in `REPRO_OUT` as the run goes:
  one record per test (outcome, duration, the phase where it did not pass, the failure's text),
  one per module that failed to collect, and a session record last (exit status, tests
  collected, pytest and Python versions, seed). Outcomes: `passed`, `failed`, `error` (setup or
  teardown failed), `skipped`, `xfailed`, `xpassed`, as in the event schema's `TestOutcome`.
- **Fixed seeds**: before each test's setup, `random` is seeded from `REPRO_SEED` and the test's
  node ID, so a test's draws do not depend on which tests ran before it.
- **Net guard** (`REPRO_NET_GUARD=1`): a TCP connection to anything but loopback, and resolving
  any name but `localhost`, fail at once. Each refusal is raised as the audit event it stands
  for, so the audit hook (D01) records it as network evidence.
- **The command and environment** (`repro.runner`): `-o addopts=`, `-p repro_pytest`,
  `-p no:randomly`, `-p no:xdist`, `-p no:cacheprovider`, `--continue-on-collection-errors`,
  `--junitxml`; `PYTHONUTF8=1`, `TZ=UTC`, `LC_ALL`/`LANG=C.UTF-8`, `REPRO_SEED`, the net guard, on
  top of the sandbox's minimal environment with `PYTHONHASHSEED=0`.
- **`run_tests`** runs node IDs (or every test) in either sandbox and returns the execution, the
  results read back (bounded, malformed records counted, a run with no session record
  incomplete) and the JUnit XML.
- `HostProvisioner(python=...)`: an environment with another of uv's Pythons (the plugin's
  matrix); runs still use 3.13 on both sides.

## Out of scope
- Selecting tests (D05), running both sides and comparing them, reruns and flake control (D06),
  timing (D07), tracing (Stage E).

## Design notes
- **Repro's own results, JUnit kept aside.** The plugin decides one outcome per test from its
  three phases: a setup that does not pass decides it; otherwise the call; a failing teardown
  turns a pass into an error and leaves a failure a failure. JUnit XML is written for people
  and other tools but not read: pytest 9.1.1 lists a teardown error as a test case of its own,
  beside the test's own entry (measured here: 20 entries for 18 tests and one module that did
  not import).
- **One broken module does not hide the rest.** Without `--continue-on-collection-errors`, pytest
  stops before running any test when a module fails to import; a change that breaks one test
  module would hide every other outcome.
- **The plugin's results are the target's to forge.** It runs in the target's process. The reader
  bounds what it reads (64 MiB, 200,000 records, 2,000 characters a field), counts malformed
  records rather than trusting them, and reports a run without a session record (a crash, a
  kill, a timeout) as incomplete, never as passing (THREAT_MODEL T11).
- **Written as it goes.** A test's record is flushed after its teardown, so a process that dies
  leaves the records of every test before it.
- **Expected writes are not detections.** The process sandbox takes `writable` directories (the
  results directory), so the plugin's own files are not reported as writes outside the run.
- **Where the plugin lives.** ARCHITECTURE §3 names a `plugin/` package shipped into the sandbox;
  it is `sandbox/_hook/`, the directory both sandboxes already put first on `PYTHONPATH` (mounted
  read-only at L3) for the audit hook.

## Acceptance criteria
- [x] AC1 (roadmap): the plugin's own test matrix passes on 3.12, 3.13, 3.14 and 3.15.
- [x] AC2 (roadmap): the same test run twice gives the same outcomes.
- [x] AC3: every outcome and phase is reported as pytest decides it; a collection error does not
  stop the run; the project's `addopts` is overridden.
- [x] AC4: a run that dies or times out is incomplete, with what it wrote before; malformed
  records are counted and skipped.
- [x] AC5: the net guard refuses non-loopback connections and name resolution at once, keeps
  loopback working, and the audit hook records each refusal.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_pytest_plugin.py::test_the_suite_on_each_python[3.12…3.15]`: the fixture suite (`data/plugin_suite`), provisioned with each of uv's Pythons, in the process sandbox on Windows and Ubuntu (CI) |
| AC2 | `test_the_same_run_twice_gives_the_same_outcomes`, `test_a_draw_does_not_depend_on_what_ran_before`, `test_the_seed_decides_the_draws`; `test_the_suite_in_a_container` (twice, at L3) |
| AC3 | the suite: pass, fail, two skips, xfail, xpass, strict xpass, setup and teardown errors, a failure with a broken teardown, parametrized cases, a module that does not import, `addopts = -x` in `pytest.ini` |
| AC4 | `test_a_run_that_dies_is_incomplete_not_passing` (`os._exit` mid-run), `test_a_run_killed_for_its_timeout_is_incomplete`; `test_runner_pytest.py` (malformed records, bounds, limits) |
| AC5 | the suite's `test_network.py`, and the network detections of each matrix run |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/sandbox/_hook/repro_pytest.py`; `engine/src/repro/runner/` (`pytest.py`).
- `ProcessSandbox.run(writable=...)`; `HostProvisioner(python=...)`.
- Fixture suite `engine/tests/data/plugin_suite/` (pytest 9.1.1 and its dependencies pinned).
- Tests: `test_pytest_plugin.py` (11, one with D03's pytest 8.3.3 fixture), `test_runner_pytest.py`
  (20). pytest 959 → 990 (988 pass and 2 skip on Windows with Docker Desktop).

## Evidence
- Windows: the suite gives the expected outcomes on CPython 3.12.13, 3.13.13, 3.14.4 and 3.15.0
  (uv's builds), and in Repro's image at L3 with Docker Desktop; both plugin test files take
  about 70 s here, provisioning included.
- `TZ=UTC` is honoured on Windows: on a host whose own time zone is not UTC, the suite's
  `time.localtime(0)` is midnight on every Python (research/03 §10 had this unverified).
- CI run: linked in the PR.

## Deviations from spec
- IMPLEMENTATION_PLAN asks for the matrix "inside containers". Repro's image has one Python
  (3.13), so the 3.12–3.15 matrix runs in the process sandbox with uv's interpreters, on Windows
  and Ubuntu; the container run covers 3.13.
- The plugin imports pytest (ARCHITECTURE §3 says stdlib-only): it is a pytest plugin, so pytest
  is always there. It imports nothing else.

## Known gaps
- Only `random` is seeded; other generators (NumPy's, for one) are not.
- The net guard stops TCP connections and name resolution in Python; UDP `sendto` and C
  extensions are only recorded by the audit hook (and stopped by the container at L3).
- Tests that need the network fail on both sides; whether a result depends on the network is
  D06's to report.

## Dependencies added
None.

## Research notes
- pytest 9.1.1's own `--help`: `--continue-on-collection-errors` "Force test execution even if
  collection errors occur"; `-p name` with the `no:` prefix avoids loading a plugin;
  `-o`/`--override-ini` overrides a configuration option. Measured here, `uv run pytest --help`.
- `sys.audit` raises an auditing event and triggers any active auditing hooks (added in 3.8).
  https://docs.python.org/3/library/sys.html#sys.audit **[V]** 2026-10-15
- RFC 5737 reserves 192.0.2.0/24 (TEST-NET-1) for documentation; such addresses "SHOULD NOT
  appear on the public Internet". https://www.rfc-editor.org/rfc/rfc5737 **[V]** 2026-10-15
- pytest 9.1.1 on PyPI: `Requires-Python >=3.10`, classifiers 3.10 to 3.15, uploaded 2026-06-19.
  https://pypi.org/project/pytest/9.1.1/ **[V]** 2026-10-15

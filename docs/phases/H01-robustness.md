# H01 — Robustness & failure modes

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | in progress |
| **Depends on** | G09 |
| **Branch / PR** | `phase/H01-robustness` · PR pending |
| **Started / finished** | 2026-10-17 / — |

## Objective
Every way a run can fail is catalogued, ends in an explicit missing item and the right status,
and reads as something a user can act on. Each is met for real by a test.

## Scope
- **The failure catalogue** (`docs/FAILURES.md`): each failure, what the run records, its
  effect on the card, what resolves it, and its test. Residual risks are listed, not hidden.
- **A partial run is never a pass.** A selected test that no run reported has no outcome. Until
  now, only a run with no outcome at all was UNVERIFIABLE. A head run that timed out after
  reporting some tests left the rest out silently, and the card could be VERIFIED. The status
  rules now say `N of the M selected tests have no outcome` (`tests_not_run`).
- **Memory.** A new missing reason, `memory_limit`. A run that reached its sandbox's memory
  limit says so, recognised three ways:
  - Docker stopped it;
  - its peak came within 5 % of the limit (Windows);
  - tests failed with `MemoryError` (any platform; the process sandbox refuses the
    allocation).

  A probe run that ended early is no longer always called a timeout.
- **Settings.** `test_timeout_s` (900 s) and `memory_limit_mb` (4096) set each sandboxed
  run's limits, until now fixed in code.
- **Readable reasons.**
  - A failed job's item names the error, by its type and the first line of its message (home
    written `~`), not only its type.
  - A collection error reports the line that names the error, not a cut traceback with host
    paths, with a resolution.
  - A run that timed out says how long it ran, not "exit status None".
  - A sandbox that cannot start (Docker missing or stopped) says so, with advice that fits:
    start Docker, or use the process sandbox.
  - Provisioning reasons lose the home directory.
  - The Markdown card shows each item's resolution.
  - "1 test runs", not "1 tests run".
- **Outages.**
  - The OpenAI-compatible backend now also retries an API it cannot reach and an answer it
    cannot use (not JSON, no choices). An unusable answer used to crash the job.
  - Any failure of the probe writer is an `agent_failed` item. Hypothesis's probes run
    anyway.
- **`repro run` without git** prints a message and exits 2, not a traceback.
- **Chaos tests** (`test_failures.py`, marker `chaos`, CI job `chaos` on Ubuntu and Windows).
  Each runs `repro run` end to end into one failure:
  - a head that breaks a test module's import;
  - a head that hangs;
  - a head that exhausts memory;
  - a head whose build cannot work offline;
  - an API nobody answers;
  - Docker asked for and missing;
  - git missing.

## Out of scope
- **Isolating the tracer's callbacks** from the test they observe (H03; listed as residual).
- **Filling a disk to test the store's failure** (residual).

## Design notes
- **The rule reads the log, not the failure.** "Selected but without an outcome" is computed
  from `test.selected` and `diff.outcome`, so it holds however a run stopped: a timeout, a
  crash, memory, a cancelled container. It needs no list of failure kinds.
- **Memory is recognised where each platform shows it.** Windows' Job Object and POSIX's
  `RLIMIT_AS` refuse the allocation, and the test fails with `MemoryError`; Docker's kernel
  kills the process. A test that fails only on head for want of memory stays a P2F (FLAGGED).
  The change may well use more memory, and the item says the limit was reached.
- **Readable, not complete.** The card carries the error's first line; the whole message
  stays in the run's log. A card may be shared, so what it carries is free of the machine.

## Acceptance criteria
- [ ] AC1 (roadmap): every catalogued failure has a test and a user-readable reason.
- [ ] AC2: no failure in the catalogue can leave the card VERIFIED.
- [ ] AC3: chaos tests run in CI on Ubuntu and Windows.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `docs/FAILURES.md`'s Test column; `test_failures.py` checks each reason is one line, free of tracebacks and the home directory |
| AC2 | `test_failures.py`: each run's status; `test_status.py`: *a selected test unreported* |
| AC3 | The `chaos` job |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence
- CI run: linked in the PR.

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes

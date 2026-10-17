# Stage H gate — Hardening & first release

| | |
|---|---|
| **Phases** | H01–H06 |
| **Release** | `v1.0.0` |
| **Gate date** | 2026-10-17 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate H) | Result | Evidence |
|---|---|---|
| Install-from-scratch tests pass on Windows and Linux | pass | CI's `install` job, on Ubuntu and on Windows, for every change: the release's two wheels, built by `scripts/build_wheels.py`, installed with the README's one command into a tool directory of their own, then `repro --version`, `repro doctor` and a first run on a small repository, whose card must be VERIFIED with a test run (H06), all inside ten minutes. On `main` at 0fdc8e8 ([CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488)): Ubuntu 27.2 s, its first run at L3 in a container; Windows 30.1 s, its first run at L2 (GitHub's Windows runners have no Linux containers). Both cards VERIFIED, with a test run |
| | | The release workflow (`.github/workflows/release.yml`) builds and checks the same wheels for a published release and attaches them to it |
| The security review is complete | pass | H03: each of THREAT_MODEL's 19 threats names the tests that meet its mitigation, or its residual risk (§7), and `test_threat_model.py` fails when one lacks a row or names a missing test. The container escape suite runs at L3 and under gVisor (L4) in CI; the dependency audit (pip-audit, `pnpm audit`) runs on every change. H06 removed the last host mount from the containers and the session token from the server's log |
| The user documentation is complete | pass | H06: `docs/guide/` (quickstart, reading a card, `repro.yml`, troubleshooting, for contributors) and a recorded demo. A reviewer given only the guide completed the quickstart with no blocker. The owner will also run it in person |
| `v1.0.0` is tagged and published | pass | Annotated tag `v1.0.0` on the gate's squash commit, and the GitHub release with its two wheels attached by the release workflow |

## Phases
| Phase | PR | Commit on `main` | What it brought |
|---|---|---|---|
| H01 | [#71](https://github.com/DuhItzAniket/Repro/pull/71) | ebd612e | The failure catalogue (`docs/FAILURES.md`) and a chaos test for each failure, through `repro run`, on Ubuntu and Windows |
| H02 | [#72](https://github.com/DuhItzAniket/Repro/pull/72) | 43a2eb8 | `repro_bench.scale` on three pinned Pallets changes, and what made real repositories slow (dependency groups, the project's own deselection, paired runs) |
| H03 | [#73](https://github.com/DuhItzAniket/Repro/pull/73) | dcdb25f | The threat model traced to tests, the API's session token, gVisor (L4), seven more container escapes, scrubbing of logs and of the home directory, the dependency audit |
| H04 | [#74](https://github.com/DuhItzAniket/Repro/pull/74) | 1987814 | `repro export` to an in-toto Statement with Repro's predicate (round trip exact), SARIF 2.1.0 and JUnit XML, each checked against its schema |
| H05 | [#75](https://github.com/DuhItzAniket/Repro/pull/75) | b46a2f6 | The release's wheels, with the cockpit and the schemas inside; the README's install; the install check in CI; the release workflow |
| H06 | [#76](https://github.com/DuhItzAniket/Repro/pull/76) | 0fdc8e8 | The user guide and the demo; from its dry runs, an install that ran no test in a container, a card VERIFIED with no test run, the token in the server's log and class-body changes that selected no test, each fixed |

## CI matrix
| Job | Python | Node | Result | Run |
|---|---|---|---|---|
| test, ubuntu-latest (Docker: L3 suites required) | 3.13 | 24 | pass (8 min 27 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| test, windows-latest | 3.13 | 24 | pass (23 min 21 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| chaos, ubuntu-latest and windows-latest (each catalogued failure, through `repro run`) | 3.13 | — | pass (52 s; 2 min 2 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| install, ubuntu-latest (L3) and windows-latest (L2): the release's wheels, a first run | 3.13 | 24 | pass (46 s; 1 min 36 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| gvisor, ubuntu-latest (the container suite under gVisor, L4) | 3.13 | — | pass (1 min 12 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| agent evals, ubuntu-latest (five reviewed PRs from cassettes) | 3.13 | — | pass (1 min 21 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| Gate E, ubuntu-latest (containers) | 3.13 | 24 | pass (1 min 38 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| Gate D, ubuntu-latest (containers) | 3.13 | 24 | pass (1 min 49 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| Gate C, ubuntu-latest (`--analyse-only`) | 3.13 | 24 | pass (58 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| visual, ubuntu-latest + Playwright image | — | 24 | pass (2 min 36 s) | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| lint, security, gates, dependency audit | 3.13 | 24 | pass | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |
| dependency review | — | — | skipped: off until the repository's Dependency graph is enabled | [CI run 39047948488](https://github.com/DuhItzAniket/Repro/actions/runs/39047948488) on `main` at 0fdc8e8 (all of Stage H) |

The install job is Gate H's first criterion, met on both systems for every change since H05 and, since H06, only by a first run whose card is VERIFIED with a test run.

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 1,918 collected (1,819 at Gate G); Vitest 395 (385); Gates C, D and E; the agent evals; the chaos tests (8); the install check |
| Code | 22,806 lines of Python under `engine/src` (21,610 at Gate G); 19,461 in `engine/tests` (17,809); 985 in `bench/src` (732); 669 in `scripts`; 17,961 lines of TypeScript under `apps/web/src`; counted with `wc -l` over tracked files |
| User guide | 7 pages, 768 lines, under `docs/guide/`, and the demo's 4 stills and card |
| Scale (H02, Windows, process sandbox, cold) | itsdangerous 18 s, flask 110 s, click 34 s, from 38 s, 402 s and 1,151 s before H02 |
| First install and run (H06, Windows, Docker, uv's cache warm) | 44.4 s in all, the first run 32.5 s at L3 |

## Retrospective
- **The last phase found what the first five did not.** A reviewer with only the documentation
  installed the release as a user would and, on the first try, got a card with no test run:
  an installed Repro could start no test in a container on Windows. 1,896 tests had passed,
  and the install job checked that a run completed, not that it ran anything. Two more
  findings came from the second reviewer. An acceptance test of the shipped product, by
  someone who knows nothing of the code, belongs in every stage that ships something.
- **A rule that never fires reads as a pass.** The status rules were tested rule by rule, from
  inputs where tests had been selected. A run with nothing selected, because the runs that
  decide the selection had died, matched no rule and came out VERIFIED. "Nothing ran" is now a
  state the rules see directly (`run_incomplete`).
- **Real repositories, not fixtures, set the performance targets.** The two largest costs in
  H02 were in reading the target's own configuration wrongly, invisible on toy fixtures.
- **What leaves Repro is an attack surface.** H03 traced each threat to a test; H06 still found
  the token in a log line from the web server's own logger. Every output channel, a library's
  logs included, has to go through the same scrubbing.

# Stage D gate — Sandboxed two-sided execution

| | |
|---|---|
| **Phases** | D01–D07 |
| **Release** | `v0.4.0` |
| **Gate date** | 2026-10-15 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate D) | Result | Evidence |
|---|---|---|
| A branch that breaks one test shows exactly that test flipping (P2F) in Execution, Change routes and the index | pass | `apps/web/gate/gate-d.spec.ts` builds the `breaks-one` fixture (discount() changed so that `test_discount`, and only it, fails), runs `repro run` on it in full (containers, environments from the package index) and reads the cockpit through its panels' own views: Execution has that test failed in every HEAD run (H and three reruns) and nothing failed on BASE or A′; Change routes has the one changed function, routed to that test, its check flagged; the index has a single check, flagged, and the header agrees (1 check, 1 flagged). The `gate-d` CI job runs it on Linux; on Windows in Edge with Docker Desktop it took 49 s, and the cockpit was checked by eye (a "P2F test_discount" callout on the stage) |
| A branch that deletes or weakens a test is flagged as test tampering | pass | The same spec on `test-tamper` (head breaks divide() and percent(), deletes the assertion that caught the first and skips the test that caught the second): four `diff.tests` checks, all flagged (`assertion_removed`, `skip_added`, both edited tests' base versions failing on head), the two edited tests' outcomes unassessed (modified), the untouched test passed; the index reads "7 checks / 1 passed / 4 flagged / 2 unassessed". 1.4 min on Windows with Docker Desktop |
| The sandbox escape suite passes at the level the card claims | pass | `sandbox.ready` states the level reached and the network: `L3` / `enforced` in containers, `L2` (or `L1`) / `detected-only` in the process sandbox; `test_run_stage.py` asserts both. At L3 the escape suite (`test_sandbox_docker.py`: raw `_socket`, `ctypes`, a subprocess reaching out, writes outside the work directory, the host's `.git`) is blocked, required on CI's Ubuntu job (`REPRO_REQUIRE_DOCKER=1`) and run on Windows with Docker Desktop; at L2 `test_sandbox.py` checks detection and containment on Windows and Ubuntu. Runs listed under CI matrix |

## Phases
| Phase | PR | What it brought |
|---|---|---|
| D01 | [#38](https://github.com/DuhItzAniket/Repro/pull/38) | The process sandbox (L0–L2): minimal environment, the audit hook in every Python process, Job Objects on Windows and process groups with limits on POSIX; detections as evidence |
| D02 | [#39](https://github.com/DuhItzAniket/Repro/pull/39) | The container sandbox (L3): the commit streamed into a volume, hardened containers with no network, the escape suite |
| D03 | [#40](https://github.com/DuhItzAniket/Repro/pull/40) | Provisioning: the project's kind and requirements from its files, dependencies from wheels in a cached environment, the project built offline in the sandbox |
| D04 | [#41](https://github.com/DuhItzAniket/Repro/pull/41) | Repro's pytest plugin and command: per-test outcomes through a results file read as untrusted input, per-test seeds, a network guard, Python 3.12–3.15 |
| D05 | [#42](https://github.com/DuhItzAniket/Repro/pull/42) | Test selection from a per-test function map (`sys.monitoring`), import graphs and edited tests; `no_covering_test` gaps |
| D06 | [#43](https://github.com/DuhItzAniket/Repro/pull/43) | Two-sided execution in `repro run`: A, A′ and H, reruns of flips, outcome classes, the test-file diff, base tests on head |
| D07 | [#44](https://github.com/DuhItzAniket/Repro/pull/44) | The performance pass: ABBA timings, BCa intervals, Mann-Whitney with Benjamini-Hochberg, an A/A noise floor, a timing floor |

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest (Docker: L3 suites required) | 3.13 | 24 | pending | the gate PR's CI run |
| windows-latest | 3.13 | 24 | pending | the gate PR's CI run |
| ubuntu-latest, Gate D (Chromium from Playwright 1.64.0, containers) | 3.13 | 24 | pending | the gate PR's CI run |
| ubuntu-latest, Gate C | 3.13 | 24 | pending | the gate PR's CI run |
| ubuntu-latest + Playwright image (visual) | — | 24 | pending | the gate PR's CI run |

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 1,077 (Windows: all pass but 2 POSIX-only skips; 891 at Gate C); Vitest 377 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 296); 8 visual screenshots; Gates C and D |
| Engine code | 10,548 lines of Python under `engine/src` (5,690 at Gate C) and 7,517 in `engine/tests` |
| Web code | 11,845 lines of TypeScript outside tests and 5,300 in tests, under `apps/web/src` |
| JavaScript, gzip | 197.75 kB of the 300 kB budget (197.5 kB at Gate C) |
| A change through `repro run`, process sandbox | `honest-fix` (2 tests, a flip rerun 3 times on each side) end to end in about 20 s with the dependencies' environment cached, on Windows |
| A change through `repro run`, containers | Gate D: `breaks-one` 49 s, `test-tamper` 1.4 min (including the perf pass), on Windows with Docker Desktop |
| The plugin's suite | passes on CPython 3.12.13, 3.13.13, 3.14.4 and 3.15.0, under pytest 9.1.1 and 8.3.3 |

## Retrospective
- **Linux found what Windows hid.** The base and head sandbox jobs run in parallel and, on
  Ubuntu CI, built the same cached dependencies' volume at once; and Linux snapshots keep the
  symlinks a test relied on being skipped. Both were caught by CI on the D06 PR and fixed in it,
  each with a test that fails on the old code.
- **Wiring the cockpit found contract drift.** The gate's browser test showed the run stage
  approximating ADR-0015's check statuses and reporting A′ on the `base` side when the schema
  has `base_repeat`; both now follow the documents exactly, asserted end to end. A log level the
  schema forbids had sat in C08's snapshot job until D06 exercised it; log levels are now typed.
- **Reference implementations, not intuition, for statistics.** The BCa interval,
  Mann-Whitney and Benjamini-Hochberg were checked against SciPy 1.18.1 and statsmodels before
  any timing test relied on them.
- **Measure what the docs left open.** research/03 had `TZ` on Windows unverified; D04 measured
  it. uv's read-only cache (planned in ADR-0004) turned out impossible (D03), and equal code
  objects across files turned out to compare equal (D05); each changed the design, and each is
  recorded where the plan was.

## Gaps and owed items
- Stage D: target projects run on Python 3.13 only; the timing and noise floors are constants;
  dependency environments and container volumes are not pruned (Stage H); a module-scoped
  fixture is mapped to its first test only.
- Owed by the owner: the decision on rewriting the 32 merge commits on `main` that carry the
  personal email (#1–#34); making the `visual` and gate jobs required checks; the dependency
  graph and the Dependabot PR #17; the mid-laptop 60 fps check.

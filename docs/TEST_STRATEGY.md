# Repro — Test Strategy

Repro asks people to trust its verdicts, so its own test suite has to show that the verdicts
are correct, deterministic and safe to produce. This document defines the test layers, what
each one protects, where it runs, and the fixtures it relies on.

## 1. Principles

1. **Determinism is tested, not assumed.** The same inputs give the same normalised event log
   (IDs and timestamps stripped). Golden-log tests enforce this.
2. **Every verdict path has a fixture.** For each way a change can be wrong (test flip, silent
   behaviour change, API break, new dependency, network access, perf regression, flaky test,
   false claim, unclaimed change) there is a tiny target repo that exhibits it, and a test that
   asserts the resulting evidence and status.
3. **The UI is tested as a function of events.** Projections are pure, so they are unit tested
   by folding event logs. Rendering is tested by visual snapshots at frozen replay times.
4. **LLM behaviour is measured, not unit-tested.** Deterministic CI uses recorded responses.
   Real model behaviour is measured by an eval suite with tracked metrics.
5. **Isolation is attacked.** Sandbox tests deliberately try to escape and must be blocked or
   detected.

## 2. Layers

| # | Layer | Tooling | Scope | Runs on |
|---|---|---|---|---|
| 1 | Static | Ruff, type checker (strict), Biome, `tsc --noEmit` | All code | Every PR |
| 2 | Schema | JSON Schema meta-validation, codegen drift check, cross-language round trip | `packages/events` | Every PR |
| 3 | Unit | pytest, Vitest | Pure logic: diff parsing, graph, blast radius, canonicalisation, diffing, status rules, projections | Every PR |
| 4 | Property-based | Hypothesis, fast-check | Canonical hashing is stable and deterministic. Projections: `fold(all) == fold(snapshot) + fold(rest)`. Diff symmetry | Every PR |
| 5 | Golden logs | pytest approval tests | Normalised event log of each fixture repo run | Every PR (fast fixtures), nightly (all) |
| 6 | Integration | pytest + scripted fixture repos | Engine stages against real git repos, real venvs, real pytest | Every PR (Ubuntu + Windows, small set), nightly (full) |
| 7 | End-to-end | pytest (engine) + Playwright (web) | `repro run` → WS → UI shows the expected state | Nightly, stage gates |
| 8 | Visual regression | Playwright screenshot comparison | Cockpit at frozen replay times on the reference fixture log | Every PR touching `apps/web` |
| 9 | Performance | Custom harness + Playwright tracing | Frame-time budget, JS bundle size, engine wall-clock on reference repos | Bundle size on every PR; frame/engine perf nightly |
| 9a | Allocation | Vitest (heap after GC; V8 allocation counter) | 1,000 frames of the stress burst: flat heap; stage allocation per frame within budget | Every PR (Ubuntu + Windows) |
| 10 | Security | pytest sandbox suite | Network, filesystem, process, resource-exhaustion escape attempts | Every PR touching isolation; nightly |
| 11 | Agent evals | Eval harness over labelled PR set | Claim extraction, verdict accuracy, citation validity, cost | On agent changes (recorded), weekly live |
| 12 | Mutation | mutmut (engine core) | Measures how strong the suite is | Stage gates |

## 3. Fixture target repositories

Fixture repos are **generated at test time** by `engine/tests/fixtures/repo_builder.py` from
specs in `engine/tests/fixtures/specs.py`. They are never committed as nested `.git`
directories. Each spec is a tiny Python project on `main` (base) plus one or more head branches.
Specs are Python data, so a fixture's deliberately buggy code is never collected, linted or
type-checked as Repro's own code. Commits use fixed identities and dates, files are written
with LF, and global and system git config is ignored, so **commit SHAs are identical on every
OS**. A test pins them.

| Fixture | Head branch exhibits | Expected evidence | Expected status |
|---|---|---|---|
| `honest-fix` | Bug fix matching its claim | test flip fail→pass on claimed target only | VERIFIED |
| `silent-change` | Output change in an untested path | behaviour diff, no test outcome change | FLAGGED (unexplained) |
| `false-claim` | Claims "no behaviour change", changes behaviour | behaviour diff contradicting claim | FLAGGED |
| `api-break` | Removes a parameter of a public function | API diff | FLAGGED (`public_api_stable`) |
| `new-dep` | Adds a dependency | dependency diff | FLAGGED (`no_new_dependencies`) |
| `net-call` | Code under test opens a socket | network attempt recorded | FLAGGED (`no_network`) |
| `perf-regress` | Quadratic loop in hot path | perf diff over budget | FLAGGED (`perf_budget`) |
| `flaky` | Test with random outcome | observation marked `unstable` | not diffed; listed under *missing* |
| `noisy` | Refactors functions whose results or arguments carry time, random and set-order noise | every noisy call `unstable`, no behaviour difference (E03) | not diffed; listed under *missing* |
| `untested` | Change no test reaches | blast radius with no covering tests | UNVERIFIABLE / *missing* |
| `selection` | Changes whose affected tests a person can name, beside a test none affects | exactly the expected selected tests and reasons; no gaps (D05) | VERIFIED |
| `breaks-one` | A change that breaks exactly one test | that test P2F, in Execution, Change routes and the index (Gate D) | FLAGGED |
| `forbidden-path` | Edits a protected path | invariant failure | FLAGGED (`forbidden_paths`) |
| `test-tamper` | Deletes a failing assertion and adds `@pytest.mark.skip` to another test | `test_change` evidence. Base version of the edited test fails on head | FLAGGED |
| `probe-only` | Wrong output on inputs no existing test uses | `probe_diff` from generated probes | FLAGGED (Stage E06/G07) |
| `policy-weaken` | Head edits `repro.yml` to drop an invariant | policy change gap item. Policy still read from base | FLAGGED |
| `injection` | PR text and code comments contain instructions aimed at the reviewer agents | none. Verdicts unchanged vs the clean twin | same as clean twin |

Each fixture's expected outcome lives next to the specs as `<name>.toml` (stdlib `tomllib`).
From Stage D on, integration tests assert it end to end. Fixtures are added by the phase that
first needs them; `honest-fix` exists since A07, `selection` and `untested` since D05,
`flaky` and `test-tamper` since D06, `perf-regress` since D07, `breaks-one` since Gate D,
`noisy` since E03, `silent-change` and `false-claim` since E04, `api-break` and `new-dep` since
E05, `probe-only` since E06, `policy-weaken` since F01. A fixture's `behaviour` list holds
the missing items the behaviour comparison adds (E03), and its evidence lists its
`behaviour_diff` items (E04), with `[reproducers]` where a test checks them; `test_run_stage.py`
expects them with the rest.

### Golden files and property tests

- `golden` fixture (root `conftest.py`): compares text with `<test dir>/golden/<name>` using LF
  line endings on every OS. `pytest --update-goldens` rewrites the files; review the diff before
  committing.
- Event logs are compared in normalised form (`repro-events normalise`). Ids, timestamps,
  durations and producer version are replaced deterministically, and the result stays
  schema-valid.
- Hypothesis profiles: `dev` (default, explores new examples) and `ci` (derandomised,
  `HYPOTHESIS_PROFILE=ci` in CI, so failures reproduce). fast-check covers the TypeScript side.

## 4. Cross-platform

CI runs on `ubuntu-latest` and `windows-latest`. Tests cover:
- paths with backslashes, spaces, and long paths (`core.longpaths`),
- CRLF in target repos (hashing and diffing must be line-ending independent where intended),
- worktree creation and cleanup when files are locked (Windows),
- subprocess termination on timeout (Job Objects on Windows, process groups on POSIX).

## 5. Agent evaluation (summary)

Detailed in `docs/ARCHITECTURE.md` §Agents and `docs/paper/README.md`.
- **CI (deterministic):** agent calls are served from recorded responses keyed by prompt hash.
  A missing recording fails the test. It never silently calls the API.
- **Eval suite (live):** labelled PRs with expected claims and verdicts. Tracked metrics:
  claim-extraction precision/recall, verdict accuracy, **citation validity rate** (cited
  evidence exists and relates to the claim's targets), rejection rate, tokens and cost per PR.
  Results are appended to `bench/results/agent-evals.csv` with model ID and prompt version.

## 5a. Web quality gates (B12)

Each gate has a self-test in CI that injects a regression of its kind and requires the gate to
fail (`REPRO_INJECT`):

| Gate | Runs | Measure | Injected regression |
|---|---|---|---|
| Visual (`visual` job) | Every PR | Playwright, Chromium + SwiftShader, pinned image; screenshots at 12, 24.5, 30.5 s, the end, the drawer and reduced motion; at most 50 differing pixels | Every panel shifted by 1 px |
| Size (`test`, Ubuntu) | Every PR | size-limit: all shipped JS, gzip, 300 kB | 300 kB of random data in the entry chunk |
| Allocation (`test`) | Every PR | Heap plus ArrayBuffers after GC, 1,000 frames after warm-up, under 512 kB of growth | A 2 kB-per-frame leak |
| Perf (`gates`, nightly) | Every PR (self-test), nightly | Frame cost p50/p95 divided by a calibration workload, at most 30% above the CI baseline | 2 ms of work per frame |

Baselines (screenshots, perf) are produced by CI and committed from its artifacts, never
generated on a developer machine.

## 6. CI tiers

| Trigger | Jobs |
|---|---|
| PR | static, schema, unit, property, fast golden logs, small integration set, secret scan, bundle size, visual regression (if web changed) |
| Push to `main` | PR set + full integration |
| Nightly | full integration, end-to-end, performance, security suite |
| Stage gate | everything + mutation testing + live agent eval + benchmark smoke run |

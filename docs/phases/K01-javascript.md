# K01 — TypeScript/JavaScript targets

| | |
|---|---|
| **Stage** | K — Expansion backlog |
| **Status** | in progress |
| **Depends on** | — |
| **Branch / PR** | `phase/K01-javascript` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Repro for JavaScript and TypeScript changes tested with Vitest or Jest (roadmap: "Needs a
V8-side tracer design"). The design is ADR-0017. Its first phase, test outcomes base against
head, is built here. The rest awaits the owner's approval, because it changes the sandbox
image and the event schema's core.

## Scope
- **ADR-0017 (proposed)**: outcomes, then a test → function map from V8's precise coverage
  taken between tests, then function-level traces from a synchronous `load` hook that wraps
  changed functions, then the card with the TypeScript compiler API. The sources are read and
  quoted there.
- **`repro.jsts`** and **`repro js-run --repo --base --head [--json]`** (experimental):
  - **Detection**: a `package.json` naming Vitest or Jest (dependencies or the `test`
    script); the package manager is read from its lockfile, and a project without one is
    refused.
  - **Dependencies** come from the lockfile with lifecycle scripts off (`--ignore-scripts`).
    `--no-install` uses what the snapshot holds.
  - **The suite runs in Repro's process sandbox** (L2), with the runner's JSON report. One
    reader serves Vitest and Jest: Vitest's report is Jest's format.
  - **Comparison per test** (`<file>::<full name>`): regressions, fixes, new failing and new
    passing tests, removed tests.
  - **The summary** names the isolation level, and that a Node process's network use is not
    detected. Function-level traces are listed as missing.

## Out of scope
- ADR-0017's phases 2 to 4 (the map, the tracer, the card): proposed, awaiting approval.
- Running in a container: a Node image through `sandbox_image` (J04) is the path. The Docker
  sandbox's environment logic is Python's, and is phase 4.

## Acceptance criteria
- [x] AC1: a design for JavaScript targets, the V8-side tracer included, with its sources.
- [x] AC2: a Vitest or Jest change's tests run on base and on head, and their outcomes are
  compared, in the sandbox, with no code run while the network is reachable.
- [ ] AC3 (roadmap's full item): traces and a card. *Proposed, awaiting approval.*

## Test plan
| Criterion | Check |
|---|---|
| AC2 | `test_jsts.py`: detection (three runners and managers; refusals); the report read for every status; the comparison by category; a real change run with Vitest 5.0.4 on both sides of a tiny repository, finding the regression |

---
*Filled in at the end of the phase:*

## What shipped
- `docs/adr/0017-javascript-targets.md` (proposed).
- `repro.jsts`, `repro js-run`.
- Tests: `test_jsts.py` (8, one of them a real Vitest run).

## Evidence
- **A real run**: a tiny repository whose head changes `add(a, b)` from `a + b` to `a - b`.
  Each side was snapshotted and run with Vitest 5.0.4 in the process sandbox. Base had two
  tests passing. The comparison found `test/m.test.js::m adds` regressed and one test the
  same: `add(0, 0)` is 0 either way.
- CI run: linked in the PR.

## Deviations from spec
- Phase 1 of 4: the roadmap's item is the whole design. The rest needs the owner's approval
  (ADR-0017).

## Known gaps
- L2 only: a Node process's network use is neither blocked nor detected outside a container.
- Monorepos with several packages: the project is the repository's root `package.json`.

## Dependencies added
None in Repro. The target's own Node, package manager and runner are used.

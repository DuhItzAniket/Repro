# K08 — JavaScript: the card

| | |
|---|---|
| **Stage** | K — Expansion |
| **Status** | in progress |
| **Depends on** | K07 |
| **Branch / PR** | `phase/K08-js-card` |
| **Started / finished** | 2026-10-20 / — |

## Objective
ADR-0017's phase 4, first part. `repro run` reproduces a JavaScript or TypeScript change and
makes its card, as it does a Python change's. The owner split phase 4 on 2026-10-20:
- **K08:** the card, at L2;
- **K11:** L3 in a container with Node, and the TypeScript compiler API for the public API and
  for edited tests' assertions.

## Scope
- **The schema** (approved with ADR-0017).
  - `run.started.language`, `python` or `javascript` (TypeScript included). It is optional, so
    a log from before it still validates and replays to the same card.
  - `env.provisioned`: npm, pnpm and Yarn as project kinds, and `node_version`.
  - The card's conditions: `language`, `node_version` and `shuffle_seed`, present only when the
    log records a language.
- **The language** (`repro.language`): Python's files at the root, else a `package.json`.
  A root with both is Python's. `repro run --language` overrides it.
- **The analysis** (`repro.analysis.javascript`). It returns the same `StaticAnalysis` as
  Python's, so the build stage emits the same events.
  - Modules, and the imports between them: relative specifiers, resolved as Node and bundlers
    resolve them.
  - Changed functions from K06's scanner: added, removed, modified or moved, and `<module>`
    for code in no function.
  - Python's blast radius.
- **The run and diff stages** (`repro.js_stage`), with the same events as Python's.
  - **Sandboxes:** the process sandbox (L2), dependencies installed from the lockfile with
    lifecycle scripts off.
  - **Runs:** A and H, with the map and the traces. Then the selection, with the schema's
    reasons. Then A2, shuffled, and three reruns a side of each test that flipped. Outcomes are
    classified by Python's rules.
  - **A test's own code:** where the runner says the test starts, to the end of its call
    (`jsmap.own_lines`). An edited test is `modified`; a new one is `new`.
  - **Edited tests:** a removed test, a new skip, and fewer `expect`/`assert` calls are
    `diff.tests` findings.
  - **Behaviour:** K07's comparison, as evidence. A changed function the map says ran, with
    no call traced, is a `trace_unavailable` item.
  - **Dependencies:** `package.json`'s, and the installed packages.
  - **Invariants:** F02's.
  - **Missing items:** whatever Python checks and JavaScript does not yet: the public API,
    weakened assertions, timing, and the network (`no_network` is not evaluated).
- **The cockpit, the Markdown card and `repro doctor`** name Node.js.

## Out of scope
- L3 in a container with Node; the TypeScript compiler API; base's version of an edited test
  run against head: K11.
- Timing JavaScript tests; generated probes for JavaScript.
- Workspaces and monorepos: only the root project runs, and the card says so.

## Acceptance criteria
- [ ] AC1: `repro run` on a JavaScript change gives a schema-valid log whose card is assembled
  again from it byte for byte, with the language, Node.js and L2 in its conditions.
- [ ] AC2: a regression is a P2F confirmed by reruns, and a silent change is a behaviour
  difference: both flag the card.
- [ ] AC3: edited tests are named for what was done to them: removed, skipped, fewer
  assertions.
- [ ] AC4: a change that keeps behaviour can be VERIFIED, with every check not run listed as
  missing.
- [ ] AC5: a log from before K08 replays to the same card.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_js_stage.py`: three real Vitest changes through the pipeline; the log validated, the card regenerated |
| AC2 | `test_js_stage.py`: `add` breaks two tests (P2F, three reruns a side); `label` changes with every test passing |
| AC3 | `test_js_stage.py`: one assertion fewer, a `test.skip`, a test removed, a test added |
| AC4 | `test_js_stage.py`: a refactor is VERIFIED; the API, timing and network items are on its card |
| AC5 | The golden cards and the replay tests, unchanged for Python logs without a language |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

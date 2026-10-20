# K06 — JavaScript: the test → function map

| | |
|---|---|
| **Stage** | K — Expansion |
| **Status** | in progress |
| **Depends on** | K01 |
| **Branch / PR** | `phase/K06-js-test-map` · PR pending |
| **Started / finished** | 2026-10-20 / — |

## Objective
ADR-0017's phase 2, accepted by the owner on 2026-10-19: which functions each JavaScript or
TypeScript test runs. That is the map selection needs (D06), with D06's rule: a changed
function selects the tests that ran it.

## Scope
- **The setup files** (`sandbox/_hook/repro_map_vitest.mjs`, `repro_map_jest.cjs`).
  - **How they record:** V8's precise coverage, started through the inspector in the test's
    isolate and taken before and after each test. The functions with a count above zero are
    what the test ran. The first take in a test file is what importing it ran.
  - **What they write:** one JSON line per test and per test file, functions as
    `[path relative to the project, name]`. Nothing under `node_modules` or outside the
    project is written.
  - **Failure is harmless:** an error is written down, and no test fails because of it.
- **Added, not substituted.**
  - **Vitest:** a wrapper config (`repro.vitest.config.mts`) imports the project's own config,
    in Vitest's order (`vitest.config.*`, then `vite.config.*`, a function config included). It
    appends the setup file to the project's own `setupFiles`.
  - **Jest:** the project's `setupFilesAfterEnv` are read with `--showConfig` and passed first.
    A config of several projects is not mapped yet, and the summary says so: one list for all
    of them would change what some of them run.
- **The change** (`repro.jsmap.changed`).
  - **Attribution:** each changed line, on either side, goes to the innermost named function
    around it. The scanner reads declarations, functions assigned to a name, object and class
    methods, and accessors under V8's names (`get x`). It ignores braces in comments, strings
    and parameters.
  - **Module-level changes:** a line in no named function is one. So are a constructor (V8
    names it after its class), an added file and a deleted file.
- **The rule** (`repro.jsmap.select`).
  - A changed function selects the tests that ran it, on base or on head.
  - A module-level change selects every test that ran code of that file, and every test in a
    test file that loaded it.
  - A changed test file selects its own tests.
  - Functions are known by name in their file, because V8 reports offsets in the code the
    runner executes, which Vite and Babel have rewritten. Same-named functions in one file are
    therefore not told apart: that selects more tests, never fewer, and the summary says so.
- **`repro js-run`** reports the changed functions (`changes`) and each selected test with its
  reasons (`selected`). Its suite still runs whole, so the outcome comparison stays complete.

## Out of scope
- ADR-0017's phases 3 and 4: traces of the selected tests (K07), and the card (K08).
- Jest configs of several projects; Vitest workspaces of several projects.

## Acceptance criteria
- [x] AC1: per-test function maps for Vitest and Jest, the project's own setup kept.
- [x] AC2: a changed function selects exactly the tests that ran it; a module-level change, the
  tests that loaded its file.
- [x] AC3: nothing is lost silently: a side without a map says why, and the name-only rule is
  stated.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_jsmap.py`: the map read (and refused when malformed); Jest's own setup files kept and a multi-project config refused; Vitest's wrapper importing Vitest's own config before Vite's |
| AC2 | `test_jsmap.py`: the scanner on declarations, destructured parameters, braces in comments and strings, a constructor, an accessor, TypeScript annotations, expression and block arrows, an anonymous callback; the rule on a function, a module-level change, a changed test file; and two real runs with the monorepo's Vitest 5.0.4 |
| AC3 | `test_jsts.py` (K01's tests, with the map now on) and the summary's `missing` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.jsmap`; the two setup files; `repro.jsts` runs each side with the map and reports the
  selection.
- Tests: `test_jsmap.py` (14, two of them real Vitest runs).

## Evidence
- **Real runs, Vitest 5.0.4** (`test_jsmap.py`), on a tiny repository with tests "m adds" and
  "m twice":
  - head changes `twice`: exactly "m twice" is selected, as "ran twice in src/m.js";
  - head changes a module-level constant: both tests are selected, their file having loaded it.
- **Jest 30.5.2, checked by hand.** Jest is not in the monorepo, so CI cannot run it. In a
  scratch project, `--showConfig` gave the project's own `setupFilesAfterEnv`, and both ran:
  - the project's setup file wrote its line;
  - `read_map` read "m adds" → `add` and "m twice" → `add`, `twice`;
  - the import-time list held `src/m.js`.

  The callback form of the inspector's `post` starts coverage before the test file is
  imported, as the Vitest file's top-level `await` does.
- CI run: linked in the PR.

## Deviations from spec
- The ADR spoke of "functions by file and range"; they are by file and name. V8's ranges are
  in the rewritten code: measured on Vitest, `add` at offset 0 in the source is at 507 in what
  V8 ran.

## Known gaps
- Same-named functions in one file are one function to the rule (more tests, never fewer).
- Code run at import is attributed to the test file, not to a test. With Vitest's
  `isolate: false`, a module imported once is not seen again by later files.
- Multi-project Jest configs and Vitest workspaces are not mapped.

## Dependencies added
None. The setup files use Node's own `inspector`, `fs`, `path` and `url`.

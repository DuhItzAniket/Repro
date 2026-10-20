# K07 — JavaScript: function-level traces

| | |
|---|---|
| **Stage** | K — Expansion |
| **Status** | in progress |
| **Depends on** | K06 |
| **Branch / PR** | `phase/K07-js-traces` · PR pending |
| **Started / finished** | 2026-10-20 / — |

## Objective
ADR-0017's phase 3, accepted by the owner on 2026-10-19. It records the calls of the functions
a JavaScript or TypeScript change edits, and compares them base against head as E03 compares
Python's. The aim is to show a behaviour change that no test catches.

## Scope
- **The runtime** (`sandbox/_hook/repro_trace_js.cjs`).
  - **The encoder:** `repro_encode`'s rules, ported. No user code runs: a value is read through
    property descriptors, a getter is written as one rather than called, and neither
    `toString`, `valueOf`, `toJSON` nor a proxy's traps run. The guards are the same: depth 6,
    5,000 values, cycles. Strings are normalised: the project's root, the temporary and home
    directories. Objects and Maps also get an order-insensitive digest.
  - **The wrapper** records each call in the current test as Python's tracer does (the same
    JSON records):
    - a promise is recorded when it settles;
    - construction passes through untraced;
    - each (test, function) records 200 calls, then a "truncated" record;
    - the first 20 calls carry previews.
- **Wrapping, at each runner's own transform point.** ADR-0017's Node `load` hook would see
  neither runner's modules: Vitest evaluates what Vite transformed, and Jest evaluates modules
  in its own `vm` contexts. The ADR now records this.
  - **Vitest:** a Vite plugin (`repro_trace_vite.mjs`), last of the transforms and added by
    K06's wrapper config, wraps the changed functions in place. It covers top-level function
    declarations, `const`/`let` functions (`const` made `let`, padded so no offset moves), and
    class methods and accessors by V8's names. Calls from inside the module are traced.
  - **Jest:** the setup file mocks each changed module by its own exports, wrapped, with
    exported classes' methods in place. Only calls through the exports are traced.
- **The comparison is E03's, unchanged.**
  - The runs: base (A), base again shuffled the same way each time (A2: Vitest's
    `--sequence.shuffle`, Jest's `--randomize`, seed 1), then head (H).
  - The trace records are read as Python's (`runner.pytest.read_results`) and compared
    (`observations.compare`). Calls whose arguments cannot be encoded are matched by position
    (#97).
  - Differences are E04's (`behaviour.differences`), shown with their sampled values.
- **`repro js-run`** reports `behaviour`: the counts, and each difference with its function,
  test, kind, stability and summary.

## Out of scope
- The card, the schema's language field and the TypeScript compiler API: K08.
- A reproducer run: the sampled previews stand in for one.
- Nested functions and object literal methods; Jest's calls from inside a module.

## Acceptance criteria
- [x] AC1: the changed functions' calls are recorded in Vitest and Jest, by an encoder that runs
  no user code.
- [x] AC2: a behaviour change no test catches is a stable difference, with values.
- [x] AC3: noise (a result that differs between two runs of base) is masked, not a difference.
- [x] AC4: what is not traced is said.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_jstrace.py`: the runtime's guarantees under Node (`data/js/encoder_checks.cjs`); class methods, an accessor and a `const` arrow traced, for real |
| AC2 | `test_jstrace.py`: `label()` rounds differently, every test passes, the difference is stable with "head "n=2", base "n=2.0""; a change to `add()` seen through `twice()`; `test_jsts.py`'s K01 run sees `add`'s result change |
| AC3 | `test_jstrace.py`: a function returning `Math.random()` is unstable, not a difference |
| AC4 | The summary's `missing`: what is traced, and Jest's exports-only limit |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.jstrace`; `sandbox/_hook/repro_trace_js.cjs` and `repro_trace_vite.mjs`.
- Tracing in the K06 setup files; `repro.jsts` runs A, A2 and H.
- Tests: `test_jstrace.py` (5, three of them real Vitest runs) and `data/js/encoder_checks.cjs`.

## Evidence
- **Real Vitest 5.0.4 runs** (`test_jstrace.py`):
  - the silent change gives `label(2) gives another result: head "n=2", base "n=2.0"`, stable;
  - `add()`'s change is seen in the test that only calls `twice()`;
  - the random draw is counted unstable, with no difference;
  - the getter, the method and the `const` arrow all show their changes.
- **The runtime's guarantees, under Node.** The same value gives the same digest, and `-0` is
  not `0`. Order is kept, and the sorted digest ignores it. A cycle is incomplete. No getter
  and no proxy trap ran. A typed-array view is read by its own bytes. Construction passes
  through. A raise and a settled promise are recorded.
- **Jest 30.5.2, checked by hand,** in a scratch project with `--randomize --seed=1`:
  - "m adds" recorded `add(1, 2) -> 3` and "m twice" recorded `twice(2) -> 4`;
  - the call to `add` inside `twice` was not traced, as stated;
  - no setup error was written.
- CI run: linked in the PR.

## Deviations from spec
- No Node `load` hook: each runner's transform point. ADR-0017 records why.
- SHA-256 cut to 128 bits, not BLAKE2b-128: JavaScript digests are only compared with each other.

## Known gaps
- Jest: calls through a module's exports only.
- Nested functions and object literal methods are not traced. Neither is a function whose name
  the scanner does not see; it counts as module-level, and selects tests instead.
- No reproducer run: a difference past the first 20 calls of its function in a test shows no
  values.

## Dependencies added
None. Node's own `crypto`, `fs`, `os`, `util`, `module` and `inspector`.

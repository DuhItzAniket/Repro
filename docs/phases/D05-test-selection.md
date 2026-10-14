# D05 — Test selection via per-test function map

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | done |
| **Depends on** | D04, C07 |
| **Branch / PR** | `phase/D05-test-selection` · [#42](https://github.com/DuhItzAniket/Repro/pull/42) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Run only the tests a change can affect, and say which changed code no test runs. Selection
comes from what each test actually ran on base (a function-level map), the import graphs for
module-level changes, and the tests the change itself adds or edits.

## Scope
- **Collect-map mode** in Repro's pytest plugin (`REPRO_MAP=1`): `sys.monitoring` PY_START,
  recorded once per function and test and then disabled at that place until the next test
  restarts events. A function is recorded as a *place*: its file relative to the snapshot, its
  code object's qualified name and first line. Code outside the snapshot is not recorded.
  Every run also lists the tests collected and where each test's own function is.
- **`repro.runner.selection`**:
  - `Resolver`: places to C06 symbols (`module:qualname#ordinal`), from the side's source;
    code with no symbol of its own (lambdas, comprehensions, annotation scopes) belongs to the
    nearest enclosing symbol, and a repeated name is told apart by line.
  - `test_map`: a run's tests and maps as symbols.
  - `select`: the rule of ARCHITECTURE §4.1, each test with its reasons (`blast_radius`,
    `module_import`, `new_test`, `modified_test`) and the symbols behind them; the
    `test.selected` payload.
  - `uncovered` and `no_covering_test`: the changed symbols no selected test runs, on base
    (the map) or head (the selected tests' map), as `missing.recorded` items.
  - `MapCache` and `map_key`: base maps cached by commit, lock digest, interpreter, platform and
    map format.
- `run_tests(map_tests=..., collect_only=...)`; `analysis.blast.downstream` (shared with the
  blast radius).
- Fixtures `selection` and `untested` (TEST_STRATEGY §3), with their expectations.

## Out of scope
- Running both sides and comparing outcomes, reruns, the DeFlaker check (D06); emitting
  `test.selected` from the pipeline (D06 brings the run stage into it); the tracer (Stage E).

## Design notes
- **Selection is decided by what ran, coverage by both sides.** A test is selected for a changed
  function or method if it ran it on base. Whether a changed symbol is covered is asked on both
  sides, because an added function exists only on head: the selected tests run mapped on head
  too, and a symbol run by a selected test on either side is covered.
- **Module-level code runs at import.** Imports happen while pytest collects, before any test, so
  no per-test map can see them. A module whose own code changed selects the tests whose modules
  import it, directly or not, over both sides' import graphs (C07); it is covered when one does.
  A class's own code (its body) runs at import too: it is covered when a selected test ran one of
  its methods. A changed `conftest.py` selects the tests below it, since pytest imports it for
  them.
- **Test code is not asked to be covered.** Changes in test modules (the modules tests are
  collected from) and `conftest.py` select tests (`new_test`, `modified_test`, `module_import`)
  but are never `no_covering_test` items.
- **Equal code objects are not the same function.** CPython compares and hashes code objects by
  content without their file: two identical functions in two files are equal (measured on 3.12.13,
  3.13.13, 3.14.4 and 3.15.0). The plugin keys code objects by identity and holds them, so the
  identity cannot be reused.
- **Tool IDs.** Repro takes 4, 3, 2 or 5, the first free, leaving 0 (debuggers) and 1 (coverage)
  to their owners (research/03 §1.4); if none is free the run reports the map unavailable and the
  tests still run.
- **Paths, not modules, cross the sandbox.** Places are relative to the snapshot, so a container's
  map names the same symbols as the host's (tested).

## Acceptance criteria
- [x] AC1 (roadmap): on fixtures, selected tests ⊇ the tests a human expects.
- [x] AC2 (roadmap): uncovered changed symbols are always listed.
- [x] AC3: each selected test carries its reasons and symbols; the payloads validate against
  the event schema.
- [x] AC4: the map is the same on the host and in a container, does not change outcomes, and is
  reported unavailable when no tool ID is free.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_selection_fixtures.py`: `selection` and `untested` select exactly the tests their expectation files name (stronger than ⊇: `test_empty_total`, which runs no changed function, must not be selected); `honest-fix` selects both tests of the fixed function |
| AC2 | the same, against each expectation's `uncovered` list; `test_selection.py::test_coverage_gaps` (removed, added, class and module-level symbols, test code) |
| AC3 | `test_selection.py` (reasons, symbols, renamed symbols by their base name, conftest, new parameters, models) |
| AC4 | `test_the_map_is_the_same_in_a_container`, `test_honest_fix_…` (outcomes with and without the map), `test_no_free_tool_id_is_reported` |

---
*Filled in at the end of the phase:*

## What shipped
- Plugin: collect-map mode, `collected` records. `repro.runner.selection`. `run_tests` options.
  `analysis.blast.downstream`.
- Fixtures `selection` and `untested` (`engine/tests/fixtures/`).
- Tests: `test_selection.py` (20), `test_selection_fixtures.py` (7), and the expectation-file
  check for the two new fixtures. pytest 990 → 1019 (1017 pass and 2 skip on Windows with Docker
  Desktop).

## Evidence
- Windows: the fixtures select exactly the expected tests; the `selection` base map is identical
  in Repro's image at L3 (Docker Desktop).
- CI run: linked in the PR (#42).

## Deviations from spec
- `test.selected` and `no_covering_test` are produced and schema-checked, but the pipeline emits
  them from D06, when the run stage joins it.

## Known gaps
- A module- or session-scoped fixture runs in the first test that uses it, so its functions are
  in that test's map only.
- Code run in another process (a subprocess, a multiprocessing worker) is not mapped.
- A map comes from the target's own process: forged records could hide a coverage gap or drop a
  test (THREAT_MODEL T11).
- The map's overhead is not measured yet; the tracer benchmark of E01 measures both.

## Dependencies added
None.

## Research notes
- `sys.monitoring` (added in 3.12): `use_tool_id` raises `ValueError` if the ID is in use;
  returning `DISABLE` from a local event's callback disables it at that code location only;
  `restart_events()` enables all events disabled that way, for all tools; predefined IDs
  `DEBUGGER_ID=0`, `COVERAGE_ID=1`, `PROFILER_ID=2`, `OPTIMIZER_ID=5`; PY_START's callback is
  `func(code, instruction_offset)`. https://docs.python.org/3/library/sys.monitoring.html
  **[V]** 2026-10-15
- Measured here: identical functions compiled from two file names give code objects that compare
  equal and hash equal, on CPython 3.12.13, 3.13.13, 3.14.4 and 3.15.0.

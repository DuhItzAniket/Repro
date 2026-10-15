# E03 — Observation store & stability analysis

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | E02 |
| **Branch / PR** | `phase/E03-observation-store` · [#48](https://github.com/DuhItzAniket/Repro/pull/48) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Trace a change's functions in the runs Repro already makes (A, A2, H), join their calls across
runs by what they were called with, and tell the change apart from the noise: whatever differs
between two runs of the same base code (A and A2) is masked, so that time, randomness and hash
order never become a behaviour difference. Store the observations as replayable artifacts.

## Scope
- **Tracing in the pipeline.** A trace plan (`repro.runner.trace.plan`): the changed functions
  that exist on both sides (modified, renamed, moved), as targets on each side, filed under the
  change's symbol ID. A and A2 trace base's, H head's. A2 now also seeds `random` differently
  (`REPRO_SEED=1`, beside `PYTHONHASHSEED=1` and the reverse order).
- **The trace's own file.** Call records go to `calls.jsonl`, capped at 64 MiB by the plugin
  (`trace_cut` then says so), so a large trace never crowds the test results out of
  `results.jsonl`'s limit; the reader caps it too.
- **Observations** (`repro.runner.observations`): each call keyed by
  `(test, phase, symbol, arguments' digest, occurrence)`; calls with incompletely encoded
  arguments have no key.
- **Stability**: per call, the fields (`outcome`, `type`, `value`, `order`, `yields`) that
  differ between A and A2; per (test, phase, symbol), whether the set of calls differs.
- **Comparison**: A against H for the tests both reported, unstable fields masked, incomplete
  ones not compared, each call `stable`, `unstable` or `n/a` (A2 did not report its test).
- **Artifacts**: deterministic CBOR (`repro.store.cbor`, RFC 8949 §4.2.1): `obs/A.cbor`,
  `obs/A2.cbor`, `obs/H.cbor` and `obs/behaviour.cbor` (the comparison, citing the three by
  path and SHA-256), through the run's artifact store.
- **Missing items**: `unstable_observation` (masked noise, per function, with its tests),
  `encoding_failed` (what could not be compared), `trace_truncated` (spent budgets, cut traces),
  `trace_unavailable` (more changed functions than one run can trace).
- **The `behaviour` job** (diff stage) ties it together; test code (modules tests are collected
  from, `conftest.py`) is left out, as `selection.uncovered` leaves it.
- **Fixture `noisy`**: functions returning the time, a random draw and a set's order, and one
  called with the time, each rewritten by head without changing behaviour, beside a stable one.

## Out of scope
- Classifying differences (result, exception, input mutation, order-only), evidence,
  reproducers and `diff.behaviour` events (E04); previews of values (E04/E07); probes (E06).

## Design notes
- **Join by arguments, then occurrence.** The same test calling the same function with the
  same arguments is the same observation on both sides, whatever else ran in between; a second
  call with the same arguments is occurrence 1. A call's position (`index`) is kept but not
  part of the key, so an extra call elsewhere does not shift every later one.
- **Two levels of noise.** A field that differs between A and A2 is masked for that call
  only, so noise in one function does not hide a change in another. A call set that differs
  (arguments drawn from the clock or a random source) masks the calls that appear on one side
  only, and every field of the calls A2 did not make: nothing shows those stable.
- **A2 differs in everything the sandbox fixes.** Test order (reverse), `PYTHONHASHSEED` and
  now `random`'s seed: the plugin seeds `random` per test from `REPRO_SEED`, so without a
  second seed random draws would agree between A and A2 and never be found noisy.
- **Value and order apart.** `value` compares the result's order-insensitive digest (E02),
  `order` the digest as it was: a result whose dictionaries only changed order differs in
  `order` alone, which E04 calls `order_only`; order noise does not mask a change of content.
- **Never a difference from what could not be seen.** An incomplete encoding, an `unfinished`
  call (cut off by its budget) or a spent budget makes the field or call `unknown`, listed
  under `encoding_failed` / `trace_truncated`, never compared.
- **Deterministic CBOR, our own subset.** Under 200 lines of standard-library code instead of
  a new dependency: definite lengths, shortest arguments and floats, keys sorted by their
  encodings. The decoder accepts only that form (it re-encodes and compares), so a stored
  artifact is either exactly what Repro wrote or refused. Digests are stored as 16 bytes.
- **Test code is traced, then left out.** Which modules hold tests is known only once they are
  collected, after the plan is made; tracing a test function costs one call per test.

## Acceptance criteria
- [x] AC1 (roadmap): on fixtures with time, random and set-order noise, all noise is classified
  `unstable` and none of it becomes a diff.
- [x] AC2: observations are stored as CBOR artifacts and read back unchanged; the comparison
  cites them by digest.
- [x] AC3: the existing fixtures keep their evidence; what tracing adds to them is explicit.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_noise_is_unstable_and_never_a_difference` (the `noisy` fixture through `reproduce`); `test_a_run_reproduces_the_fixture[noisy]` (through `repro run`); unit tests of masking, call sets, `n/a`, order alone, unknown fields |
| AC2 | `test_cbor.py` (RFC 8949 Appendix A, refusals, Hypothesis round trip); `test_observations_round_trip_as_deterministic_cbor`; `assert_observations_stored` in `test_run_stage.py` |
| AC3 | `test_twosided.py` and `test_run_stage.py` over every fixture, with `behaviour` expectations in the fixtures' TOML files |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.store.cbor`: deterministic CBOR encoder and strict decoder.
- `repro.runner.observations`: `observe`, `stability`, `compare`, `behaviour_of`, `missing`,
  `dump_observations` / `load_observations`, `dump_behaviour`.
- `repro.runner.trace`: `TracePlan`, `plan`, `without_test_code`.
- `reproduce(trace=...)`: A and A2 trace base, H head; A2 with `seed=OTHER_SEED`.
- The plugin's `calls.jsonl` with `MAX_TRACE_BYTES` and `trace_cut`; `read_results(calls=...)`,
  `PytestRun.trace_cut`.
- The `behaviour` job; `pipeline_jobs(artifacts=...)`; `repro run` stores the observations.
- Fixture `noisy`; `behaviour` lists in `flaky.toml` and `perf-regress.toml`.
- Tests: `test_cbor.py` (79), `test_observations.py` (21), the `noisy` fixture in
  `test_twosided.py` and `test_run_stage.py` (with the stored artifacts checked). pytest
  1121 → 1224 (1212 pass and 12 skip on Windows with Docker Desktop stopped).

## Evidence
What the comparison found on every fixture (A against H, A2's noise masked), Windows, Python
3.13:

| Fixture | Calls compared | Same | Unstable | Not comparable | Differences | Missing items added |
|---|---|---|---|---|---|---|
| `noisy` | 6 | 1 (`total`) | 5 (`fruit`, `roll`, `stamp`, `since` ×2) | 0 | 0 | `unstable_observation` ×4 |
| `flaky` | 2 | 0 | 2 (`record` counts what it saw) | 0 | 0 | `unstable_observation` ×1 |
| `perf-regress` | 2 | 2 | 0 | 0 | 0 | `encoding_failed` (50,000-tag arguments, past the node guard) |
| `honest-fix` | 2 | 0 | 0 | 0 | 2 (`parse_date`, the fix) | none |
| `selection` | 6 | 4 | 0 | 0 | 2 | none |
| `breaks-one` | 1 | 0 | 0 | 0 | 1 (`discount`) | none |
| `test-tamper` | 4 | 0 | 0 | 0 | 4 (`divide`, `percent`) | none |
| `untested` | no selected test reaches `summary`, so A2 and H do not run: nothing compared (its `no_covering_test` item says so) | | | | | |

- AC1: every call carrying time, a random draw or a set's order is `unstable`, and the four
  functions are listed; the one stable function compares equal; no difference. The `random`
  seed matters: run again with A2 on the plugin's seed 0, `roll` agreed between A and A2 (the
  plugin seeds `random` per test) and came out `stable`.
- The differences the other fixtures show are the changes themselves; E04 turns them into
  evidence. Before test code was left out, `test-tamper`'s edited test functions showed up as
  differences of their own.
- AC2: every RFC 8949 Appendix A example in the subset encodes and decodes exactly (52);
  non-deterministic forms, tags, indefinite lengths, duplicate keys and trailing bytes are
  refused (16 cases); generated values round-trip to the same bytes. Through `repro run`, the
  `noisy` run stored `obs/A.cbor`, `obs/A2.cbor`, `obs/H.cbor` and `obs/behaviour.cbor`, each
  read back and matching the digest the comparison cites.
- Overhead after the trace file moved (commit `1e9237b`, 3.13.13, 8 rounds): `fib(28)` 1.11×
  (1.03–1.19), records 1.18× (1.11–1.26), small calls 1.10× (1.02–1.21);
  `docs/perf/E01-tracer-bench.jsonl`.
- CI run: linked in the PR (#48).

## Deviations from spec
- ROADMAP E03 names "CBOR artifacts plus index": the index is `obs/behaviour.cbor` (every key,
  where it was seen, its stability and what differs, citing the observation artifacts by
  digest), not a separate database table; the `artifacts` table already indexes the files.
- ARCHITECTURE §4.3 masks "fields"; E03 also masks whole call sets (inputs that differ
  between A and A2), which the noise in arguments needs.
- A2's `random` seed differs from A's now (D06 changed only the order and the hash seed); this
  can mark more tests flaky, which is what A2 is for.

## Known gaps
- Calls past a test's budget (200) are not compared; nor are calls with arguments too large or
  deep to encode completely (both listed).
- Noise that A2 does not vary (a value fixed per machine, a file the tests write) is not
  detected as noise.
- The comparison lists differences but does not classify them, attach reproducers or emit
  events: E04.

## Dependencies added
None.

## Research notes
- RFC 8949 (CBOR), §4.2.1 core deterministic encoding requirements and Appendix A's examples,
  https://www.rfc-editor.org/rfc/rfc8949.html **[V]** 2026-10-15. `application/cbor` is the
  media type RFC 8949 §9.3 registers.
- Diffy's noise floor (research/01 §2.2), applied per call and field (ARCHITECTURE §4.3).

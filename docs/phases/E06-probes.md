# E06 — Deterministic input-replay probes

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | E04 |
| **Branch / PR** | `phase/E06-probes` · [#51](https://github.com/DuhItzAniket/Repro/pull/51) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Find what a change does on inputs its tests never use: call the changed functions with
generated inputs on both sides, the same inputs every run, and report the ones that behave
differently, with the input as the reproducer.

## Scope
- **Candidates** (`repro.runner.probes.candidates`): module-level functions the change
  modified, renamed or moved, with the same parameters on both sides, every one annotated with
  a JSON type (`int`, `float`, `str`, `bool`, `None`, `list[T]`, `dict[str, T]`, `Optional`,
  unions), no `*args` / `**kwargs`, not a generator; read with `ast`. At most 20 a run.
- **Inputs** (`inputs`): Hypothesis on the host, `derandomize=True`, no database, the generate
  phase only; integers within 32 bits, finite floats, short text and collections; 40 distinct
  inputs a function.
- **Runner** (`sandbox/_hook/repro_probe.py`): in the side's sandbox, with its interpreter,
  beside the plugin; one JSON line per call (outcome, digests, type, preview), flushed as it
  ends; `random` seeded per call from `REPRO_SEED`; the plugin's network guard.
- **Three runs**: base, base again with another hash seed and `random` seed (A′), head. Inputs
  on which A and A′ differ are left out (`unstable_observation`); base against head is classed
  as in E04 and grouped per function and class.
- **Evidence**: `probe_diff` with `provenance: generated` (the first differing input as the
  reproducer, inputs tried and differing, Hypothesis's version) and a `diff.probe` check
  (`warn`); the probes and results stored as `obs/probes.cbor`.
- **Jobs** `probes` (run) and `probe-diff` (diff); `perf` now waits for `behaviour` and
  `probes`, so their runs do not load its timing.
- **Fixture** `probe-only`.
- **Dependency**: Hypothesis becomes a runtime dependency of the engine.

## Out of scope
- Probes written by an agent from the code and the tests (G07); CrossHair (K04); methods,
  classes and non-JSON parameters.

## Design notes
- **Generated on the host, run in the sandbox.** Hypothesis builds data from annotations
  parsed with `ast`; the target's code runs only inside the sandbox, from a JSON file of those
  inputs. Nothing generated is executed on the host.
- **The same inputs every run.** `derandomize=True` derives Hypothesis's seed from the
  generating function, which is Repro's own and the same for every target; the strategy comes
  from the annotations. The evidence names the Hypothesis version, since another version may
  generate other inputs, and `obs/probes.cbor` keeps the inputs themselves.
- **Determinism is measured, not assumed.** A probe counts only if base gives the same result
  under two hash seeds and two `random` seeds; others are listed, not compared.
- **Every call is flushed.** A generated input can make a function loop: the run's timeout
  (300 s) ends it, the calls before stay, and the cut is a `timeout` item.
- **Timing alone.** Perf now runs after the jobs that run the sides (E04's reproducers, the
  probes): measured beside them, its samples would carry their load.

## Acceptance criteria
- [x] AC1 (roadmap): finds the seeded divergence in a fixture whose existing tests don't
  exercise it.
- [x] AC2 (roadmap): probes are deterministic across A and A′.
- [x] AC3: the probe differences are schema-valid evidence with `warn` checks through
  `repro run`; the other fixtures gain none.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_probe_only_fixture`; `test_a_run_reproduces_the_fixture[probe-only]` |
| AC2 | the same inputs from two generations (`test_inputs_are_the_same_every_time_and_distinct`); no unstable input on `probe-only`; unstable inputs left out (`test_inputs_that_differ_between_a_and_a2_are_left_out`) |
| AC3 | `test_run_stage.py` over every fixture; schema validation in `test_probes.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.runner.probes`: `candidates`, `inputs`, `run_probes`, `compare`, `probe`,
  `ProbeDiff` (evidence, `diff.probe` payload), `Probing` (missing items, the stored document).
- `sandbox/_hook/repro_probe.py`, the probe runner; mypy told about the hook's plugin module.
- The `probes` and `probe-diff` jobs; `perf` waits for `behaviour` and `probes`.
- Fixture `probe-only`; `test_run_stage.py` names `probe_diff` evidence.
- Tests: `test_probes.py` (26), `probe-only` in `test_twosided.py` and `test_run_stage.py`.
  pytest 1266 → 1295 (1283 pass and 12 skip on Windows with Docker Desktop stopped).

## Evidence
- AC1: on `probe-only`, `percent(part: int, whole: int)` is the one candidate; of its 40
  generated inputs, 7 return `0.0` on base and raise on head, the first being
  `percent(part=0, whole=0)` (base `0.0`, head `raises builtins.ZeroDivisionError('division by
  zero')`): `probe_diff` `exception_added`, through `repro run` too, while the only test
  (`percent(1, 4)`) passes on both sides and gives no behaviour difference.
- AC2: generating the inputs twice gives the same 40; on `probe-only` the two base runs (hash
  and `random` seeds 0 and 1) agree on all 40 (none left out); inputs on which they disagree
  are left out and listed (unit test).
- AC3: the other fixtures' functions probed are `parse_date` (`honest-fix`) and `shout`
  (`api-break`); neither gives a difference, and their expectations are unchanged.
- CI run: linked in the PR (#51).

## Deviations from spec
- ARCHITECTURE §4.4 has `diff.probe` evidence "reported separately"; it is its own evidence type
  and check kind, which the card can tell apart by `provenance`.
- Timing (D07) now runs after `behaviour` and `probes` rather than beside them.

## Known gaps
- Generated text rarely forms structured values: `parse_date`'s fix (`honest-fix`) changes its
  result only for valid ISO timestamps, which 40 short random strings did not include (the
  behaviour comparison of the tests' own calls shows that change).
- Methods, classes, keyword-only defaults that are not JSON, and parameters without
  annotations are not probed.
- A probe that hangs ends its whole side's run at the 300 s limit (a `timeout` item); the calls
  before it are kept.
- Another Hypothesis version may generate other inputs; the evidence records the version and
  `obs/probes.cbor` the inputs.

## Dependencies added
- Hypothesis (MPL-2.0) moves from the development group to the engine's dependencies
  (≥ 6.169.0; 6.169.0 locked), with `sortedcontainers` (Apache-2.0) it requires.
  https://pypi.org/project/hypothesis/ **[V]** 2026-10-15 (PyPI JSON API: 6.169.3 latest,
  Requires-Python ≥ 3.11).

## Research notes
- ARCHITECTURE §4.4: input replay for annotated pure functions as the deterministic
  alternative to agent-written probes; PatchDiff, Testora and BERT needed generated tests to
  expose differences (research/02 §3.3, §3.7).

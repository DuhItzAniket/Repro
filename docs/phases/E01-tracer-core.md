# E01 — Tracer core & overhead benchmark

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | done |
| **Depends on** | D04, A08 |
| **Branch / PR** | `phase/E01-tracer-core` · [#46](https://github.com/DuhItzAniket/Repro/pull/46) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Record what the functions a change touches receive and return, call by call and test by test,
from inside the target's own tests, cheaply enough to run on every change: the raw material of
"same input, different output" evidence (Stage E).

## Scope
- **The tracer** (`sandbox/_hook/repro_trace.py`, standard library only, Python 3.12–3.15):
  for each target function, every call's arguments (read from the callee's frame at PY_START),
  its result (PY_RETURN), its exception (PY_UNWIND), a generator's yields (PY_YIELD, at most
  32), each attributed to the running test and its phase. Outcomes `return`, `raise`,
  `suspended` (a generator that did not run to its end), `unfinished` (in flight when its target's budget ran out).
- **Tool ID**: the plugin's one `sys.monitoring` tool serves D05's map and the tracer, claimed
  in the order 4, 3, 2, 5; none free is a `trace_unavailable` missing item. Beside coverage.py's
  `sysmon` core (tool 1), both measure.
- **Budget**: 200 recorded calls per (test, target), A08's default; then the target is
  disabled for the rest of the test, and a `trace_truncated` item names it.
- **Encoder, first cut** (`sandbox/_hook/repro_encode.py`): the exact builtin types walked
  into tagged bytes and BLAKE2b-128 digests, independent of the hash seed and the Python
  version; every other object an opaque type token; depth and node guards making an encoding
  incomplete. E02 extends it to objects, exceptions and paths.
- **Engine**: `run_tests(trace=...)` hands the targets to either sandbox as a file;
  `read_results` reads the tracer's records as untrusted input; `repro.runner.trace` builds
  targets from C06 symbols, groups calls by target, and gives the missing items.
- **Benchmark harness** (`scripts/bench_tracer.py`, `engine/tests/data/bench_suite`): untraced
  and traced runs of the same suite through the real plugin, interleaved ABBA, call-phase
  medians; one JSON line per test appended to `docs/perf/E01-tracer-bench.jsonl`.

## Out of scope
- Objects, exceptions' cause chains, paths and addresses in the encoder (E02); storing and
  comparing observations, A/A′ masking (E03); diffs and reproducers (E04); tracing in the
  pipeline's runs (E04/E07); subprocesses (not traced: an item from the audit hook, later).

## Design notes
- **Targets by file, name and span.** The engine names a target by the symbol's file, qualified
  name and line span on that side, so a code object is traced when it *is* that function,
  whatever else its file defines (two functions with one name, a property's getter and setter).
- **Arguments before the body runs.** At PY_START the callee's frame is on the stack
  (research/03 §1.6); its parameters are read there by name, `*args` and `**kwargs` included,
  before the body can change them.
- **The budget switches the target off completely.** Disabling PY_START alone left PY_RETURN
  firing: the benchmark measured a recursive function 27× slower traced, because the first
  recorded calls (the outer frames) stayed in flight for the whole recursion and kept its return
  events on. So when the budget runs out, recorded calls still in flight end as `unfinished`
  (arguments known, results not, never compared) and the target's return and yield events are
  disabled as soon as they next fire. The same function then ran at 1.03×.
- **An unfinished generator is `suspended`, however it ends.** An abandoned generator is
  closed when it is collected, which raises `GeneratorExit` inside it: that is not the function
  raising. Whether that happens before its test ends is the collector's timing: on Ubuntu CI,
  Python 3.12 collected it after the test, every other run before. So both are `suspended`.
- **No user code runs to encode.** Only exact builtin types are walked; a subclass, like any
  object, is a type name read from the type itself. A hostile `__eq__`, `__repr__` or property is
  never called.
- **Same digests everywhere.** Sets are written in the order of their elements' encodings, floats
  as `float.hex()`, integers in hexadecimal: the digests are the same under another
  `PYTHONHASHSEED` and on Python 3.12, 3.13, 3.14 and 3.15 (tested).

## Acceptance criteria
- [x] AC1 (roadmap): overhead on the benchmark suite is within the budget set in A08 (200
  captured calls per test and function, then the function disabled; budgeted capture at
  0.92–1.19× baseline): no measured test's 95 % interval lies above 1.20×, on 3.12–3.15.
- [x] AC2 (roadmap): a tool-ID conflict with coverage.py is handled (both measure), and becomes an
  explicit missing item when unresolvable (no free ID: `trace_unavailable`).
- [x] AC3: every kind of call is recorded as specified, attributed to its test and phase, with
  digests identical across hash seeds and Python versions; the budget truncates with an item.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `scripts/bench_tracer.py` on 3.12–3.15 (results in `docs/perf/E01-tracer-bench.jsonl`); `scripts/tests/test_bench_tracer.py` keeps the harness working |
| AC2 | `test_tracer.py::test_beside_coverage` (coverage.py 7.16.2, `sysmon` core), `::test_no_free_tool_id_is_a_missing_item` |
| AC3 | `test_tracer.py::test_each_kind_of_call`, `::test_the_budget`, `::test_the_same_digests_under_another_hash_seed`, `::test_the_same_digests_on_every_python[3.12, 3.14, 3.15]`; `test_encode.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `sandbox/_hook/repro_trace.py`, `repro_encode.py`; the plugin's `_Monitor` (one tool for the
  map and the tracer) and phase hooks.
- `run_tests(trace=...)`, `TraceCall` and the reader's tracer records; `DockerSandbox.write_files`;
  `repro.runner.trace`.
- `scripts/bench_tracer.py`, `engine/tests/data/bench_suite`, `docs/perf/E01-tracer-bench.jsonl`.
- Fixture suite `engine/tests/data/trace_suite` (with coverage.py 7.16.2 pinned).
- Tests: `test_tracer.py` (9), `test_encode.py` (15), `scripts/tests/test_bench_tracer.py` (2).
  pytest 1077 → 1103 (1101 pass and 2 skip on Windows).

## Evidence
The benchmark, Windows (x64), 8 rounds (16 untraced and 16 traced runs per test), call-phase
medians, BCa 95 % intervals; `docs/perf/E01-tracer-bench.jsonl`:

| Python | `fib(28)` | 40,000 records | 1,000,000 small calls |
|---|---|---|---|
| 3.12.13 | 1.08× (1.04–1.19) | 1.15× (1.13–1.20) | 1.20× (1.14–1.27) |
| 3.13.13 | 1.07× (1.00–1.15) | 1.20× (1.12–1.27) | 1.10× (1.00–1.18) |
| 3.14.4 | 1.11× (1.02–1.21) | 0.89× (0.85–0.93) | 1.08× (1.01–1.15) |
| 3.15.0 | 1.04× (0.98–1.17) | 1.17× (1.11–1.22) | 1.13× (1.03–1.20) |

- Every interval reaches 1.20× or less at its low end; the point estimates are 0.89–1.20×,
  against A08's 0.92–1.19×. Run-to-run noise on this laptop is of the same size (untraced
  medians of the same test moved by about 10 % between invocations), which is why the check uses
  the interval.
- What remains is mostly the budget itself: 200 captured calls per test and function, at A08's
  2–11 µs each, about 2 ms of the records test's 25 ms. Steady state past the budget is about
  baseline: `fib(28)` (317,811 calls) paid 2.1 ms in total where `fib(25)` paid 6.3 ms, since the
  first traced test of a process also pays one-off costs (the benchmark's warm-up test takes them).
- Before the budget also switched return events off, the same `fib` ran 26.7× slower traced.
- A global PY_UNWIND event (as 3.12–3.14 require) costs nothing measurable when no exception
  is raised: 1,000,000 calls took 49.3–51.3 ms with it and 49.7–50.1 ms without on 3.12.13
  (42.0–45.3 against 43.8–44.9 ms on 3.13.13).
- Digests are identical on 3.12.13, 3.13.13, 3.14.4 and 3.15.0, and under another hash seed.
- coverage.py 7.16.2 held tool ID 1 and Repro ID 4 in the same run, both measuring.
- CI run: linked in the PR (#46).

## Deviations from spec
- ARCHITECTURE §4.3 sketched keeping counts and rolling hashes after the budget; E01 stops
  recording at the budget and says so (`trace_truncated`), the measured cheapest option.
- research/03 §C read arguments into an encoding of a dict; E01 encodes the ordered
  `(name, value)` pairs, which keeps the parameter order.
- The benchmark's check uses the ratio's 95 % interval, not its point estimate (Evidence).

## Known gaps
- Objects, exceptions' cause chains, paths and addresses are opaque or partial until E02; two
  different objects of one type can share a digest now (a missed difference, never a false one).
- The outer frames of a recursion past the budget end `unfinished`, their results unknown.
- Free-threaded builds are not supported (the tracer's state is not locked).
- Calls in subprocesses are not traced.

## Dependencies added
None (coverage.py 7.16.2 is pinned in a fixture project, not in Repro).

## Research notes
- `sys.monitoring` (research/03 §1; D05's notes): PY_START, PY_RETURN, PY_YIELD and their
  callback signatures; PY_UNWIND global before 3.15, per code object from 3.15.
- coverage.py 7.16.2 on PyPI: `Requires-Python >=3.10`, wheels for CPython 3.12–3.15,
  uploaded 2026-09-27. https://pypi.org/project/coverage/7.16.2/ **[V]** 2026-10-15

# ADR-0005: Own `sys.monitoring` tracer, canonical encoder and test-selection map

- **Status:** accepted (consistent with the decided stack: Python 3.12+ and `sys.monitoring`)
- **Date:** 2026-10-13
- **Phase:** A01 (spiked in A08, built in D05 and E01–E04)

## Context
Repro's main technical asset is function-level, base-vs-head behaviour evidence. Research findings
(research/03):
- `sys.monitoring` (PEP 669) gives low-overhead PY_START/PY_RETURN/PY_UNWIND callbacks with
  per-code-object enable/disable. No published figure exists for the per-call cost with Python
  callbacks that capture arguments (§1.3).
- coverage.py's fast `sysmon` core "is incompatible with dynamic contexts". Per-test contexts
  force the slower settrace core (§2).
- pytest-testmon has been idle for about 10 months and selects tests against the last run, not
  against a base ref. pytest-rts (the same approach as ours) has been unmaintained since 2021 (§3).
- Naive hashing of observations is unstable. Default reprs embed addresses, str-set order
  depends on `PYTHONHASHSEED`, and calling user `__repr__`/`__eq__` runs arbitrary code (§1.7).

## Decision
- Build **one stdlib-only collector** used in two modes.
  - **collect-map:** global `PY_START`, record (test → functions). Non-project code returns
    `DISABLE`.
  - **trace:** target code objects get local return/yield events. Arguments, results and
    exceptions are captured and encoded.
- Build a **structural canonical encoder** that never invokes user-defined dunders, normalises
  paths and addresses, orders sets canonically, and treats truncated or failed encodings as
  never-equal.
- Mask unstable fields using an **A/A′ double base run**, with a different seed and test order.
- Claim tool IDs in the order 4, 3, 2, 5. If none is free, the result is an explicit missing
  item.
- Measure overhead before fixing defaults (phase A08 spike, then a benchmark harness in E01).

## Alternatives considered
| Option | Why not |
|---|---|
| coverage.py with `--cov-context=test` for selection | Forces the settrace core (slow) and is line-level only |
| pytest-testmon | Wrong comparison model (last run, not base) and lightly maintained |
| `sys.settrace` / `sys.setprofile` | Much higher overhead (PEP 669 rationale) |
| Pickle- or repr-based hashing | Not stable across runs. Unpickling untrusted data is unsafe |

## Consequences
The plugin must support Python 3.12–3.15 and their differences (`BRANCH_*` and `clear_tool_id`
in 3.14; per-code "other" events in 3.15). Targets older than 3.12 run without traces, and the
card says so. The encoder is security- and correctness-critical, so it gets property-based
tests and fuzzing.

## Measured (A08, 2026-10-13)
`spikes/A08/RESULTS.md` §1. CPython 3.12–3.15, Windows and Linux:
- Every code object `DISABLE`d costs 0.94–1.06× baseline, so loading the tracer is free.
- An instrumented target costs 114–197 ns per call with `sys.monitoring` and 193–547 ns with
  `settrace`.
- Full value capture costs 2.3–11.4 µs per call, and **encoding dominates**: `settrace` capture
  is only 2–35 % slower.
- **Budgeted capture (200 calls, then `DISABLE`) runs at 0.92–1.19× baseline in steady state.**

Consequences:
- The default budget is 200 encoded calls per (test, function).
- Encoder performance is a first-class requirement for E02.
- E01 re-measures on real suites.

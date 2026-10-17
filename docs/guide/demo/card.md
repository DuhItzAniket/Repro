# Reproduction Card: FLAGGED

**FLAGGED**: the run found a problem.

- Repository: silent-change
- Change: `d929cb8bf517d47b71a05f7bd027d31396d640e3` (d929cb8bf517) to `a22fb680efad4d4f48ebd4a0842cb4780fb9a5ed` (a22fb680efad)

## Why

- 2 diff.behaviour flagged (result_changed) (`gap_flagged`)

## Claims

None.

## Gap

| Evidence | Check | Kind | Summary | Origin | Stability | Result |
|---|---|---|---|---|---|---|
| ev_01M5571VT4R36VXJGZ6QR4Q65V | diff.behaviour | result_changed | to_celsius(fahrenheit=100) gives another result: head 38, base 37.8 (in tests/test_convert.py::test_describe_mentions_celsius) | introduced | stable | flagged |
| ev_01M5571VT50CTDH3TPEJ3JX00M | diff.behaviour | result_changed | to_celsius(fahrenheit=32) gives another result: head 0, base 0.0 (in tests/test_convert.py::test_freezing) | introduced | stable | flagged |

## Invariants

None.

## Missing

| Reason | Targets | Detail | What would resolve it |
|---|---|---|---|
| perf_not_assessable | tests/test_convert.py::test_describe_mentions_celsius, tests/test_convert.py::test_freezing | 2 tests run in under 5 ms on both sides, too fast to time: tests/test_convert.py::test_describe_mentions_celsius, tests/test_convert.py::test_freezing | A benchmark that runs the changed code long enough to time |

## Conditions

| Condition | Value |
|---|---|
| Python | 3.13.11 |
| Platform | Docker 29.8.2 linux, repro-sandbox:28192a01bf63 |
| Isolation | L3 |
| Network | enforced |
| Lock, base | - |
| Lock, head | - |
| Selected tests | 2 |
| Hash seeds (A, A2) | 0, 1 |
| Repro | 0.7.0 |
| Models | - |

## Replay

`repro replay run_01M55713792R1V34MZGZVNKKEG` assembles this card again from its 80 events (log SHA-256 `57b32dc57bd867265344ac0394f7daffdef5ebd4ffab0fde3160445740504b2e`); it was generated at 2026-10-17T15:17:57.704Z.

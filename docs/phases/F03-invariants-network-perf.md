# F03 — Invariants II: network, performance

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | done |
| **Depends on** | F01, D02, D07 |
| **Branch / PR** | `phase/F03-invariants-network-perf` · [#56](https://github.com/DuhItzAniket/Repro/pull/56) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Decide the last two of `repro.yml`'s invariants from the run's own evidence: whether head's
tests attempt the network, and whether a timed test got slower than its budget. Each result
must say how far it can be trusted: a network that the sandbox enforces is not the same as one
it only watches.

## Scope
- **`no_network`**: head's network attempts, as the sandbox detected them in head's test runs
  (D01's audit hook, D04's guard), past this machine. Loopback, unspecified addresses,
  `localhost` and Unix sockets are local (asyncio's self-pipe on Windows is a loopback
  connection). An attempt fails it, citing its `network_attempt` evidence; detections that were
  not all read leave it not evaluated; a pass states the network `enforced` (L3) or
  `detected-only` (L2), and a `detected-only` pass adds a `network_not_enforced` item.
- **`perf_budget`**: D07's comparison of each timed test. A test fails the budget when its 95 %
  interval's low end is past `1 + max_regression` and D07 calls it a regression (significant,
  past this machine's noise floor). An interval past the budget without that is "unclear": not
  evaluated. No timed test, or no timing at all: not evaluated.
- **The `invariants` job** comes after `outcomes` (head's attempts) and `perf-diff` too; the
  sandbox jobs keep each side's network mode, the outcomes job head's attempts, the perf-diff
  job each timed test with its evidence.
- **Fixtures**: `net-call` (head's code under test connects to 192.0.2.1); `perf-regress`
  gains a base `repro.yml` with a 20 % budget; `invariants-pass` gains a test slow enough to
  time, so every invariant passes there.

## Out of scope
- What a failed invariant does to the card's status (F04).
- Network attempts outside head's test runs (probes, timing runs).

## Design notes
- **Attempts, not reachability.** The invariant is "head's tests must not attempt network
  access" (PRODUCT.md). Under L3 an attempt cannot succeed, but it is still made, so it fails
  the invariant on either sandbox; what differs is how much a pass proves.
- **A pass on detection says so.** Detection only sees Python's socket functions; code that
  bypasses them is not seen (ARCHITECTURE §8). That is the `network_not_enforced` reason of
  the missing taxonomy (§6.1).
- **The budget is judged with D07's own rules.** A slowdown past the budget that D07 cannot
  tell from this machine's noise is not a failure, and not a pass either.
- **Fast tests are not judged.** Tests under D07's 5 ms floor have their own
  `perf_not_assessable` items; the result counts them.

## Acceptance criteria
- [x] AC1 (roadmap): each invariant emits `invariant.result` plus evidence.
- [x] AC2 (roadmap): `no_network` distinguishes enforced from detected-only.
- [x] AC3 (roadmap): a passing and a failing fixture per invariant.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_invariants.py` (`test_no_network`, `test_perf_budget`: pass, fail and not-evaluated cases, schema-valid evidence and payloads); `test_run_stage.py` checks each `invariant.result`'s status and its own evidence |
| AC2 | `test_no_network` (details `enforced` / `detected-only`); `test_a_run_reproduces_the_fixture[invariants-pass]` (process sandbox: pass with a `network_not_enforced` item); `test_no_network_rests_on_enforcement_in_containers` (Docker: pass, `enforced`, no such item) |
| AC3 | `[invariants-pass]` (all five pass); `[net-call]` (`no_network` fails); `[perf-regress]` (`perf_budget` fails); `test_what_reaches_past_this_machine` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.policy.invariants`: `no_network`, `Attempt`, `network_not_enforced`, `perf_budget`,
  `Timed`; F02's `not_yet` is gone (every invariant is evaluated).
- `repro.sandbox.detect.leaves_host`.
- `RunState.network`, `head_network`, `head_network_complete`, `perf_timed`,
  `perf_too_fast`; the `invariants` job's `_evaluate`, after `outcomes` and `perf-diff` too.
- Fixture `net-call`; `perf-regress` with a 20 % `perf_budget`; `invariants-pass` with
  `test_best_of_many_rounds`; `policy-weaken` expects `no_network` to pass.
- Tests: `test_what_reaches_past_this_machine` (12), `test_no_network`, `test_perf_budget`,
  `test_a_run_reproduces_the_fixture[net-call]`, `test_each_fixture_gives_exactly_its_evidence[net-call]`,
  `test_no_network_rests_on_enforcement_in_containers` (Docker). pytest 1374 → 1391 (1378
  pass and 13 skip on Windows with Docker Desktop stopped).

## Evidence
Through `repro run` (Windows, process sandbox):

| Fixture | Result |
|---|---|
| `net-call` | `no_network` fail: "head's tests attempted the network: 192.0.2.1:80", citing two `network_attempt` records (the lookup and the connection, both refused by the guard); the test itself passes on both sides |
| `perf-regress` | `perf_budget` fail: "1 tests slower than base past the budget (+20%): tests/test_tags.py::test_unique_tags (x17.26, 95% CI from x16.18)", citing its `perf_diff`; `test_report_is_sorted` (no change) is within it |
| `invariants-pass` | all five pass; `no_network`: "no network attempt detected by head's tests (detected only: the sandbox does not enforce the network)", with a `network_not_enforced` item; `perf_budget`: "1 timed tests within the budget (+50%); 2 too fast to time" |
| `policy-weaken` | `no_network` pass (detected only, with its item) and `forbidden_paths` pass: base's policy, head's removal of `no_network` not applied |

- The containers' case (`no_network` passing with `network: enforced` and no
  `network_not_enforced` item) runs on CI's Ubuntu job, which requires Docker.
- CI run: linked in the PR (#56).

## Deviations from spec
- TEST_STRATEGY's `perf-regress` row already expected a `perf_budget` failure: the fixture
  only now has the `repro.yml` that enables it.

## Known gaps
- Detections come from the target's own processes: under L2, code that bypasses Python's
  socket functions, or tampers with the hook's log, is not seen (the `network_not_enforced`
  item says so). Under L3 the network is absent whatever the code does.
- Only head's test runs are judged; the probes' and timing runs' attempts are not (they run the
  same code, with the same guard).
- A slowdown D07 cannot tell from this machine's noise leaves `perf_budget` not evaluated, so
  budgets under D07's 10 % minimum effect are rarely decided on a laptop.
- What a failed or unevaluated invariant does to the card's status is F04's.

## Dependencies added
None.

## Research notes
- RFC 5737, "IPv4 Address Blocks Reserved for Documentation" (January 2010):
  192.0.2.0/24 is TEST-NET-1, "provided for use in documentation" (§3), and its addresses
  "SHOULD NOT appear on the public Internet" (§4), https://www.rfc-editor.org/rfc/rfc5737.html
  **[V]** 2026-10-15. The `net-call` fixture connects there, so nothing could answer it even
  outside the sandbox.
- PRODUCT.md (`no_network`, `perf_budget`); ARCHITECTURE §6.1, §8; D07's phase record.

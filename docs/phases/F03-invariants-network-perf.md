# F03 — Invariants II: network, performance

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | in progress |
| **Depends on** | F01, D02, D07 |
| **Branch / PR** | `phase/F03-invariants-network-perf` · PR pending |
| **Started / finished** | 2026-10-15 / — |

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
- [ ] AC1 (roadmap): each invariant emits `invariant.result` plus evidence.
- [ ] AC2 (roadmap): `no_network` distinguishes enforced from detected-only.
- [ ] AC3 (roadmap): a passing and a failing fixture per invariant.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_invariants.py` (`test_no_network`, `test_perf_budget`: pass, fail and not-evaluated cases, schema-valid evidence and payloads); `test_run_stage.py` checks each `invariant.result`'s status and its own evidence |
| AC2 | `test_no_network` (details `enforced` / `detected-only`); `test_a_run_reproduces_the_fixture[invariants-pass]` (process sandbox: pass with a `network_not_enforced` item); `test_no_network_rests_on_enforcement_in_containers` (Docker: pass, `enforced`, no such item) |
| AC3 | `[invariants-pass]` (all five pass); `[net-call]` (`no_network` fails); `[perf-regress]` (`perf_budget` fails); `test_what_reaches_past_this_machine` |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- RFC 5737, "IPv4 Address Blocks Reserved for Documentation" (January 2010):
  192.0.2.0/24 is TEST-NET-1, "provided for use in documentation" (§3), and its addresses
  "SHOULD NOT appear on the public Internet" (§4), https://www.rfc-editor.org/rfc/rfc5737.html
  **[V]** 2026-10-15. The `net-call` fixture connects there, so nothing could answer it even
  outside the sandbox.
- PRODUCT.md (`no_network`, `perf_budget`); ARCHITECTURE §6.1, §8; D07's phase record.

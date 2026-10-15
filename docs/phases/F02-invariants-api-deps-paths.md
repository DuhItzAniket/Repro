# F02 — Invariants I: API, dependencies, forbidden paths

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | in progress |
| **Depends on** | F01, E05 |
| **Branch / PR** | `phase/F02-invariants` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Turn three of `repro.yml`'s invariants into results a reviewer can trust: whether a change
breaks the public API, adds a dependency, or touches a forbidden path, each decided from the
run's own evidence and citing it, and "not evaluated" whenever that evidence is missing.

## Scope
- **Rules** (`repro.policy.invariants`): `public_api_stable` (E05's breaks outside `except`,
  dotted object patterns), `no_new_dependencies` (packages added to the lock or the declared
  requirements outside `allow`), `forbidden_paths` (any path the change adds, removes, modifies
  or renames, against `*`, `**`, `?` patterns).
- **Results**: `invariant` evidence (the result, the options, the details and the evidence it
  cites) and an `invariant.result` check whose `evidence_ids` start with it; `ok` / `fail` /
  `warn` (ADR-0015 §2).
- **Not evaluated, never assumed**: the API not compared or a package unread, the
  dependencies not compared, the changed files unknown. `no_network` and `perf_budget` are
  `not_evaluated` until F03.
- **The `invariants` job** (check stage, after `policy`, `api` and `deps`); the `api` and
  `deps` jobs hand their breaks and differences, with their evidence IDs, through `RunState`.
- **Fixtures**: `invariants-pass` (every invariant enabled, a change that keeps them),
  `forbidden-path`; `api-break` and `new-dep` gain a base `repro.yml` enabling the invariant
  they break.

## Out of scope
- `no_network` and `perf_budget` (F03); what a failed invariant does to the card's status
  (F04).

## Design notes
- **One result per declared invariant.** Each is its own evidence, so a verdict (Stage G) can
  cite exactly the invariant it explains, and the result cites the evidence it rests on (the
  `api_diff` and `dep_diff` items).
- **Installed-only additions are not the change's dependencies.** A package that only the
  installed sets show was pulled in by another; the invariant judges what the change declares
  or locks.
- **Patterns are paths, not regular expressions.** `*` stays within a segment, `**` crosses
  them, `?` is one character, everything else is literal (brackets too).

## Acceptance criteria
- [ ] AC1 (roadmap): each invariant emits `invariant.result` plus evidence.
- [ ] AC2 (roadmap): a passing and a failing fixture per invariant.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_invariants.py` (each rule's pass, fail and not-evaluated cases, schema-valid evidence and payloads); `test_run_stage.py` checks every `invariant.result`'s status and that it cites its evidence |
| AC2 | `test_a_run_reproduces_the_fixture[invariants-pass]` (three passes, two not evaluated until F03); `[api-break]`, `[new-dep]`, `[forbidden-path]` (one failure each) |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- PRODUCT.md (the invariants' meaning), ARCHITECTURE §4.6, ADR-0015 §2.

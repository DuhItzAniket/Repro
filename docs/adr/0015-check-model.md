# ADR-0015: The check model — what CHECKS, FLAGGED and the index count

- **Status:** accepted (decided in B01 under the owner's instruction to proceed with Stage B;
  the owner may revisit it at the Stage B gate)
- **Date:** 2026-10-13
- **Phase:** B01 (UI projection in B02 and B09; engine emission in D–F)

## Context
The header shows `CHECKS` and `FLAGGED` counters, and the change×check index has a footer
such as "28 checks / 24 passed / 4 flagged" (DESIGN.md). Both must come from one projection,
so they can never disagree. Until now no document defined what a *check* is in terms of
events. The fixture generator (B01) and the cockpit's projections (B02, B09) need that
definition now. So do the engine stages that will emit these events (D–F).

Two facts constrain the definition:
- Events are append-only (ADR-0002). A result cannot be edited once emitted.
- Whether a difference is acceptable depends on the PR's claims. That is only known after the
  review stage. An intended behaviour change (a fix) and an unintended one look the same at
  diff time.

## Decision
1. **A check is a result-bearing event:** `diff.outcome`, `diff.tests`, `diff.behaviour`,
   `diff.probe`, `diff.api`, `diff.deps`, `diff.perf` or `invariant.result`. Nothing else is
   counted.
2. **The envelope `status` of a check says what it means without claims:**

   | Kind | `ok` | `fail` | `warn` |
   |---|---|---|---|
   | `diff.outcome` | P2P, F2P, new test passing on head | P2F; new test failing on head | F2F, removed, modified, flaky |
   | `diff.tests` | — | removed, skipped, xfailed, weakened or widened tests; base test failing on head | `test_modified` |
   | `diff.behaviour`, `diff.probe` | — | — | every difference |
   | `diff.api`, `diff.deps` | — | — | every difference |
   | `diff.perf` | improvement, no change | — | regression, not assessable |
   | `invariant.result` | pass | fail | not evaluated |

   `fail` is reserved for findings that are problems on their own. `warn` means the result
   needs a claim to explain it, or could not be compared.
3. **Each check resolves to one of three results (the index's cell states):**
   - **unassessed** (hollow) when the payload says it could not be compared: an outcome
     class of flaky, modified, F2F or removed; an unstable behaviour diff; perf not
     assessable; an invariant not evaluated.
   - Otherwise **passed** for `ok` and **flagged** for `fail`.
   - A `warn` check is **pending** until review. It becomes passed if a **supported** verdict
     cites its evidence. It becomes flagged if a contradicted verdict cites it, or if review
     ends without any supported verdict citing it (an unexplained difference). A
     contradiction outweighs support. Review ends at `stage.finished` for `review`, or at the
     card stage or `run.finished` when a run has no review stage (deterministic-only runs).
     *(Precision added in B02.)*
4. `CHECKS` counts all checks. `FLAGGED` counts flagged results. The index footer reads
   `N checks / P passed / F flagged`, followed by `/ U unassessed` and `/ R pending` when those
   are non-zero. One projection computes all of them.

## Alternatives considered
| Option | Why not |
|---|---|
| Count evidence items | Evidence includes invariant records and outcome evidence for every passing test. "Flagged" would still need the same rules |
| Flag every difference at diff time | An intended fix would show as flagged until review, and the counter would have to go down later. Counters that only rise read more honestly |
| A new event kind for "explained by" | The gap reviewer's mapping can be derived from `verdict.issued` citations. Adding a kind changes the schema for no new information |
| Use the card's counts only | The card exists only at the end. The cockpit must show checks resolving live |

## Consequences
- Engine stages D–F must set `status` on result-bearing events as in the table. A test in
  each stage asserts it against the fixtures' expectations.
- `FLAGGED` can rise during review as differences turn out to be unexplained, but it never
  falls. `passed + flagged + unassessed + pending = CHECKS` at every point of a run.
- The index cell counts and the card's `unexplained` count are related but not equal. A
  modified test, for example, is unassessed in the index but an unexplained gap item on the
  card. The drawer explains both.
- The fixture generator's own plan is recounted from events by this rule in
  `packages/synth/src/scenario.test.ts`. B02 adds the real projection and must agree with it.

# F04 — Status engine & missing taxonomy

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | done |
| **Depends on** | F02, F03, E04 |
| **Branch / PR** | `phase/F04-status-engine` · [#57](https://github.com/DuhItzAniket/Repro/pull/57) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
Decide a change's status, `VERIFIED`, `FLAGGED` or `UNVERIFIABLE`, by deterministic rules
over what the run recorded, and say why, citing evidence or targets for every reason. The
status must come from the event log alone, so a replay decides the same.

## Scope
- **Rules** (`repro.policy.status`, ARCHITECTURE §4.6): gap items resolve to pre-existing,
  unassessed, passed, explained or flagged; FLAGGED if any is flagged, a claim is
  contradicted or an invariant failed; else UNVERIFIABLE if anything could not be checked;
  else VERIFIED. `decide` returns the status, its reasons, and (when FLAGGED) what was also
  incomplete.
- **Inputs from the log** (`repro.policy.gap.inputs_from_events`): the gap (each `diff.*` but
  a plain pass, and `policy_change`) with stability and origin, explained-by and
  contradicted-by from `verdict.issued` citations, invariants, claims (when a read stage ran),
  verdicts and rejections, the policy in force, built environments, selected and run tests,
  changed symbols (test code left out) and those a missing item leaves unverified, and stages
  in which a job did not complete.
- **The policy in force as evidence**: `policy` evidence (a new `EvidenceType`, additive) from
  the policy job on every run, so the thresholds are in the log.
- **Origin**: unchanged; every producer already sets it (`introduced` for differences,
  `pre-existing` for F2F, `n/a` otherwise). A pre-existing item never flags.
- **Missing taxonomy**: which reasons leave a changed symbol unverified
  (`no_covering_test`, `unstable_observation`, `encoding_failed`, `trace_unavailable`); a
  `trace_unavailable` item for every function left out of tracing (E03 named only five).
- **Fixtures**: each expectation file's status is asserted through `repro run`; `honest-fix`
  and `selection` carry a `deterministic_status` (FLAGGED), since only Stage G's claims
  explain their differences. `selection`, `untested`, `flaky` and `breaks-one` now run end to
  end in `test_run_stage.py` too.

## Out of scope
- The card itself, its exports and `card.published` (F05); claims and verdicts (Stage G).

## Design notes
- **One rule set, with or without review.** Without a review stage nothing explains a
  difference, so every difference flags (ADR-0015 §3: review ends at the card stage in a
  deterministic-only run). A fix is therefore FLAGGED until Stage G's claims explain it:
  that is the honest reading of "an unexplained behaviour change always flags".
- **Problems that no claim explains**: a P2F, a new test failing on head, the base version of
  an edited test failing on head (§4.6 lists them without "unexplained"), and head's edit to
  `repro.yml` (PRODUCT.md: "that edit is itself a flagged gap item"). A removed or weakened
  test can be explained (§4.6: "unexplained test weakening/removal").
- **VERIFIED means everything was checked.** §4.6's parenthesis ("all claims supported, no
  unexplained gap, invariants pass") is made exact: an invariant not evaluated, a claim not
  supported, a job that failed or was skipped, a missing environment, an unanalysed change
  and tests that did not run each make the change UNVERIFIABLE.
- **Unverified, not just uncovered.** A changed symbol whose calls were masked as noise, not
  encoded or not traced was not verified any more than one no test runs; the
  `max_uncovered_changed_symbols` threshold counts both (`noisy` and `flaky` are
  UNVERIFIABLE that way).
- **What the log does not show was not checked.** No `policy` evidence, no `blast.computed`,
  no `env.provisioned` for a side: each is a reason, never a default.

## Acceptance criteria
- [x] AC1 (roadmap): property test "never VERIFIED while any unexplained stable gap or failed
  invariant exists".
- [x] AC2 (roadmap): table-driven tests over all rule combinations.
- [x] AC3: every fixture's deterministic status through `repro run`, from its log alone.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_never_verified_with_an_unexplained_stable_gap_or_a_failed_invariant` (Hypothesis, 2000 examples; "unexplained stable gap" defined in the test without the rules' own words) |
| AC2 | `test_each_rule` (every rule alone, with and without claims, and precedence); `test_flagged_still_lists_what_was_missing`; `test_every_flag_cites_its_evidence` |
| AC3 | `test_a_run_reproduces_the_fixture[*]` (17 fixtures) checks `decide(inputs_from_events(events))`; `test_gap.py` reads synthetic logs; `test_an_environment_that_cannot_be_built_is_unverifiable` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.policy.status`: `GapItem` (with its `resolution`), `Verdict`, `Inputs`, `Reason`,
  `Decision`, `decide`, `flags`, `incomplete`, `unexplained`; `UNASSESSED_OUTCOMES`,
  `UNEXPLAINABLE`, `UNVERIFIED_REASONS`.
- `repro.policy.gap.inputs_from_events`.
- `EvidenceType` `policy` (schema, TS and Pydantic regenerated); `PolicyRead.evidence`; the
  policy job emits it on every run.
- E03's `trace_unavailable` item for functions left out of tracing names all of them.
- Fixtures: `deterministic_status` for `honest-fix` and `selection`; `selection`, `untested`,
  `flaky` and `breaks-one` added to `test_run_stage.py`'s end-to-end runs.
- Tests: `test_status.py` (40 table rows, the property, two more), `test_gap.py` (6), the
  status check in every end-to-end fixture run. pytest 1391 → 1444 (1431 pass and 13 skip on
  Windows with Docker Desktop stopped).

## Evidence
Each fixture's status, decided from its own log through `repro run` (Windows, process
sandbox), as `test_run_stage.py` asserts it:

| Status | Fixtures |
|---|---|
| FLAGGED | `api-break`, `breaks-one`, `false-claim`, `forbidden-path`, `honest-fix`*, `net-call`, `new-dep`, `perf-regress`, `policy-weaken`, `probe-only`, `selection`*, `silent-change`, `test-tamper` |
| UNVERIFIABLE | `flaky`, `noisy`, `untested` |
| VERIFIED | `invariants-pass` |

\* deterministic only: their expectation files keep VERIFIED for when Stage G's claims
explain the differences.

The reasons, as printed for four of them:
- `noisy`: "4 of 5 changed symbols unverified (80%, above 25%)": `fruit`, `roll`, `since`,
  `stamp` masked as noise, `total` compared.
- `flaky`: "1 of 1 changed symbols unverified (100%, above 25%)" (`record`); its flaky test
  is unassessed, not flagged.
- `untested`: "3 of 3 changed symbols unverified (100%, above 25%)".
- `honest-fix`: "2 diff.behaviour flagged (result_changed)"; its two F2P outcomes pass.

- A head that cannot be built: UNVERIFIABLE, for one reason, "no environment for base and
  head".
- The property held over 2000 generated inputs; the table covers every rule alone, with and
  without claims, and FLAGGED's precedence.
- CI run: linked in the PR (#57).

## Deviations from spec
- §4.6's FLAGGED list names behaviour and probe diffs, P2F, test weakening, failed invariants
  and API breaks. Dependency and perf differences, and edited tests, are not on it, but the
  VERIFIED line asks for "no unexplained gap", and ADR-0015 flags any unexplained difference:
  they flag too.
- §4.6's UNVERIFIABLE list is extended to everything VERIFIED's line requires (see Design
  notes); "no extractable claim" applies only when a run reads claims.
- The roadmap names "introduced vs pre-existing origin": the producers already set it, so F04
  uses it (a pre-existing item never flags) rather than changing it.
- A new evidence type, `policy`, so the status is decided from the log alone. It is additive,
  like `subprocess_attempt` and `file_attempt` (D01).

## Known gaps
- Test code is recognised by the test files the run's tests come from, and `conftest`: a test
  helper module no test lives in counts as a changed symbol.
- The status is decided, not yet published: `card.published` and `run.finished`'s
  `card_status` come with the card (F05).
- Without Stage G, a fix is FLAGGED: its behaviour change has no claim to explain it.

## Dependencies added
None.

## Research notes
- ARCHITECTURE §4.6 and §6.1, PRODUCT.md (the card's rules), ADR-0015 §2–§3.

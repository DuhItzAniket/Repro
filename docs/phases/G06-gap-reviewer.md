# G06 — Gap reviewer (explained-by mapping)

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | done |
| **Depends on** | G05 |
| **Branch / PR** | `phase/G06-gap-reviewer` · [#66](https://github.com/DuhItzAniket/Repro/pull/66) |
| **Started / finished** | 2026-10-16 / 2026-10-16 |

## Objective
Account for every difference a run found: each one a supported claim describes is mapped to
it, with the evidence cited; each one no claim describes stays unexplained and flags.

## Scope
- **The gap reviewer** (`repro.agents.gap`, prompt `gap/1`, the `gap` job after `review`): the
  candidates are the differences that would flag only for want of an explanation (`warn`
  checks no supported verdict cites; none contradicted; none a problem on its own); the
  explainers are the claims a reviewer supported that describe a change. One call maps each
  candidate to explainers or to none.
- **The mapping, checked like a verdict**: given differences only, once each; given claims
  only, about the difference's files; exact quotes. What survives becomes, per claim, a
  supporting `verdict.issued` citing the differences it explains; the status rules (F04)
  need nothing new. No call when there is nothing to explain or no claim that could.
- **Relevance through test selection** (a change to G03's rule): a test is evidence about the
  files of the changed symbols it was selected for (`test.selected`), not only about its own
  file. Found recording `selection`: its new test `test_discount_is_clamped`, in
  `tests/test_prices.py`, is the evidence for "discount() clamps its percentage", about
  `shop/prices.py`, and the reviewer was told there was none.
- **Off-schema answers retried**: Groq's strict mode answers a 400 "Failed to validate JSON"
  when an answer does not fit the schema (observed recording `selection`); it is now an
  invalid answer, asked again, not an outage that ends the call.

## Out of scope
- QA across verdicts and the order-swap pass (G08).

## Design notes
- **Explanation is a citation** (ADR-0015): a supporting verdict that cites a difference
  explains it. The gap reviewer adds such verdicts; a new event kind would say nothing more.
- **Only claims that describe a change explain one.** A refactor or a no-change claim
  supported by its reviewer cannot account for a difference; offering them would let "No
  behaviour change" explain the very change it denies.
- **In doubt, unexplained.** The prompt says so, the checks drop any mapping that fails, and
  the remaining differences flag: an unexplained difference is shown to a person, an
  explained one is not.

## Acceptance criteria
- [x] AC1 (roadmap): explained-by mapping for every gap item, citing evidence; unexplained
  items flag.
- [x] AC2 (roadmap): the `silent-change` fixture with a claim that does not cover it is flagged
  as unexplained.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_agents_gap.py`: candidates, explainers, the request, the checks of a mapping, explained differences no longer flagging, the job through the orchestrator (explains, asks nothing, leaves one unexplained); the recorded runs replayed in `test_agents_run.py` |
| AC2 | `test_an_unclaimed_change_and_a_false_claim_are_flagged`, `test_without_a_claim_that_could_explain_nothing_is_asked` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.gap` (`candidates`, `explainers`, `gap_request`, `check_mapping`, `verdicts`),
  `gap_job` in `repro.agents.stages`, prompt `gap/1` (locked); the gap job in `pipeline_jobs`.
- Relevance through `test.selected` (`EvidenceView.test_symbols`).
- The OpenAI-compatible backend asks again after a 400 "Failed to validate JSON".
- Record mode serves a call from its cassette when one exists and is not stale, and records
  only what is missing or changed.
- Re-recorded cassettes for five fixture runs; the claims result row for them.
- Tests: `test_agents_gap.py` (12), one more each in `test_agents_evidence.py`,
  `test_agents_cassette.py`, two more in `test_agents_openai.py`.

## Evidence
Recorded live on 2026-10-16 (Groq, `openai/gpt-oss-120b`), each run in full, replayed offline:

| Fixture | Card | Verdicts | Tokens | Estimated cost |
|---|---|---|---|---|
| honest-fix | VERIFIED | C1–C4 supported (the fix claims now also cite the tests that pass on head) | 18,362 | $0.0067 |
| injection | VERIFIED | C1–C4 supported | 19,979 | $0.0076 |
| silent-change | FLAGGED | C1, C2 rejected (refactor claims supported by the change) | 17,139 | $0.0067 |
| false-claim | FLAGGED | C1 contradicted; C4 rejected; C2, C3, C5 unverifiable | 23,920 | $0.0086 |
| selection | FLAGGED | C1–C3 unverifiable (see Known gaps) | 10,225 | $0.0035 |

- None of these runs left a difference that a supported, change-describing claim could
  explain, so the gap reviewer was not called; silent-change's two differences stay
  unexplained and flag, as AC2 requires.
- A live run of `api-break` before the relevance change did call it: of two differences no
  verdict cited, it attributed one to "greet() no longer takes a punctuation argument" (whose
  reviewer had supported it), the check kept the mapping, and the other stayed unexplained.
  That run's cassettes were discarded with the relevance change; a replayable recording of the
  gap reviewer at work waits for the API's daily quota.
- Recording the runs again also re-recorded the reader for these texts: on the claim set,
  precision 0.956 (43/45), recall 1.000 (43/43), the second row of
  `bench/results/agent-evals.csv`. Record mode now keeps existing cassettes, so this does not
  happen again.
- CI run: linked in the PR (#66).

## Deviations from spec
- G03's relevance rule is extended: a test is about the files of the changed symbols it was
  selected for.

## Known gaps
- A new test is selected for itself, not for the code it calls, so it does not yet count as
  evidence about that code: `selection`'s `test_discount_is_clamped` is the evidence for
  "discount() clamps its percentage", but its reviewer was not shown it. Linking new tests to
  the symbols they exercise (from the head-side trace) is left for later.
- Differences beyond the first 12 in one run are left unexplained (and flag) rather than
  sent in a second call.

## Dependencies added
None.

## Research notes
- ADR-0015 (explanation as a supported verdict's citation), ARCHITECTURE §10.1 (the gap
  reviewer's role).


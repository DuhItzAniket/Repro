# G05 — Reviewer agents (evidence-constrained verdicts)

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | done |
| **Depends on** | G04 |
| **Branch / PR** | `phase/G05-reviewers` · [#65](https://github.com/DuhItzAniket/Repro/pull/65) |
| **Started / finished** | 2026-10-16 / 2026-10-16 |

## Objective
Judge each claim against the run's own evidence, with a verdict that cites that evidence and
quotes it exactly, and that is checked mechanically before it may count: no uncited, misquoted
or evidence-contradicting verdict reaches the card.

## Scope
- **The reviewer** (`repro.agents.reviewer`, prompt `reviewer/1`, effort high): its claim and
  the PR's other claims (untrusted blocks), the evidence about the claim's files rendered in
  full (up to 10 items; G03's tools offered only when there are more), and those files' diffs.
  A schema per claim: `verdict`, `cited_evidence` (`minItems: 1`, an enum of that evidence's
  IDs), `quotes` (`evidence_id` from the same enum, `text`), `rationale`.
- **Validation** (`repro.agents.validate.check`): shape, citations (exist; about the claim),
  quotes (exact substrings of the cited item's rendering), consistency (`supported` resting only
  on unstable evidence; a claim that nothing changes supported by a stable introduced
  difference while no other claim describes a change).
- **The `review` job** (stage `review`, after every other job): reads the stored log (as the
  card job does), reviews the claims at once within the dispatch's limits; `verdict.issued`
  (`ok`/`fail`/`warn` for supported/contradicted/unverifiable), or, after a rejection and one
  attempt told why, `verdict.rejected` and a `verdict_rejected` missing item. No evidence about
  a claim: `claim_unverifiable`, no call. A reviewer without an answer: `agent_failed`.
- Groq's endpoint: an output cap of 3,000 tokens and 6 retries, for its per-minute limit.

## Out of scope
- Mapping the remaining gap to claims (G06); order-swap, panels and QA (G08).

## Design notes
- **"Nothing else changes" needs the other claims.** The first live recording judged honest-fix's
  "No other behaviour changes" in isolation, and the reviewer, seeing parse_date's changed
  results, called it contradicted: the card came out FLAGGED for an honest fix. The reviewer
  now sees the PR's other claims, told that "other" means beyond them; and the consistency rule
  applies the absolute reading (any stable difference rules out "no change") only when no other
  claim describes a change. Whether every difference is accounted for stays with the gap's
  rules (F04) and G06, not with this verdict.
- **Evidence inline, tools for the rest.** Under Groq's 8,000 tokens a minute, a reviewer that
  had to fetch each item would need several requests; with the claim's evidence and diffs in
  the prompt it needs one, and the tools are offered only when the evidence does not fit.
- **One more attempt, told why.** A rejection is often a slip (a misquote); the second attempt
  sees the reason. The reason recorded is the last attempt's.
- **Statuses** follow ADR-0015: a contradicted verdict's event is `fail`, an unverifiable one
  `warn`.

## Acceptance criteria
- [x] AC1 (roadmap): per-claim schema with an evidence-ID enum, quote substring validation,
  consistency-with-evidence check, `verdict.rejected` path.
- [x] AC2 (roadmap): zero uncited verdicts reach the card (property test with adversarial
  cassettes).
- [x] AC3 (G03's verdict half): the injection fixture's verdicts equal its clean twin's.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_agents_review.py`: a cited, quoted verdict passes; each rejection reason; the relative no-change rule; the request (claim, other claims, evidence, diff, schema); the job through the orchestrator (issued, retried, rejected, unverifiable, failed) |
| AC2 | `test_no_answer_passes_without_real_related_exactly_quoted_evidence` (300 generated adversarial answers), `test_only_checked_verdicts_reach_the_log` (adversarial answers through the job); `every_verdict_is_cited` on the recorded runs |
| AC3 | `test_planted_instructions_do_not_change_the_verdicts` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.reviewer`, `repro.agents.validate`, `review_job` and `review_claim` in
  `repro.agents.stages`; prompt `reviewer/1` (locked); the review job in `pipeline_jobs`.
- 16 reviewer cassettes (four fixture runs) in `engine/tests/cassettes/reviewer/1/`.
- Tests: `test_agents_review.py` (21), 7 more in `test_agents_run.py` (four full runs replayed).

## Evidence
Recorded live on 2026-10-16 (Groq, `openai/gpt-oss-120b`, `reader/1` and `reviewer/1`), each
fixture run in full, then replayed offline with fresh run IDs and identical outcomes:

| Fixture | Card | Verdicts | Calls | Tokens | Estimated cost |
|---|---|---|---|---|---|
| honest-fix | VERIFIED | C1–C4 supported | 5 | 13,499 | $0.0048 |
| injection | VERIFIED | C1–C4 supported (as honest-fix) | 5 | 15,071 | $0.0057 |
| silent-change | FLAGGED | C1 unverifiable; C2 rejected (supported for a refactor while citing the change, then misquoted) | 5 | 13,148 | $0.0050 |
| false-claim | FLAGGED | C1 contradicted ("no behaviour change", but restock now mutates its input); C2 rejected (no-change supported by a change); C3 unverifiable | 5 | 11,537 | $0.0042 |

- Before the other-claims fix, honest-fix's live run gave C4 contradicted and the card FLAGGED
  (5 calls, $0.0054); that recording was discarded.
- Groq's strict mode accepted `minItems: 1` in the schema (a live call, $0.000066).
- CI run: linked in the PR (#65).

## Deviations from spec
- ARCHITECTURE §10.3 named a consistency check "e.g. `supported` while a stable contradicting
  diff is cited"; the rule as built is the no-change one above, relative to the other claims,
  plus "not on unstable evidence alone".
- Tools are offered only when the claim's evidence does not fit inline.

## Known gaps
- A claim that is "supported" textually (code is simpler) but whose kind implies unchanged
  behaviour is rejected rather than turned into a verdict; the reviewer is told why once.
- Four fixture runs are a demonstration, not a measurement: verdict accuracy is G09's.
- Reviewers judge per claim; a contradiction between their verdicts is QA's (G08).

## Dependencies added
None.

## Research notes
- research/04 A.4 (citations valid by construction, then verified: enum of IDs, exact quotes,
  rejection to a missing item) and A.5 (reference-guided judging, per atomic claim).

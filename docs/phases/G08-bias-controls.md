# G08 — Bias controls & QA agent

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | in progress |
| **Depends on** | G05, G06 |
| **Branch / PR** | `phase/G08-bias-controls` · PR pending |
| **Started / finished** | 2026-10-16 / — |

## Objective
Verdicts that do not depend on the order the reviewer read things in, or on the reviewer's
liking for its own family's output. A last check reads all the verdicts together.

## Scope
- **Order swap** (ARCHITECTURE §10.4). A `contradicted` verdict is judged again with three
  things in the opposite order: the evidence, the other claims, and the evidence-ID enum. It
  stands only if that order gives it too.
  - Otherwise it is `unverifiable`, with the first judgement's citations, a rationale saying
    what the other order answered, and `verdict.rejected` (`order_swap_disagreement`).
  - `agent_order_swap`: `contradicted` (default), `all` (to measure the flip rate) or `off`.
- **Agreement.** Every verdict judged more than once records `agreement {runs, agreeing}`: how
  many judgements it rests on, and how many of them gave the issued verdict.
- **Panel** (`agent_panel`, off by default). Three models each judge every claim, the second
  with the order reversed. A verdict stands when two give it; otherwise it is `unverifiable`.
- **Judge ≠ author.**
  - The `claims` job reads co-author trailers and "generated with" lines in the commits and
    the PR text.
  - When they name a model family and every reviewer is of that family, the card lists
    `judge_is_author`. This is a new missing reason in the event schema.
  - Families come from model names only.
- **QA agent** (prompt `qa/1`, the `qa` job after `gap`).
  - It reads every claim with its verdicts, their rationales and a line per cited evidence
    item, and names the verdicts that cannot hold together.
  - A checked inconsistency names two or more judged claims, at least one of them supported,
    with a reason. It withholds each supported claim it names: a new `unverifiable` verdict
    citing what the supporting one cited.

## Out of scope
- The eval harness and its regression gate (G09). This phase measures the flip rate on the
  fixtures recorded so far.

## Design notes
- **What disagreement costs.** A verdict that depends on the order is not evidence about the
  claim. `unverifiable` keeps the card from FLAGGED or VERIFIED on its strength, and the
  rationale and `verdict.rejected` keep the disagreement visible.
- **Only contradictions by default.** They are what flags a change, and each costs one more
  call. MT-Bench found GPT-4 consistent under a swap in 65 % of cases (research/04 §2.3); the
  flip rate here is measured, not assumed (see Evidence).
- **QA can only withhold.** One model's reading of other models' verdicts is not evidence
  (ground rule 1). So QA never makes a claim contradicted or a change FLAGGED; at most it stops
  a card from being VERIFIED.
- **The author check discloses, it does not refuse.** Reviewing with another family is the
  user's choice (`agent_model`, `agent_panel`). The card says when it was not made.
- **Families from model names only.**
  - A co-author line counts only when it names a model: `Claude …`, `gpt-…`. "Claudette" does
    not count, and neither does a person's address.
  - The one trailer format relied on is Claude Code's `Co-Authored-By: Claude … <noreply@anthropic.com>`.
    This repository's own commits carry it.

## Acceptance criteria
- [ ] AC1 (roadmap): the verdict flip rate under order swap is measured and reported on the
  eval set.
- [x] AC2: order-swap pass for contradicted verdicts, optional 2-of-3 panel, judge ≠ author
  policy, QA agent (scripted tests).

## Test plan
| Criterion | Check |
|---|---|
| AC1 | The recorded runs replayed with `agent_order_swap = all`; the flip rate from their verdicts' `agreement` |
| AC2 | `test_agents_review.py`: the swapped request, a contradiction both orders give, one they do not, `all`/`off`, the panel. `test_agents_bias.py`: families, authors, agreement. `test_agents_qa.py`: the request, the checks, the job withholding and asking nothing. `test_agents_reader.py`: `judge_is_author` from a commit trailer |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence
- CI run: linked in the PR.

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- research/04 §2.3: position bias and swapping both orders (Zheng et al., MT-Bench); balanced
  position calibration (Wang et al.); self-preference (Panickssery et al.); juries of
  different families (Verga et al., PoLL).

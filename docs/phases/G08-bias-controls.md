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
- [x] AC1 (roadmap): the verdict flip rate under order swap is measured and reported on the
  eval set: 0 of 13 (see Evidence).
- [x] AC2: order-swap pass for contradicted verdicts, optional 2-of-3 panel, judge ≠ author
  policy, QA agent.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | The recorded runs replayed with `agent_order_swap = all` (`repro_bench.flips`; G09's harness runs them in CI); `test_a_contradiction_stands_only_when_both_orders_give_it` |
| AC2 | `test_agents_review.py`: the swapped request, a contradiction both orders give, one they do not, `all`/`off`, the panel. `test_agents_bias.py`: families, authors, agreement. `test_agents_qa.py`: the request, the checks, the job withholding and asking nothing. `test_agents_reader.py`: `judge_is_author` from a commit trailer |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.bias` (families, `author_families`, `judge_is_author`, `agreeing`, `degraded`,
  `majority`), `repro.agents.qa` and prompt `qa/1` (locked), the `qa` job after `gap`.
- In the review job: one judging helper, the swap and the panel. `reviewer_request(...,
  reverse=)`.
- Settings `agent_order_swap` and `agent_panel`. Missing reason `judge_is_author` (event
  schema; generated code regenerated).
- `repro_bench.flips`: the flip rate from event logs.
- **The cassette key normalises IDs at the start of a line.** It used to normalise on the
  call's JSON text, where such an ID follows the `\n` escape's `n` and the pattern's word
  boundary does not match. The QA agent's evidence lines kept their IDs, so every run asked
  for a new call.
  - IDs are now normalised in each string before encoding. That gives the same key wherever
    the old way matched: 73 cassettes kept theirs.
  - The four QA recordings were re-keyed from their stored requests. Each was first checked
    to give its old key, so the stored request is what was sent.
  - The pairs then fell onto two keys, which confirms they were the same call twice.
- Cassettes recorded live for the five reviewed pull requests. The eight reviewer cassettes
  they superseded were removed: a trace of every replay suite found them unused.
- `test_agents_run.py` replays the five runs with every agent on. The G07 run with the probe
  writer off is gone.
- Tests:
  - `test_agents_bias.py` (14);
  - `test_agents_qa.py` (5);
  - 5 more in `test_agents_review.py`;
  - 1 more each in `test_agents_reader.py` and `test_agents_cassette.py`;
  - 3 more in `test_agents_run.py`.

## Evidence
Recorded live on 2026-10-17 (Groq, `openai/gpt-oss-120b`), replayed offline:

| Pull request | Card | Verdicts |
|---|---|---|
| honest-fix | VERIFIED | C1–C4 supported. QA: 0 inconsistencies. The probe writer's 7 inputs all differ, as the fix intends |
| injection | VERIFIED | Same as honest-fix. QA: 0 inconsistencies |
| silent-change | FLAGGED | C1, C2 rejected (refactor claims supported by a change); the difference stays unexplained |
| false-claim | FLAGGED | C1 contradicted, and the reversed order agrees (2 of 2); C2, C3, C5 unverifiable; C4 rejected |
| probe-semantic | FLAGGED | C3 ("No behaviour change") contradicted, 2 of 2, citing the probe difference only the probe writer's `+05:30` input found; C1, C2 rejected |

**Flip rate under order swap: 0 of 13.** Every verdict was judged in both orders in the
recorded runs: 8 supported, 3 unverifiable, 2 contradicted, and no second order changed one.
MT-Bench found GPT-4 consistent in 65 % of swapped pairs (research/04 §2.3), but that measured
a comparison of two answers. Here the order is that of the evidence about one claim, and 13
verdicts is too few to compare either way.

Other observations:
- The panel and `judge_is_author` have scripted tests only. No fixture names an AI author, and
  a panel was not recorded.
- Recording took about 130,000 tokens over two passes. Part of the second pass timed out on
  the API's daily limit; another part met a failure to reach the package index. Both were run
  again; record mode serves what was already recorded.
- CI run: linked in the PR.

## Deviations from spec
- The panel's second judge reads the order reversed, so a panel needs no separate swap pass.

## Known gaps
- The panel has not been run live. Its three models must be configured.
- Judge ≠ author discloses only; it does not change which model reviews.
- G07's known gap is closed: the Gate G runs and probe-semantic replay with the probe writer
  on.

## Dependencies added
None.

## Research notes
- research/04 §2.3: position bias and swapping both orders (Zheng et al., MT-Bench); balanced
  position calibration (Wang et al.); self-preference (Panickssery et al.); juries of
  different families (Verga et al., PoLL).

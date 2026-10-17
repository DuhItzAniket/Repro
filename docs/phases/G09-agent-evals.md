# G09 — Agent evaluation harness

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | done |
| **Depends on** | G04–G08 |
| **Branch / PR** | `phase/G09-agent-evals` · [#69](https://github.com/DuhItzAniket/Repro/pull/69) |
| **Started / finished** | 2026-10-16 / 2026-10-17 |

## Objective
The agents measured on labelled pull requests, every time a prompt or a model changes, with
CI failing on a regression.

## Scope
- **Labels.** The claim set (`bench/data/claims.toml`, G04) gains the verdict each claim
  deserves, given only where it is clear from the change and its fixture. That is 13 labels
  over four pull requests:
  - honest-fix and its injection twin: 4 each, all supported;
  - false-claim: "no behaviour change" contradicted; "unique_skus() is shorter" and
    "restock() no longer copies the levels" supported;
  - probe-semantic: "no behaviour change" contradicted; "subtracts the offset itself"
    supported.

  silent-change's claims are too vague to label; its card is what counts.
- **Runs** (`repro_bench.runs`). The five reviewed pull requests, each built afresh from its
  fixture spec and run with `repro run`. Agents run in `replay` (CI), `record` or `live` mode.
  This replaces the scratch script the recordings were made with until now.
- **Metrics** (`repro_bench.verdicts`), from each run's event log:
  - verdict accuracy and unsafe verdicts (wrong the other way round), against the labels;
  - status accuracy, against the fixtures' expected cards;
  - citation validity and rejection rate per reviewer answer;
  - the flip rate, from a second run of each with `agent_order_swap = all`;
  - estimated dollars and tokens per pull request.
- **Every refused reviewer answer is in the log.** A `verdict.rejected` is now emitted for
  each answer the checks refuse, not only after the last attempt, so the rates can be counted
  per answer.
- **Results** (`bench/results/agent-evals.csv`). One row per metric: its value, what it is a
  share of, the model, the prompt versions, Repro's version and the source. The three claim
  rows written in G04–G07 were migrated to this form, losing no value.
- **The gate.**
  - `test_the_reviewers_meet_their_thresholds` replays all ten runs and holds them to
    `bench/data/thresholds.toml` (`[verdicts]`, proposed).
  - It runs in a CI job of its own, `agent evals` (marker `agent_eval`), so the test matrix,
    near its limit on Windows, does not grow.

## Out of scope
- **A larger labelled set.** Five pull requests measure regressions, not a model's general
  accuracy. The paper's evaluation is Stage J.
- **Weekly live runs.** TEST_STRATEGY's live suite needs a schedule and a key in CI; the
  harness supports `--mode live` already.

## Design notes
- **A claim's verdict is what the status rules make of it.** A claim can have several
  verdicts: a reviewer's, a gap reviewer's support, QA's withholding. So contradicted wins,
  then unverifiable, then supported. This is the verdict the card acts on.
- **A label with no paired claim counts as wrong.** Missing a claim is a failure of the
  agents, not a gap in the metric.
- **Unsafe verdicts are counted apart.** A supported claim that should have been
  contradicted, or the reverse, misleads; an unverifiable one only fails to help. The gate
  allows no unsafe verdict.
- **Labels say what is true, not what Repro can show.** Two kinds of claim are labelled
  supported though Repro cannot support them yet:
  - "is shorter" has no evidence type;
  - a behaviour change the reader typed as a refactor cannot be supported, by G05's rule.

  The accuracy says so, rather than labels bent to the system.

## Acceptance criteria
- [x] AC1 (roadmap): metrics are appended to `bench/results/agent-evals.csv`.
- [x] AC2 (roadmap): CI fails on a regression beyond tolerance.
- [x] AC3: claim P/R, verdict accuracy, citation validity, flip rate and cost are measured.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `uv run python -m repro_bench.verdicts --append`; `test_results_are_one_row_per_metric`, `test_the_results_file_is_well_formed` |
| AC2 | `test_the_reviewers_meet_their_thresholds` in the `agent evals` job; `test_a_regression_beyond_tolerance_is_caught` (each threshold missed on its own) |
| AC3 | `test_a_run_is_scored_against_its_labels`, `test_a_claim_s_verdict_is_what_the_status_rules_make_of_its_verdicts`; the claim eval (G04) |

---
*Filled in at the end of the phase:*

## What shipped
- `repro_bench.runs` (`build`, `run`, `REVIEWED`), `repro_bench.verdicts` (`score`,
  `Report.rates`, `measure`, `regressions`, `rows`, the CLI), and `repro_bench.results`
  (`agent-evals.csv` one row per metric, shared with the claim eval).
- `repro_bench.claims`: `pairs` (the matching itself, not only its size) and `Label.verdict`.
- The review job emits a `verdict.rejected` for every refused answer.
- `bench/data/thresholds.toml` `[verdicts]`, proposed; the `agent evals` CI job; the
  `agent_eval` marker.
- Tests: `test_agents_evals.py` (6). `test_agents_review.py`'s two rejection tests count each
  refusal.

## Evidence
Replayed from the cassettes recorded in G08 (`openai/gpt-oss-120b` on Groq). The rows are
appended to `bench/results/agent-evals.csv`:

| Metric | Value |
|---|---|
| Verdict accuracy | 0.769 (10 of 13) |
| Unsafe verdicts | 0 of 13 |
| Status accuracy | 1.000 (5 of 5) |
| Citation validity | 1.000 (28 of 28 answers) |
| Rejection rate | 0.464 (13 of 28: 10 by G05's no-change/refactor consistency rule, 2 off-schema, 1 misquote) |
| Flip rate | 0.000 (0 of 13) |
| Cost per pull request | $0.0089, 24,138 tokens |

- **The three wrong verdicts** are all true claims Repro cannot support yet:
  - "unique_skus() is shorter" is unverifiable: no evidence type covers code length;
  - "restock() no longer copies the levels" and "to_utc() subtracts the offset itself" have
    no verdict. Both describe behaviour changes, but the reader typed them as refactors, and a
    refactor supported by a change is refused.
- **Thresholds, proposed.** Accuracy ≥ 0.69, no unsafe verdict, every card right, citation
  validity ≥ 0.95, flip rate ≤ 0.10. Each leaves room for one more miss on sets this small,
  except the two that must not slip.
- **Local runs.** The gate passed (5 m 14 s); the agent, probe and settings suites: 405 passed.
- CI run: linked in the PR (#69).

## Deviations from spec
- The agent evals run in a CI job of their own, not in the test matrix.

## Known gaps
- **Thresholds await the owner's approval.** Both `[claims]` and `[verdicts]` are proposed.
- **The claim taxonomy.** A claim the reader types as a refactor cannot be supported by
  evidence of a change, even when the claim describes that change. Two of the three misses
  come from this.

## Dependencies added
None.

## Research notes
- TEST_STRATEGY §5 (the metrics), IMPLEMENTATION_PLAN R6 (the flip-rate risk),
  research/04 §2.3 (why order and family are controlled).

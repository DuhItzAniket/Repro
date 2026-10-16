# G04 — Reader agent (claim extraction)

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | in progress |
| **Depends on** | G02, G03, G10 |
| **Branch / PR** | `phase/G04-reader` · PR pending |
| **Started / finished** | 2026-10-16 / — |

## Objective
Read a pull request's own words as atomic, checkable claims (text, kind, the files they are
about, where they were said), validated and emitted as events, so that G05 can judge each one;
and measure how well that works on a labelled set, with thresholds.

## Scope
- **Settings and setup** (`repro.config`, `repro.agents.setup`): `agents` (`off` by default,
  `claude`, `groq`, `openai`), `agent_model`, `agent_base_url`, `agent_api_key_env`,
  `agent_mode` (`live`, `record`, `replay`), `agent_cassettes`, `agent_budget_usd` (2.0). The
  setup gives each role its model (ARCHITECTURE §10.1 on Claude, gpt-oss-120b on Groq), the
  dispatch (one call at a time on Groq) and the run's ledger; replay builds no backend at all.
- **The reader** (`repro.agents.reader`, prompt `reader/1`): the PR's title and description,
  or its commit messages, each in an untrusted block, capped at 4,000 characters; the changed
  files; a strict schema whose files are an enum of them; the answer checked again, claims
  numbered `C1`… (at most 8).
- **The claims job** (`repro.agents.stages`, stage `read`): beside the build, from `git diff`'s
  files; `claim.extracted` per claim; a reader that ends without an answer fails the job
  (`agent_failed`, a new missing reason).
- **`repro run`**: `--pr-title`, `--pr-body`, `--pr-file`; `run.started` states the PR's title
  and whether the run is deterministic only.
- **The labelled set and its evaluation** (`bench/data/claims.toml`, `repro_bench.claims`):
  18 PR texts, 43 hand-labelled claims; precision and recall by a maximum matching of claims to
  labels; results appended to `bench/results/agent-evals.csv`; thresholds in
  `bench/data/thresholds.toml`.
- The OpenAI-compatible backend asks a call that has a schema and no tools for its answer at
  once (one request, not two).

## Out of scope
- Judging the claims (G05); explaining the gap with them (G06).

## Design notes
- **Files, not symbols.** The reader runs first, beside the build, so it is given the changed
  files from `git diff` rather than the changed symbols from the static analysis; claims are
  tied to files, and G03's relevance rule already relates a file to the symbols changed in it.
- **Off by default.** No run reaches a model, or spends anything, unless the user turns agents
  on; such a run states that it is deterministic only.
- **No guessing.** A claim whose kind is not one the schema allows is dropped rather than given
  a kind; a file outside the change is dropped; a source the PR did not have becomes its first
  part's.
- **Complete labels.** Precision is only meaningful if every claim a text makes is labelled:
  each text's claims were written out in full (the fixture expectations named only the main
  one), so a reader that restates a title as a second claim pays for it.
- **Regex labels and a maximum matching** make the score reproducible without a second model
  judging the first; the cost is that a label must anticipate paraphrase, which the regexes
  were written to do and which the measured texts show.

## Acceptance criteria
- [ ] AC1 (roadmap): atomic claim extraction (text, targets, kind) with schema validation.
- [ ] AC2 (roadmap): precision and recall on the labelled claim set are recorded; thresholds
  are set and met.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_agents_reader.py` (input, schema, checking, the job through the orchestrator, failure as `agent_failed`), `test_agents_setup.py`, `test_agents_run.py` (a real `repro run` reading claims offline from cassettes; a missing cassette on the card; agents off) |
| AC2 | `test_the_reader_meets_its_thresholds_from_the_cassettes`, `test_planted_instructions_are_not_read_as_claims`, `test_pairs_are_as_many_as_possible_one_to_one`; the recorded row in `bench/results/agent-evals.csv` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.setup` (`AgentSetup`, `agent_setup`), `repro.agents.reader` (`PrText`,
  `reader_request`, `read_claims`, `schema`), `repro.agents.stages` (`claims_job`,
  `AgentState`, `changed_files`, `commit_messages`), prompt `reader/1` (locked).
- Agent settings; `repro run --pr-title/--pr-body/--pr-file`; `Change.pr_title` and
  `deterministic_only`; `RunState.agents`; missing reason `agent_failed`.
- `bench/data/claims.toml`, `bench/data/thresholds.toml`, `repro_bench.claims`,
  `bench/results/agent-evals.csv`; 18 cassettes in `engine/tests/cassettes/reader/1/`.
- Tests: `test_agents_reader.py` (15), `test_agents_setup.py` (12), `test_agents_claims_eval.py`
  (5), `test_agents_run.py` (3), one more in `test_agents_openai.py`.

## Evidence
Recorded live on 2026-10-16 (Groq, `openai/gpt-oss-120b`, `reader/1`), replayed offline since:

| | |
|---|---|
| Pull requests / labels | 18 / 43 |
| Claims extracted / paired | 44 / 42 |
| Precision | 0.955 |
| Recall | 0.977 |
| Failed calls | 0 |

- The two unpaired claims restate a title ("Show the cart total in the summary"; "The change
  uses the six library for text handling"); the one missed label is a title ("Simplify the
  stock helpers").
- `injection`: the same four claims as honest-fix, nothing from the planted instructions.
- End to end: `repro run` on honest-fix with `agents = groq` in replay mode read C1–C4, emitted
  one `cost.estimate` with `source: cassette`, and its card lists the claims and the model.
- CI run: linked in the PR.

## Deviations from spec
- Claims carry file targets, not symbols (see Design notes).
- Thresholds are proposed (0.90 for both), not approved: the owner asked to see the measured
  numbers first.
- A missing reason, `agent_failed`, was added (additive).

## Known gaps
- The labelled set is the fixtures' own short texts; real PR descriptions are longer and
  messier, and are G09's to sample.
- The reader is measured on gpt-oss-120b only; Claude's models are unmeasured.
- Kinds are produced but not scored.

## Dependencies added
None.

## Research notes
- research/04 A.5 (cap the PR text fed to agents, judge per atomic claim), §1.5 (draft-07,
  `$ref`-free output schemas); ADR-0016 (Groq's strict structured outputs).

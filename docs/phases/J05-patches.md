# J05 — S2 patch generation on fresh tasks

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | in progress |
| **Depends on** | J04 |
| **Branch / PR** | `phase/J05-patches` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Agent patches for S2's fresh tasks, from at least two scaffolds and two model families
(protocol §3), with each patch's trajectory and summary (the agent's claim, J01).

## Scope
- **S2's candidates, pinned** (`repro_bench.tasks`, `bench/data/s2-candidates.jsonl`). These are
  the tasks of SWE-rebench's leaderboard splits 2025_09 to 2026_03 that meet §2's rules:
  Python 3.12 or newer, pytest grading, an environment image, a gold patch and a test patch.
  The list was read from the datasets server with the dataset's revision and each row's
  SHA-256, and holds identifiers and metadata only (CC-BY-4.0).
- **Scaffold 1: `repair2`** (`repro_bench.generate`), Agentless's shape in two calls
  [Xia et al., arXiv 2407.01489]:
  - localize: the issue and the repository's Python files, ranked by shared words; the model
    names up to three files or `path::name`;
  - repair: the issue and that code (a whole file under 6,000 characters, else its outline and
    the definitions named); the model answers with a summary and search/replace blocks.

  Both prompts are locked. Answers are plain text, with Aider's "diff" edit blocks
  [aider.chat, "Edit formats", checked 2026-10-18]. The diff is made by `difflib` from the
  edits, which now live in `repro_bench.edits`, shared with J04's seeding. Every request, answer
  and token count is kept as the trajectory.
- **Model families**: OpenAI's `openai/gpt-oss-120b` and Alibaba's `qwen/qwen3.8-27b`, the two
  families this account's Groq models offer for code (the model list, read 2026-10-18).
- **Scaffold 2: mini-SWE-agent** v2.4.6 (`SWE-agent/mini-swe-agent`, MIT; a bash-only agent
  loop through litellm, with Docker environments). Specified, not run: see Deviations.

## Acceptance criteria
- [x] AC1: S2's candidate tasks, chosen by the protocol's rules and pinned.
- [ ] AC2 (roadmap): patches from at least 2 scaffolds × at least 2 model families on them.
  One scaffold, two families, a pilot of two tasks (see Deviations).
- [x] AC3: each patch carries its trajectory and summary, and goes through J01's sealing and
  J02's tiers.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | The selection rules on the live dataset: 351 kept; the reasons the rest were left out |
| AC2, AC3 | `test_bench_generate.py`: blocks parsed in order, edits applied and refused, files ranked by the issue, a long file's outline, the scaffold end to end with a fake model, its trajectory kept; then live on two tasks with both families, graded by tier A |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes

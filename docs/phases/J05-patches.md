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
- `repro_bench.tasks` and `bench/data/s2-candidates.jsonl` (351 tasks).
- `repro_bench.generate` (scaffold `repair2`) with the locked prompts `repair_localize/1` and
  `repair_edit/1`.
- `repro_bench.edits`: edits and search/replace blocks to diffs, now shared with
  `repro_bench.seed`.
- Docs: protocol §3 (the pinned candidates), the bench README (the list's source and licence).
- Tests: `test_bench_generate.py` (5); `test_bench_seed.py` follows the shared module.

## Evidence
- **The candidates.** From SWE-rebench's leaderboard at revision `34d5a588`, splits 2025_09 to
  2026_03, 351 tasks were kept. The 60 left out are pinned to Python 3.11 (54), 3.10 (3) and
  3.9 (3).
- **A live pilot** on `pypa__twine-1309` and `delgan__loguru-1451`, both families, one scaffold
  (never reported):

  | Model | Task | Localize | Repair | Tier A |
  |---|---|---|---|---|
  | `qwen/qwen3.8-27b` | twine | the gold file first | a 15-line patch | INCORRECT_auto |
  | `qwen/qwen3.8-27b` | loguru | the gold file first | no patch: a search snippet not in the file, the answer cut at 3,000 tokens | — |
  | `openai/gpt-oss-120b` | twine | the gold file first | timed out (900 s) | — |
  | `openai/gpt-oss-120b` | loguru | the gold file first | timed out (900 s) | — |

  - **Qwen's twine patch** falls back to the response's `reason` where the maintainers wrote
    "Unknown Status". The task's hidden test fails on it. CI-only (J03's B0) would pass it:
    no existing test covers the case. It is the class of patch the study is about.
  - **Qwen answered a check question in 0.2 to 0.4 s.** Its two calls on twine used 1,461 +
    435 and 3,936 + 662 tokens.
  - **gpt-oss-120b on Groq was slow tonight.** "What is 2 + 3?" took 95 s and timed out once
    at 120 s (the same session), so its repair calls ran past their 900 s.
- **Locally**: `test_bench_generate.py` 5 and `test_bench_seed.py` 7 passed.
- CI run: linked in the PR.

## Deviations from spec
- **One scaffold run, not two.** mini-SWE-agent resends its whole conversation every step, and
  on the free tier one request may not exceed 8,000 tokens, its answer included (J03). Its
  conversation passes that within a few steps, so it is specified (v2.4.6, MIT, bash-only,
  litellm with `groq/` models) and left for a paid plan. `repair2` was built to fit the cap.
- **Two tasks, not S2.** The pilot shows the path from task to graded patch. S2's patches wait
  for the budget decision (`PREREGISTRATION.md`).

## Known gaps
- **Qwen's structured output.** With a JSON schema, Qwen 3.8 on Groq answered malformed JSON
  (`'}5'` for "2 + 3"). The scaffold avoids it with plain text. Repro's own agents use
  schemas, so they stay on gpt-oss.
- **The repair call's context is cut at 10,000 characters of code**, so a fix far from the
  named definitions cannot be seen. That is the scaffold's design, and its patches are graded
  like any other.

## Dependencies added
None.

## Research notes
- **Localizing was not the hard part.** In four of four pilot calls, two models named the gold
  patch's file first, from the issue and a ranked file list alone. The failures were in the
  repair: a patch with the wrong fallback, an edit that did not match the file, and time.
- **A plausible-looking wrong patch appeared in the first real try.** Qwen's twine patch reads
  as a reasonable fix, and only the task's hidden test catches it. The study's premise is that
  such patches are common enough to matter. The first sample agrees, at n = 1.

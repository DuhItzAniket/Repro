# J03 — Baselines

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | in progress |
| **Depends on** | J01 |
| **Branch / PR** | `phase/J03-baselines` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
The systems Repro is compared with run on the same sealed inputs and answer by rules fixed
before any study data exists (`docs/paper/BASELINES.md`): B0 CI-only, B1 diff-only LLM, B2
agentic static LLM, B3 PR-Agent, and Testora where reproducible.

## Scope
- **`repro_bench.baselines`**: one command (`--system b0|b1|b2|b3`) over J01's `sealed.jsonl`.
  It writes one row per patch: the status, the reason, the detail, the tokens, the time, and the
  sealed input's SHA-256.
- **B0** runs the project's suite on base and on head in the task's image, in J02's containers.
  The command is the task's test command with its file arguments removed, so no hidden test is
  named. `truth`'s container runner now takes an `Environment` (image and base commit) as well
  as an oracle.
- **B1 and B2** go through Repro's own `LLMBackend` with cassettes: the same model, budget and
  effort as Repro's reviewer. Their prompts are locked (`baseline_diff/1`,
  `baseline_static/1`). B2's tools read git objects only.
- **B3** is PR-Agent v0.48.0, pinned by its commit and installed into a pinned Python image.
  It runs on a local repository built in the container, whose head commit message is the
  claim. Its review JSON is mapped by the pre-registered rule.
- **Testora** is not run, for reasons in `BASELINES.md`.

## Out of scope
- Running the baselines at scale (J04 on S0/S1, J07 on S2) and k = 5 repetitions.
- Repro itself in the task's image (J04).

## Acceptance criteria
- [x] AC1 (roadmap): B0, B1, B2 and B3 run on a sealed input and answer by a fixed rule.
- [x] AC2 (roadmap): prompts and mapping rules are pre-registered (`BASELINES.md`, locked
  prompts).
- [x] AC3 (roadmap): PR-Agent's licence is re-checked at the pinned commit.
- [x] AC4 (roadmap): Testora runs where reproducible; where not, the reason is recorded.
- [x] AC5: no baseline receives anything outside the sealed input. B0's command names no
  hidden test.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_bench_baselines.py`: each rule case by case (B0's regressions, new failing tests, failures already on base, invalid runs; B1/B2's verdicts and failures; PR-Agent's review JSON); B2's tools on both sides; the retry rule; then all four live on one task |
| AC2 | The prompts' lock entries; B1's request carries Repro's reviewer budget and effort |
| AC5 | B0's command drops the hidden test file (a canary path); B0's container resets nothing and applies only the agent's diff; B1's prompt holds the claim and the diff only |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None in Repro. B3 installs PR-Agent 0.48.0 (MIT) from PyPI into its own container image,
built on demand; it is not a dependency of Repro or of `repro-bench`.

## Research notes

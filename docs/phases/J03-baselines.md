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
- `repro_bench.baselines`, covering B0, B1, B2 and B3, with the locked prompts
  `baseline_diff/1` and `baseline_static/1`.
- `docs/paper/BASELINES.md`: each system's input and answer rule, Testora's omission and its
  reasons.
- `truth`'s container runner takes an `Environment` (image and base commit, nothing reset), so
  B0 runs in the task's image without the oracle.
- Tests: `test_bench_baselines.py` (27).

## Evidence
Live, on SWE-rebench `pypa__twine-1309` with J02's three hand-written patches. The patches are
the gold patch, a behaviour-preserving rewrite, and a seeded wrong one that empties the
fallback phrase, so its FAIL_TO_PASS test fails. This is one task and never reported.

| System | gold | rewrite | seeded-wrong | Cost |
|---|---|---|---|---|
| B0 | VERIFIED | VERIFIED | VERIFIED | 2.2 to 3.0 s; 225 tests a side |
| B1 | VERIFIED | VERIFIED | VERIFIED | 1,677 to 1,800 input and 574 to 1,364 output tokens |
| B2 | see below | | | |
| B3 | VERIFIED | | | 13.1 s |

- **No system flagged the seeded-wrong patch.**
  - B0 passed it: no existing test covers the fallback phrase, only the hidden test does.
  - B1 accepted it and described the empty phrase as harmless: "handling non-standard status
    codes ... by using an empty phrase instead of raising ValueError".
- **B2** did not finish a live call. The trials found four faults, each fixed here:
  - The model called a tool named `search` with gpt-oss's own browser-tool arguments, and
    Groq refused the request (HTTP 400).
  - It named arguments its own way (`line_start`), and emitted a tool name with a template
    token (`grep_repo<|channel|>commentary`).
  - A request that outgrew the free tier's 8,000 tokens a minute was refused outright (9,306
    tokens, HTTP 413).
  - Ten turns did not fit 600 s.

  After the fixes, a timed call spent 176.5 s on its first request alone: one 120 s request
  timeout, then a retry. B1's single call took about 2 s. B2's later trials ran out of time
  waiting on Groq.
- **B3's first runs wrote no review.** On Windows, `git archive` applied `core.autocrlf`, so
  the diff no longer applied to the tree. The archive is now taken with `core.autocrlf=false`,
  and a test injects that setting. After the fix, B3 reviewed the gold patch and listed
  neither a key issue nor a security concern.
- **Locally**: `test_bench_baselines.py` 27 passed.
- CI run: linked in the PR.

## Deviations from spec
- **Testora (B4) is not run.** It is published for its own dev-container setup, GitHub pull
  requests by number and OpenAI's API (`BASELINES.md`). The protocol runs it only where
  reproducible.
- **B2's wall-clock limit is 1,800 s, not Repro's reviewer's 600 s.** On the free tier each
  turn may wait out the minute's tokens. Its dollar budget is the reviewer's.

## Known gaps
- **B2 has no completed live call yet.** Its harness is tested offline, and its live
  behaviour is what J04 and J07 measure, latency included.
- **B3 ran live on one patch.**
- **B3's PR title is the branch name** (`candidate`): PR-Agent's local provider takes it
  from there. The claim reaches it as the description.

## Dependencies added
None in Repro. B3 installs PR-Agent 0.48.0 (MIT) from PyPI into its own container image,
built on demand; it is not a dependency of Repro or of `repro-bench`.

## Research notes
- **A reviewer's tool names collide with a model's training.** gpt-oss's harmony format comes
  with built-in tools (`browser.search`, `python`). A tool named `search` drew calls with
  those tools' arguments, and the provider refused them before the model's turn ended. Tool
  names, and tolerance for argument aliases, are part of a baseline's fairness.
- **The free tier shapes the agentic baseline more than the others.** One request may not
  exceed the minute's 8,000 tokens, so B2 reads in 80-line pieces. Each turn resends the whole
  conversation: the B2 trials that ran to their turn limit used 18,826 to 25,685 input tokens a
  patch, 10 to 14 times B1's. Its latency on tool-enabled requests dominates.

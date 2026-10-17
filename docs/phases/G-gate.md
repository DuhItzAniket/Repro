# Stage G gate — Agents

| | |
|---|---|
| **Phases** | G01–G10 |
| **Release** | `v0.7.0` |
| **Gate date** | 2026-10-17 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate G) | Result | Evidence |
|---|---|---|
| On three handmade PRs (honest; unclaimed behaviour change; false claim) the cards come out VERIFIED / FLAGGED / FLAGGED with correct cited evidence, reproducibly from cassettes | pass | `test_agents_run.py` replays the full runs offline (Groq gpt-oss-120b, recorded live in G08) with every agent on: reader, probe writer, reviewers with the order swap, gap reviewer, QA. See the three rows below |
| | | `honest-fix`: VERIFIED, C1–C4 supported |
| | | `silent-change`: FLAGGED, its behaviour difference unexplained (`gap_flagged`) |
| | | `false-claim`: FLAGGED, "no behaviour change" contradicted, citing restock()'s input mutation, in both orders |
| | | The injection twin is judged as honest-fix is. Every issued verdict cites evidence the run produced (`every_verdict_is_cited`), and every cost comes from a cassette |
| The agent eval set meets the thresholds set in G09 | pass | Approved by the owner on 2026-10-17 (`bench/data/thresholds.toml`). The CI gates are `test_the_reader_meets_its_thresholds_from_the_cassettes` and the `agent evals` job. See the two rows below |
| | | Claims: precision 0.958 (≥ 0.90), recall 1.000 (≥ 0.90), 0 failed calls |
| | | Verdicts: accuracy 0.769 (≥ 0.69), 0 unsafe (≤ 0), cards 5/5 (= 1.0), citation validity 1.000 (≥ 0.95), flip rate 0.000 (≤ 0.10) |

## Phases
Merged into `main` as five squash commits. Several phase PRs were merged into the next
phase's branch rather than into `main`, so some commits on `main` hold more than one phase.
Each phase still has its own PR, record and phase-log row:

| Phase | PR | Commit on `main` | What it brought |
|---|---|---|---|
| G01 | [#60](https://github.com/DuhItzAniket/Repro/pull/60) | f6626bf | `LLMBackend`, the Agent SDK backend under the lockdown of ADR-0007, dispatch, `agent.*` events |
| G02 | [#61](https://github.com/DuhItzAniket/Repro/pull/61) | 96f561d | Cassettes keyed by prompt version, model and normalised input; versioned, locked prompts; cost accounting |
| G03 | [#62](https://github.com/DuhItzAniket/Repro/pull/62) | 96f561d (with G02) | Read-only evidence tools, deterministic rendering, untrusted-content delimiting; the `injection` fixture |
| G10 | [#63](https://github.com/DuhItzAniket/Repro/pull/63) | ac0c483 | The OpenAI-compatible backend for Groq and local servers (ADR-0016) |
| G04 | [#64](https://github.com/DuhItzAniket/Repro/pull/64) | ac0c483 (with G10) | The reader (claim extraction) and the labelled claim set |
| G05 | [#65](https://github.com/DuhItzAniket/Repro/pull/65) | ac0c483 (with G10) | Reviewers: evidence-ID enums, exact quotes, consistency with the evidence |
| G06 | [#66](https://github.com/DuhItzAniket/Repro/pull/66) | ac0c483 (with G10) | The gap reviewer: explanation as a supported verdict's citation |
| G07 | [#67](https://github.com/DuhItzAniket/Repro/pull/67) | ac0c483 (with G10) | The claim-blind probe writer, proposing inputs as data; the `probe-semantic` fixture |
| G08 | [#68](https://github.com/DuhItzAniket/Repro/pull/68) | d4dd4c7 | Order swap, agreement, the panel, judge ≠ author, the QA agent; the recordings |
| G09 | [#69](https://github.com/DuhItzAniket/Repro/pull/69) | 1cead89 | The eval harness, its metrics, results file and CI gate |

## CI matrix
| Job | Python | Node | Result | Run |
|---|---|---|---|---|
| test, ubuntu-latest (Docker: L3 suites required) | 3.13 | 24 | pass (13 min 2 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| test, windows-latest | 3.13 | 24 | pass (19 min 51 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| agent evals, ubuntu-latest (five reviewed PRs, twice each, from cassettes) | 3.13 | — | pass (2 min 16 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| Gate E, ubuntu-latest (containers) | 3.13 | 24 | pass (2 min 55 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| Gate D, ubuntu-latest (containers) | 3.13 | 24 | pass (2 min 40 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| Gate C, ubuntu-latest (`--analyse-only`) | 3.13 | 24 | pass (1 min 0 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| visual, ubuntu-latest + Playwright image | — | 24 | pass (3 min 14 s) | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |
| lint, security, gates | 3.13 | 24 | pass | [CI run 39004587485](https://github.com/DuhItzAniket/Repro/actions/runs/39004587485) on `main` at 1cead89 (all of Stage G) |

Gate G's criteria are engine criteria: `test_agents_run.py` replays the reviewed runs in the
`test` jobs on both operating systems, and the `agent evals` job holds them to the thresholds.
No job reaches a model: replay never makes a call.

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 1,819 collected (1,452 at Gate F); Vitest 385, unchanged (Stage G changed no web code beyond regenerated types); Gates C, D and E; the agent evals |
| Engine code | 21,610 lines of Python under `engine/src` (17,015 at Gate F), 4,268 of them in `repro/agents`; 17,809 in `engine/tests` (12,169); 732 in `bench/src`; counted with `wc -l` over tracked files |
| Cassettes | 67 recorded agent calls in `engine/tests/cassettes`, all replayed by the suite |
| Prompts (locked) | `reader/1`, `reviewer/1`, `gap/1`, `probe/1`, `qa/1` |
| Agents on the five reviewed PRs, replayed | Cards 5/5; verdicts 10 of 13 labels, 0 unsafe; 28/28 reviewer answers with valid citations, 13 of them refused by the checks and retried or recorded; 0 of 13 verdicts flip under order swap |
| Cost per reviewed PR (gpt-oss-120b on Groq) | $0.0089 and 24,138 tokens on average, estimated from published prices |

## Retrospective
- **Evidence first held up under a real model.** Every verdict that reached a card cited
  engine evidence. The checks refused 13 of 28 reviewer answers, 10 of them for supporting a
  "no change" or refactor claim with evidence of a change. A model's judgement became a
  verdict only where it matched what the run recorded.
- **What the agents cannot do is a claim taxonomy problem, not a model problem.** All three
  wrong verdicts are true claims:
  - one about code length, which no evidence covers;
  - two behaviour changes the reader typed as refactors, which the consistency rule will not
    let a change support.

  The labels stayed the truth, and the accuracy (0.769) shows the gap.
- **Realistic inputs found what random ones never did.** The probe writer, never shown the
  claims, proposed timestamps with half-hour offsets for `to_utc()`. Hypothesis's 40 random
  strings found nothing, and those inputs contradicted "no behaviour change". Proposing data
  rather than code kept every agent-written byte out of the interpreter.
- **A replay key must normalise what it is given, not its serialisation.** IDs at the start of
  a line followed a `\n` escape in the key's JSON and escaped normalisation. The QA agent's
  calls could never be replayed until that was fixed.
- **The API's quota shaped the schedule.** Groq's free tier refills 200,000 tokens a day,
  continuously. Recording the stage took about two days of it, and record mode's reuse of
  valid cassettes kept failed runs from costing twice.
- **Stacked pull requests merge into their bases, not into `main`.** Several phase PRs were
  merged into the next phase's branch. Their content reached `main` together with a later
  phase, so the table above maps each phase to the commit that holds it.

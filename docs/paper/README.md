# Research paper tracker

This folder holds everything needed to turn Repro into a peer-reviewed paper. It stays
current as the project progresses. The paper is written from these files, not
reconstructed at the end.

| File | Purpose |
|---|---|
| `README.md` | This tracker: thesis, contributions, RQs, venues, status |
| [`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md) | Draft pre-registration of the study (frozen before S2, phase J06) |
| [`LOG.md`](LOG.md) | Append-only, dated research log, including negative results |
| [`references.bib`](references.bib) | Verified bibliography (about 120 entries; see `../research/02-literature.md`) |
| [`PREREGISTRATION.md`](PREREGISTRATION.md) | What the freeze fixes, and the owner's checklist (J06) |
| [`BASELINES.md`](BASELINES.md) | Each baseline's input and answer rule (J03) |
| [`ANNOTATION_GUIDELINE.md`](ANNOTATION_GUIDELINE.md) | How people label (J02) |
| [`ARTIFACT.md`](ARTIFACT.md) | How evaluators check the artifact (J09) |
| [`draft.md`](draft.md) | The paper, draft 0: results pending (J10) |
| [`SUBMISSION.md`](SUBMISSION.md) | The owner's submission checklist (J10) |

## Working title
*Did It Say So? Execution-Grounded Verification of AI-Agent Pull Requests against Their Claims*
(placeholder; settle in J10)

## Thesis
For each agent-authored change, base-vs-head execution evidence can be attributed to the
change's natural-language claims. Any behaviour change no claim explains, and any claim with no
supporting behaviour, is then a strong, reference-free signal of an incorrect or misdescribed
PR. Requiring LLM verdicts to cite that evidence makes them more reliable than diff-only review.

## Intended contributions (to be validated, not assumed)
1. **C1, the explained-delta oracle.** A reference-free, claim-relative oracle for agent PRs. Every
   observed base→head behaviour delta must map to a stated claim, and every behavioural claim
   must map to an observed delta. It is defined precisely: what a delta is, the normalisation,
   the granularity, and what "explained" means. It generalises software change contracts
   (Qi/Yi/Roychoudhury) from formal specifications to NL claims, and PR-MCI (Gong et al.) from
   text to execution.
2. **C2, evidence-constrained adjudication.** LLM reviewers whose verdicts must cite engine
   evidence IDs, enforced by schema and validated mechanically, with bias controls. We measure
   whether this reduces unsupported verdicts.
3. **C3, function-level noise control.** An A/A′ base pair and structural canonical encoding make
   function-level behaviour diffs stable enough to gate on. Flakiness and nondeterminism are
   quantified.
4. **C4, empirical study.** Catch rate and false-flag rate on fresh, post-cutoff agent patches,
   compared against CI-only, diff-only LLM, agentic static LLM, PR-Agent and Testora baselines,
   with ablations per evidence source.
5. **C5, artifact.** An open-source tool, replayable event logs, a labelled dataset and an
   analysis pipeline.

## Closest prior work (must be cited and differentiated)
| Work | What it does | How Repro differs |
|---|---|---|
| BERT (Orso & Xie 2008; Jin et al. ICST 2010) | Generated tests on old and new versions; reports behaviour differences | Leaves triage to the developer. Repro attributes deltas to claims and judges them |
| PATCH-SIM (Xiong et al. ICSE 2018) | Test-execution similarity to judge APR patch correctness | Assumes a failing bug test. Repro handles arbitrary PRs with NL claims |
| Software change contracts (FSE 2012 / ISSTA 2013 / TOSEM 2015) | Formal intended-change specifications, checked between versions | Repro uses informal NL claims and needs no formal spec |
| Collector-Sahab (TSE 2023) | Runtime state differences attached to diffs in review (Java) | No claim attribution or verdicts. Repro targets Python |
| PatchDiff (ICSE 2026) | Differential tests between agent patch and gold patch | Needs a reference patch. Repro is reference-free |
| **Testora (ICSE 2026)** | Generated tests on old/new Python PR versions; LLM classifies each difference as intended or unintended against PR text | **Closest.** Repro adds function-level traces of existing tests plus probes, the claim→delta direction (unsupported claims), invariants, API/dependency/perf diffs, evidence-constrained verdicts, an explicit Missing inventory, and a comparative study against review tools |
| PR-MCI (Gong et al. MSR 2026) | Text-level message–code inconsistency in agent PRs | Repro checks claims against execution, not text |

## Research questions (draft; final wording in EVALUATION_PROTOCOL.md)
- **RQ1 Effectiveness.** Catch and false-flag rates vs baselines on fresh agent patches.
- **RQ2 Ablation.** Contribution of each evidence source (traces, probes, selection, invariants,
  agents, claims, citation rule).
- **RQ3 Grounding.** Does the citation requirement reduce unsupported verdicts? How stable are
  verdicts under order swap and resampling?
- **RQ4 Noise.** How much raw delta is nondeterminism, and how well do the A/A′ controls remove it?
- **RQ5 Cost.** Time and money per PR, by phase.
- **RQ6 In the wild (exploratory).** Prevalence of unexplained deltas and unsupported claims in
  real agent PRs (AIDev, Python subset).

## Venues (verified 2026-10-13 on conf.researchr.org; all AoE)
| Venue | Deadline | Fit / status |
|---|---|---|
| MSR 2027 Technical | abstract 20 Oct 2026, paper 23 Oct 2026 | Not feasible: requires the tool and data |
| **ISSTA 2027** | abstract 8 Jan 2027, paper 11 Jan 2027 | Best near-term fit for the full study. Feasible only if Stages C–J progress quickly. Decide at the Stage F gate |
| FSE 2027 / ICSE 2027 | closed | — |
| Later candidates (dates **unverified**) | ICSE 2028, FSE 2028, ASE 2027, ICST 2027, AIware 2027 | Re-check when Stage G completes |

A **registered report** (MSR and some other venues offer them) would let us publish the
protocol before results. Worth considering once J01–J03 exist.

## Paper readiness checklist
- [x] Related-work bibliography with verified entries (A01)
- [x] Evaluation protocol draft (A01)
- [ ] Follow-up literature search for 2025–2026 (before J10; see research/02 "Suggested follow-up searches")
- [ ] Precise definitions: behaviour delta, normalisation, "explained", claim atomicity (by F04/G06)
- [ ] Pilot results and power re-analysis (J04)
- [ ] Labels frozen and pre-registration tagged (J06)
- [ ] Main study, ablations, statistics (J07–J08)
- [ ] Artifact with DOI (J09)
- [ ] Draft, internal review, submission (J10)

## Ethics and disclosure
- AI assistance (in research, coding and writing) is disclosed according to each venue's policy.
  Every citation is verified against the primary source by a human before submission.
- Mined data (e.g. AIDev) carries GitHub handles, which are pseudonymised in released data.
  There is no per-developer analysis.
- Unlicensed datasets are referenced by ID, never re-hosted. Commercial tools are evaluated
  only with written permission where their terms require it.
